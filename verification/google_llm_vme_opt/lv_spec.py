"""Strict shared numerical/timing contract; raw INT8 linear, NOT model speed."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct

UPSTREAM="8e4df09b4ea7e065e02d14ce3ae033d40dfd973a"
PACKAGE="tests/cocotb/llm_vme_opt_v1"
PACKET_NAME="coral_llm_vme_opt_i256_d512_v1"
TOP="VmeCoreMini_ITCM256KB_DTCM512KBAxi"
RTL_SHA="477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2"
TILE_SHA="dd932fd04265528f979eba32d7fdb1403a05c5efeb6abe994177c2eaaa973c45"
REFERENCE_SHA="0dbdd0f29be48c78b90f0a6df970fcee050092441b5d218db2278a8b9b94b54f"
QUALIFIED_SHA="3d6753e12b348d8816ca377156233f9ce0b544c773ece8b4376e54b1b78d8d7e"
SCOPE="resident_INT8_linear_RVV_old_VME_vs_RVV_packing_direct_writeback_candidate_not_model"
PROBE_SCOPE="short_candidate_RVV_pack_VME_init_strided_store_and_fallback_arithmetic_not_performance"
MARKER="[LLM_VME_OPT_OBSERVATION] "
CASES=(("decode_tiny",1,32,32),("prefill_tiny",16,32,32),("decode_small",1,64,64),("prefill_small",16,64,64))
SAMPLES=4
PROBE_INDEX=4
PROBE_SHAPES=((1,3,1),(16,4,16),(1,17,17),(16,17,17),(16,32,32),(1,64,64),(7,7,15),(15,63,31),(16,64,64))
BASE_RTL_PACKAGE="tests/cocotb/llm_linear_v1"
GUARD=struct.pack("<I",0x55aa7711)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def testcase(index):
    return 'candidate_probe_test' if index==PROBE_INDEX else 'candidate_'+CASES[index][0]+'_test'


def target(index):return '//'+PACKAGE+':opt_'+testcase(index)


def eta(index):
    return {4:'3-10 minutes',0:'4-10 minutes',1:'10-20 minutes',2:'5-15 minutes',3:'20-45 minutes'}[index]


def checked_xml(tree,expected_name=None):
    tests=list(tree.iter('testcase'))
    if not tests or (expected_name is not None and (len(tests)!=1 or tests[0].get('name')!=expected_name)):
        raise ValueError('Wrong/missing XML testcase')
    if any(list(tree.iter(tag)) for tag in ('failure','error','skipped')):raise ValueError('Failed/skipped XML testcase')
    for node in tree.iter():
        for key in ('failures','errors','skipped'):
            if node.get(key) is not None and int(node.get(key))!=0:raise ValueError('Nonzero XML failure/error/skip count')


def reference_path():
    local=Path(__file__).with_name("baseline_spec.py")
    path=local if local.is_file() else Path(__file__).parent.parent/"google_llm_ops/spec.py"
    if sha(path)!=REFERENCE_SHA:raise ValueError("Original INT8 vector/reference source changed")
    return path


def vectors(index):
    path=reference_path();s=importlib.util.spec_from_file_location("_lv_original_vectors",path)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    if m.CASES!=CASES:raise ValueError("Original shape set changed")
    return m.vectors(index)


def expected_signature(index):
    result=2166136261;gold=vectors(index)["y"]
    for _ in range(SAMPLES):
        for value in gold:
            for _ in range(5):
                for byte in struct.pack("<i",value):result=((result^byte)*16777619)&0xffffffff
    return result


def commands(index):
    _,m,k,n=CASES[index]
    return ((n+15)//16)*((m+15)//16)*((k+3)//4)


def packed_weights(index):
    _,m,k,n=CASES[index]
    return packed_weights_for(m,k,n,vectors(index))


def packed_weights_for(m,k,n,v):
    w=list(struct.unpack("<"+"b"*(k*n),v["w"]))
    kp=(k+3)&~3;np=(n+15)&~15;data=bytearray([0x5a]*4096);bias=[0x55aa7711]*64
    for first in range(0,n,16):
        for r in range(16):
            total=0
            for d in range(kp):
                v=w[d*n+first+r] if d<k and first+r<n else 0
                data[first*kp+d*16+r]=v&255;total+=v
            bias[first+r]=-128*total
    return GUARD*4+bytes(data)+struct.pack("<64i",*bias)+GUARD*4


def workspace(index):
    _,m,k,n=CASES[index]
    return workspace_for(m,k,n,vectors(index),direct=False)


def workspace_for(m,k,n,v,direct):
    x=list(struct.unpack("<"+"b"*(m*k),v["x"]))
    data=bytearray([0x5a]*1024);kp=(k+3)&~3
    for d in range(kp):
        for lane in range(16):data[d*16+lane]=x[lane*k+d]+128 if d<k and lane<m else 0
    last=((n-1)//16)*16
    accum=[0x55aa7711]*256 if direct else [v["y"][c*n+last+r] if c<m and last+r<n else 0 for r in range(16) for c in range(16)]
    return GUARD*4+bytes(data)+struct.pack("<256i",*accum)+GUARD*4


def optimized_workspace(index):
    # All primary shapes use direct stores and must leave the scratch ACC
    # guard untouched; there is deliberately no fabricated scratch readback.
    _,m,k,n=CASES[index]
    return workspace_for(m,k,n,vectors(index),direct=True)


def probe_vectors(index):
    m,k,n=PROBE_SHAPES[index];state=0x1234+index
    def random():
        nonlocal state
        state=(state^(state<<13))&0xffffffff;state=(state^(state>>17))&0xffffffff
        state=(state^(state<<5))&0xffffffff
        return state
    x=[(random()&255)-128 for _ in range(m*k)];w=[random()%255-127 for _ in range(k*n)]
    x[0]=-128;w[0]=-127;x[-1]=127;w[-1]=127
    y=[sum(x[r*k+d]*w[d*n+c] for d in range(k)) for r in range(m) for c in range(n)]
    return dict(x=struct.pack('<'+'b'*len(x),*x),w=struct.pack('<'+'b'*len(w),*w),y=y)


def probe_contract():
    signature=2166136261;checked=commands_total=fast=fallback=0;identity=hashlib.sha256()
    for i,(m,k,n) in enumerate(PROBE_SHAPES):
        v=probe_vectors(i);identity.update(struct.pack('<III',m,k,n)+v['x']+v['w'])
        checked+=m*n;tiles=(n+15)//16;commands_total+=tiles*((k+3)//4)
        if m in (1,16):fast+=tiles
        else:fallback+=tiles
        for value in v['y']:
            for byte in struct.pack('<i',value):signature=((signature^byte)*16777619)&0xffffffff
    return dict(probe_cases=len(PROBE_SHAPES),probe_checked=checked,probe_signature=signature,
        probe_commands=commands_total,probe_fast_tiles=fast,probe_fallback_tiles=fallback,
        probe_vector_set_sha256=identity.hexdigest())


def accept_probe(row):
    expected=dict(schema=1,scope=PROBE_SCOPE,case_id=4,case='optimized_instruction_probe',
        M=16,K=64,N=64,itcm_kib=256,dtcm_kib=512,fault=False,natural_halt=True,firmware_status=3,guard_ok=True,
        input_readback_equal=True,output_readback_equal=True,packed_readback_equal=True,workspace_readback_equal=True,
        stack_low_canary_intact=True,probe_mismatches=0,probe_fail_case=0xffffffff,
        probe_current_case=8,probe_step=6,probe_first_element=0xffffffff,probe_first_actual=0,probe_first_expected=0,
        rtl_sha256=RTL_SHA,requested_cycles=5000000,**probe_contract())
    wrong=[key for key,value in expected.items() if type(row.get(key)) is not type(value) or row[key]!=value]
    if wrong:raise ValueError('Incomplete/wrong candidate hardware probe: '+', '.join(wrong))
    if not re.fullmatch('[a-f0-9]{64}',row.get('elf_sha256','')):raise ValueError('Missing probe ELF identity')
    total=row.get('observation_elapsed_cycles')
    if type(total) is not int or not 0<total<=5000001:raise ValueError('Invalid probe observation')
    return dict(scope=PROBE_SCOPE,case_id=4,probe_cases=row['probe_cases'],checked_elements=row['probe_checked'],
        signature=row['probe_signature'],full_model='NOT_RUN',performance='NOT_MEASURED')


def accept(row,index):
    if index==PROBE_INDEX:return accept_probe(row)
    name,m,k,n=CASES[index];gold=vectors(index)
    required=dict(schema=1,scope=SCOPE,case_id=index,case=name,M=m,K=k,N=n,itcm_kib=256,dtcm_kib=512,
        fault=False,natural_halt=True,firmware_status=3,mismatches=0,guard_ok=True,stack_low_canary_intact=True,
        input_readback_equal=True,output_readback_equal=True,packed_readback_equal=True,workspace_readback_equal=True,
        checked_elements=20*m*n,signature=expected_signature(index),rvv_calls=4,complete_calls=4,reuse_calls=4,
        prepack_calls=1,complete_commands=4*commands(index),reuse_commands=4*commands(index),
        opt_complete_calls=4,opt_reuse_calls=4,opt_prepack_calls=1,
        opt_complete_commands=4*commands(index),opt_reuse_commands=4*commands(index),
        opt_complete_fast_tiles=4*((n+15)//16),opt_reuse_fast_tiles=4*((n+15)//16),
        opt_complete_fallback_tiles=0,opt_reuse_fallback_tiles=0,
        vector_sha256=gold["vector_sha256"],rtl_sha256=RTL_SHA,requested_cycles=10000000)
    wrong=[k for k,v in required.items() if type(row.get(k)) is not type(v) or row[k]!=v]
    if wrong:
        raise ValueError("Incomplete/wrong RVV-VME result or required path did not execute: "+', '.join(wrong))
    if not re.fullmatch("[a-f0-9]{64}",row.get("elf_sha256","")):raise ValueError("Missing ELF identity")
    total,empty,pack=row.get("observation_elapsed_cycles"),row.get("empty_boundary_cycles"),row.get("prepack_once_cycles")
    opt_pack=row.get('opt_prepack_once_cycles')
    if type(total) is not int or not 0<total<=10000001 or type(empty) is not int or empty<0 or type(pack) is not int or not empty<pack<=total:
        raise ValueError("Invalid total/empty/prepack cycles")
    if type(opt_pack) is not int or not empty<opt_pack<=total:raise ValueError('Invalid optimized prepack time')
    arrays=[row.get(key) for key in ("rvv_cycles","complete_cycles","reuse_cycles","opt_complete_cycles","opt_reuse_cycles")]
    if any(not isinstance(a,list) or len(a)!=4 or any(type(v) is not int or not empty<v<=total for v in a) for a in arrays):
        raise ValueError("Invalid first+three steady mcycle samples")
    if sum(map(sum,arrays))+pack+opt_pack>total:raise ValueError("Measured windows exceed firmware observation")
    rvv,full,reuse,opt_full,opt_reuse=arrays
    return dict(case_id=index,case=name,M=m,K=k,N=n,rvv_cycles=rvv,complete_cycles=full,reuse_cycles=reuse,
        first_rvv_over_vme_complete=rvv[0]/full[0],steady_rvv_over_vme_complete=sum(rvv[1:])/sum(full[1:]),
        first_rvv_over_vme_reuse_excluding_prepack=rvv[0]/reuse[0],
        steady_rvv_over_vme_reuse_excluding_prepack=sum(rvv[1:])/sum(reuse[1:]),
        prepack_once_cycles=pack,reuse_first_including_prepack_cycles=pack+reuse[0],
        rvv_over_vme_reuse_first_including_prepack=rvv[0]/(pack+reuse[0]),
        reuse_four_calls_including_prepack_cycles=pack+sum(reuse),
        rvv_over_vme_reuse_four_calls_including_prepack=sum(rvv)/(pack+sum(reuse)),
        opt_complete_cycles=opt_full,opt_reuse_cycles=opt_reuse,opt_prepack_once_cycles=opt_pack,
        steady_old_complete_over_opt_complete=sum(full[1:])/sum(opt_full[1:]),
        steady_old_reuse_over_opt_reuse=sum(reuse[1:])/sum(opt_reuse[1:]),
        first_rvv_over_opt_complete=rvv[0]/opt_full[0],steady_rvv_over_opt_complete=sum(rvv[1:])/sum(opt_full[1:]),
        first_rvv_over_opt_reuse_excluding_prepack=rvv[0]/opt_reuse[0],
        steady_rvv_over_opt_reuse_excluding_prepack=sum(rvv[1:])/sum(opt_reuse[1:]),
        opt_reuse_first_including_prepack_cycles=opt_pack+opt_reuse[0],
        rvv_over_opt_reuse_first_including_prepack=rvv[0]/(opt_pack+opt_reuse[0]),
        opt_reuse_four_calls_including_prepack_cycles=opt_pack+sum(opt_reuse),
        rvv_over_opt_reuse_four_calls_including_prepack=sum(rvv)/(opt_pack+sum(opt_reuse)),
        empty_boundary_cycles=empty,software_commands_per_vme_call=commands(index),
        scope=SCOPE,full_model="NOT_RUN",raw_cycles_not_boundary_subtracted=True)


def checked_host(text):
    rows=re.findall(r"^\[LV_HOST_REFERENCE\] id=(\d+) checked=(\d+) signature=(\d+) commands_each=(\d+) VME_RVV=NOT_RUN$",text,re.M)
    probe=probe_contract()
    marker=f"[LV_OPT_PROBE_HOST_PASS] cases={probe['probe_cases']} checked={probe['probe_checked']} signature={probe['probe_signature']} hardware=NOT_RUN"
    if len(rows)!=4 or text.count('[LV_OPT_PACK_HOST_PASS] cases=980 hardware=NOT_RUN')!=1 or text.count(marker)!=1 or re.search(r"\bFAILED\b|^FAIL[: ]",text,re.M):
        raise ValueError("Native arithmetic/packing test incomplete/failed")
    for i,values in enumerate(rows):
        _,m,k,n=CASES[i]
        if tuple(map(int,values))!=(i,20*m*n,expected_signature(i),4*commands(i)):
            raise ValueError("Native packing/reference signature differs")
