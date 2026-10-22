"""Strict shared numerical/timing contract; raw INT8 linear, NOT model speed."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct

UPSTREAM="8e4df09b4ea7e065e02d14ce3ae033d40dfd973a"
PACKAGE="tests/cocotb/llm_vme_profile_v1"
PACKET_NAME="coral_llm_vme_profile_i256_d512_v1"
TOP="VmeCoreMini_ITCM256KB_DTCM512KBAxi"
RTL_SHA="477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2"
TILE_SHA="dd932fd04265528f979eba32d7fdb1403a05c5efeb6abe994177c2eaaa973c45"
REFERENCE_SHA="0dbdd0f29be48c78b90f0a6df970fcee050092441b5d218db2278a8b9b94b54f"
QUALIFIED_SHA="3d6753e12b348d8816ca377156233f9ce0b544c773ece8b4376e54b1b78d8d7e"
SCOPE="resident_INT8_VME_stage_diagnostics_with_uninstrumented_RVV_and_VME_controls_not_model"
PHASES=('input_pack','accumulator_init','load_config_issue','readback_and_possible_completion_wait','output_layout')
MARKER="[LLM_VME_PROFILE_OBSERVATION] "
CASES=(("decode_tiny",1,32,32),("prefill_tiny",16,32,32),("decode_small",1,64,64),("prefill_small",16,64,64))
SAMPLES=4
GUARD=struct.pack("<I",0x55aa7711)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
            for _ in range(4):
                for byte in struct.pack("<i",value):result=((result^byte)*16777619)&0xffffffff
    return result


def commands(index):
    _,m,k,n=CASES[index]
    return ((n+15)//16)*((m+15)//16)*((k+3)//4)


def packed_weights(index):
    _,m,k,n=CASES[index];w=list(struct.unpack("<"+"b"*(k*n),vectors(index)["w"]))
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
    _,m,k,n=CASES[index];v=vectors(index);x=list(struct.unpack("<"+"b"*(m*k),v["x"]))
    data=bytearray([0x5a]*1024);kp=(k+3)&~3
    for d in range(kp):
        for lane in range(16):data[d*16+lane]=x[lane*k+d]+128 if d<k and lane<m else 0
    last=((n-1)//16)*16
    accum=[v["y"][c*n+last+r] if c<m and last+r<n else 0 for r in range(16) for c in range(16)]
    return GUARD*4+bytes(data)+struct.pack("<256i",*accum)+GUARD*4


def accept(row,index):
    name,m,k,n=CASES[index];gold=vectors(index)
    required=dict(schema=1,scope=SCOPE,case_id=index,case=name,M=m,K=k,N=n,itcm_kib=256,dtcm_kib=512,
        fault=False,natural_halt=True,firmware_status=3,mismatches=0,guard_ok=True,stack_low_canary_intact=True,
        input_readback_equal=True,output_readback_equal=True,packed_readback_equal=True,workspace_readback_equal=True,
        checked_elements=16*m*n,signature=expected_signature(index),rvv_calls=4,complete_calls=4,reuse_calls=4,
        profile_calls=4,profile_commands=4*commands(index),
        prepack_calls=1,complete_commands=4*commands(index),reuse_commands=4*commands(index),
        vector_sha256=gold["vector_sha256"],rtl_sha256=RTL_SHA,requested_cycles=10000000)
    wrong=[k for k,v in required.items() if type(row.get(k)) is not type(v) or row[k]!=v]
    if wrong:
        raise ValueError("Incomplete/wrong RVV-VME result or required path did not execute: "+', '.join(wrong))
    if not re.fullmatch("[a-f0-9]{64}",row.get("elf_sha256","")):raise ValueError("Missing ELF identity")
    total,empty,pack=row.get("observation_elapsed_cycles"),row.get("empty_boundary_cycles"),row.get("prepack_once_cycles")
    if type(total) is not int or not 0<total<=10000001 or type(empty) is not int or empty<0 or type(pack) is not int or not empty<pack<=total:
        raise ValueError("Invalid total/empty/prepack cycles")
    arrays=[row.get(key) for key in ("rvv_cycles","complete_cycles","reuse_cycles","profile_cycles")]
    if any(not isinstance(a,list) or len(a)!=4 or any(type(v) is not int or not empty<v<=total for v in a) for a in arrays):
        raise ValueError("Invalid first+three steady mcycle samples")
    if sum(map(sum,arrays))+pack>total:raise ValueError("Measured windows exceed firmware observation")
    rvv,full,reuse,profile=arrays
    times,counts=row.get('profile_segment_cycles'),row.get('profile_segment_counts')
    expected_counts=[1]+[((n+15)//16)]*4
    if not isinstance(times,list) or len(times)!=20 or any(type(v) is not int or v<=empty for v in times):
        raise ValueError('Invalid profile stage durations')
    if not isinstance(counts,list) or len(counts)!=20 or any(type(v) is not int for v in counts) or counts!=expected_counts*4:
        raise ValueError('Wrong profile stage coverage/counts')
    stage_sums=[sum(times[s*5:s*5+5]) for s in range(4)]
    if any(value>outer for value,outer in zip(stage_sums,profile)):
        raise ValueError('Stage intervals exceed enclosing profile call')
    stages={name:[times[s*5+phase] for s in range(4)] for phase,name in enumerate(PHASES)}
    return dict(case_id=index,case=name,M=m,K=k,N=n,rvv_cycles=rvv,complete_cycles=full,reuse_cycles=reuse,
        first_rvv_over_vme_complete=rvv[0]/full[0],steady_rvv_over_vme_complete=sum(rvv[1:])/sum(full[1:]),
        first_rvv_over_vme_reuse_excluding_prepack=rvv[0]/reuse[0],
        steady_rvv_over_vme_reuse_excluding_prepack=sum(rvv[1:])/sum(reuse[1:]),
        prepack_once_cycles=pack,reuse_first_including_prepack_cycles=pack+reuse[0],
        rvv_over_vme_reuse_first_including_prepack=rvv[0]/(pack+reuse[0]),
        reuse_four_calls_including_prepack_cycles=pack+sum(reuse),
        rvv_over_vme_reuse_four_calls_including_prepack=sum(rvv)/(pack+sum(reuse)),
        empty_boundary_cycles=empty,software_commands_per_vme_call=commands(index),
        profile_cycles=profile,profile_stage_cycles=stages,profile_stage_counts_per_call=dict(zip(PHASES,expected_counts)),
        profile_unassigned_cycles=[outer-used for outer,used in zip(profile,stage_sums)],
        profile_minus_uninstrumented_reuse_cycles=[p-u for p,u in zip(profile,reuse)],
        profile_stage_fraction_of_instrumented_call={name:sum(values)/sum(profile) for name,values in stages.items()},
        stage_scope='instrumented_software_windows_not_pure_array_latency_or_v2_speedup',
        completion_wait_attribution='may_shift_to_readback; probes_fence_memory_not_matrix_retirement',
        scope=SCOPE,full_model="NOT_RUN",raw_cycles_not_boundary_subtracted=True)


def checked_host(text):
    rows=re.findall(r"^\[LV_HOST_REFERENCE\] id=(\d+) checked=(\d+) signature=(\d+) commands_each=(\d+) VME_RVV=NOT_RUN$",text,re.M)
    if len(rows)!=4 or text.count('[LV_PACK_HOST_PASS] cases=735 hardware=NOT_RUN')!=1 or re.search(r"\bFAILED\b|^FAIL[: ]",text,re.M):
        raise ValueError("Native arithmetic/packing test incomplete/failed")
    for i,values in enumerate(rows):
        _,m,k,n=CASES[i]
        if tuple(map(int,values))!=(i,16*m*n,expected_signature(i),4*commands(i)):
            raise ValueError("Native packing/reference signature differs")
