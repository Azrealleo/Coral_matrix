"""Isolated larger-shape tools, derived from pinned qualified M-sweep tools.

Build-only by default; no simulator is executed by this generator.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent
SWEEP_PIN='add3bc4396da4023a5cc716758e408bdb8c092b5'
GENERATED='verification/google_llm_vme_large_v1'
CASES=(('control_m16_k64_n64',16,64,64),('decode_m1_k128_n128',1,128,128),
       ('prefill_m16_k128_n128',16,128,128),('tiled_m32_k128_n128',32,128,128),
       ('tail_m17_k128_n128',17,128,128),('decode_m1_k256_n64',1,256,64),
       ('prefill_m16_k256_n64',16,256,64),('tiled_m32_k256_n64',32,256,64))
PROBES=((1,3,1),(16,64,64),(17,7,17),(31,17,31),
        (32,4,128),(1,255,17),(2,256,127),(17,65,17))


def pinned_sweep(repo):
    raw=subprocess.check_output(['git','-C',str(repo),'show',SWEEP_PIN+':verification/google_llm_vme_sweep/materialize.py'])
    module=types.ModuleType('_large_pinned_sweep')
    module.__file__=str(repo/'verification/google_llm_vme_sweep/materialize.py')
    exec(compile(raw,module.__file__,'exec'),module.__dict__)
    return module,hashlib.sha256(raw).hexdigest()


def transform(name,text,base):
    r=base.replace
    text=text.replace('llm_vme_sweep_v1','llm_vme_large_v1').replace('llm_vme_sweep_','llm_vme_large_')
    text=text.replace('LLM_VME_SWEEP','LLM_VME_LARGE')
    if name=='linear_core.h':
        text=r(text,'kMaxM=16,kMaxK=64,kMaxN=64,kCapacity=kMaxM*kMaxN',
               'kMaxM=16,kMaxK=256,kMaxN=128,kCapacity=32*kMaxN')
        text=r(text,'sizeof(PackedWeights)==4384 && sizeof(Workspace)==2080 && sizeof(GuardedOutput)==4128',
               'sizeof(PackedWeights)==33312 && sizeof(Workspace)==5152 && sizeof(GuardedOutput)==16416')
    elif name=='optimized_core.h':
        text=r(text,'// signed per-channel sums in INT16 (K<=64 => [-8192,8128]), widen before <<7.',
               '// signed per-channel sums in INT16 (K<=256 => [-32768,32512]), widen before <<7.\nstatic_assert(kMaxK<=256,"INT16 channel sum bound");')
    elif name=='core_test.cc':
        text=r(text,'1,65,4','1,257,4');text=r(text,'1,4,65','1,4,129')
        text=r(text,'w,65,4,optimized','w,257,4,optimized')
    elif name=='linear_bench.cc':
        text=r(text,'#include "optimized_core.h"','#include "blocked_core.h"')
        text=r(text,'lv_x[16*64],lv_w[64*64]','lv_x[32*256],lv_w[256*128]')
        text=r(text,'GuardedOutput lv_rvv_out,lv_complete_out,lv_reuse_out;',
               'GuardedOutput lv_rvv_out,lv_complete_out,lv_reuse_out;\nGuardedOutput lv_gold;')
        start=text.index('constexpr int kShapes[][3]=');end=text.index(';',start)
        text=text[:start]+'constexpr int kShapes[][3]={'+','.join('{'+f'{m},{k},{n}'+'}' for _,m,k,n in CASES)+'}'+text[end:]
        start=text.index('constexpr int kProbeShapes[][3]=');end=text.index(';',start)
        text=text[:start]+'constexpr int kProbeShapes[][3]={'+','.join('{'+','.join(map(str,s))+'}' for s in PROBES)+'}'+text[end:]
        for before,after in [('return RunComplete(','return RunBlockedLegacyComplete('),
                             ('return RunPrepared(','return RunBlockedLegacyPrepared('),
                             ('return RunOptimizedComplete(','return RunBlockedOptimizedComplete('),
                             ('return RunOptimizedPrepared(','return RunBlockedOptimizedPrepared('),
                             ('if(!RunOptimizedComplete(','if(!RunBlockedOptimizedComplete(')]:text=r(text,before,after)
        text=r(text,'Reset(lv_opt_reuse_weights);Reset(lv_opt_complete_weights);Reset(lv_opt_workspace);',
               '''Reset(lv_opt_reuse_weights);Reset(lv_opt_complete_weights);Reset(lv_opt_workspace);
  // Independent INT64 reference ONCE, outside every timed kernel window.
  // Five paths/four outputs are still checked against it and independently by
  // the host. Avoid repeating scalar reference work four times on larger RTL.
  Reset(lv_gold);
  for(int r=0;r<m;++r)for(int c=0;c<n;++c) {
    int64_t value=0;for(int depth=0;depth<k;++depth)value+=int(lv_x[r*k+depth])*int(lv_w[depth*n+c]);
    lv_gold.data[r*n+c]=static_cast<int32_t>(value);
  }''')
        text=r(text,'int64_t expected=0;for(int d=0;d<k;++d)expected+=int(lv_x[r*k+d])*int(lv_w[d*n+c]);\n      const int at=r*n+c;',
               'const int at=r*n+c;const int64_t expected=lv_gold.data[at];')
        text=r(text,'if(!OutputGuard(lv_rvv_out,m*n)', 'if(!OutputGuard(lv_gold,m*n)||!OutputGuard(lv_rvv_out,m*n)')
        text=r(text,'4u*((n+15)/16)*((k+3)/4)','4u*((m+15)/16)*((n+15)/16)*((k+3)/4)')
        text=r(text,'4u*((n+15)/16)','4u*((m+15)/16)*((n+15)/16)',2)
        text=r(text,'q<13','q<8');text=r(text,'for(unsigned i=0;i<6;++i)','for(unsigned i=0;i<8;++i)')
        text=r(text,'if(selected==6)','if(selected==8)');text=r(text,'if(selected>=6)','if(selected>=8)')
        text=r(text,'Fill(m,k,n,0x1234+q);',
               'Fill(m,k,n,0x1234+q);\n    if(k==256 && n>=2)for(int depth=0;depth<k;++depth){lv_w[depth*n]=127;lv_w[depth*n+1]=-127;}')
    elif name=='lv_spec.py':
        start=text.index('CASES=');end=text.index('\nSAMPLES=',start);text=text[:start]+'CASES='+repr(CASES)+text[end:]
        text=r(text,'PROBE_INDEX=6','PROBE_INDEX=8')
        start=text.index('PROBE_SHAPES=');end=text.index('\nBASE_RTL_PACKAGE=',start);text=text[:start]+'PROBE_SHAPES='+repr(PROBES)+text[end:]
        text=r(text,'resident_INT8_M_sweep_same_ELF_RVV_old_VME_vs_all_M_direct_writeback_not_model',
               'resident_INT8_larger_KN_M_blocking_same_ELF_five_paths_not_model')
        text=r(text,'short_all_M_RVV_pack_VME_init_strided_store_arithmetic_not_performance',
               'short_larger_KN_M_blocking_tail_and_signed_compensation_not_performance')
        start=text.index('    return {',text.index('def eta('));end=text.index('\n',start)
        text=text[:start]+"    return {8:'5-25 minutes',0:'10-30 minutes',1:'10-30 minutes',2:'25-60 minutes',3:'45-90 minutes',4:'30-70 minutes',5:'15-40 minutes',6:'25-60 minutes',7:'45-90 minutes'}[index]"+text[end:]
        text=r(text,'data=bytearray([0x5a]*4096);bias=[0x55aa7711]*64','data=bytearray([0x5a]*32768);bias=[0x55aa7711]*128')
        text=r(text,'struct.pack("<64i",*bias)','struct.pack("<128i",*bias)')
        text=r(text,'data=bytearray([0x5a]*1024);kp=(k+3)&~3',
               'base=((m-1)//16)*16;tokens=m-base\n    x=x[base*k:]\n    data=bytearray([0x5a]*4096);kp=(k+3)&~3')
        text=r(text,'d<k and lane<m else 0','d<k and lane<tokens else 0')
        text=r(text,'v["y"][c*n+last+r] if c<m and last+r<n', 'v["y"][(base+c)*n+last+r] if c<tokens and last+r<n')
        text=r(text,'checked+=m*n;tiles=(n+15)//16;', 'checked+=m*n;tiles=((m+15)//16)*((n+15)//16);')
        text=r(text,"M=16,K=64,N=64,itcm_kib=256", "M=17,K=65,N=17,itcm_kib=256")
        text=r(text,'probe_current_case=12,probe_step=6','probe_current_case=7,probe_step=6')
        text=r(text,'requested_cycles=5000000','requested_cycles=20000000')
        text=r(text,'total<=5000001','total<=20000001')
        text=r(text,'requested_cycles=10000000)','requested_cycles=30000000)')
        text=r(text,'total<=10000001 or type(empty)','total<=30000001 or type(empty)')
        text=r(text,'4*((n+15)//16)','4*((m+15)//16)*((n+15)//16)',2)
        text=r(text,'x[0]=-128;w[0]=-127;x[-1]=127;w[-1]=127',
               'x[0]=-128;w[0]=-127;x[-1]=127;w[-1]=127\n    if k==256 and n>=2:\n        for depth in range(k):w[depth*n]=127;w[depth*n+1]=-127')
        text=r(text,"or text.count(marker)!=1", "or text.count('[LV_LARGE_BLOCK_HOST_PASS] cases=1008 hardware=NOT_RUN')!=1 or text.count(marker)!=1")
    elif name=='lv_bench.py':
        text=r(text,'budget=5000000 if probe else 10000000','budget=20000000 if probe else 30000000')
        text=r(text,"('lv_x',gold['x'],1024),('lv_w',gold['w'],4096)","('lv_x',gold['x'],8192),('lv_w',gold['w'],32768)")
        text=r(text,'spec.GUARD*(1024-m*n)','spec.GUARD*(4096-m*n)')
        text=r(text,"'lv_rvv_out','lv_complete_out','lv_reuse_out','lv_opt_complete_out','lv_opt_reuse_out'",
               "'lv_rvv_out','lv_complete_out','lv_reuse_out','lv_opt_complete_out','lv_opt_reuse_out','lv_gold'")
        text=r(text,'size_bytes=4128','size_bytes=16416');text=r(text,'size_bytes=4384','size_bytes=33312')
        text=r(text,'size_bytes=2080','size_bytes=5152',2)
    elif name=='lv_audit.py':
        text=r(text,'lv_x=1024,lv_w=4096','lv_x=8192,lv_w=32768')
        text=text.replace('=4128','=16416').replace('=4384','=33312').replace('=2080','=5152')
        text=r(text,'LINKER=','SIZES.update(lv_gold=16416)\nLINKER=')
    elif name=='prepare.py':
        text=r(text,'"vme_tile.h","optimized_core.h"','"vme_tile.h","optimized_core.h","blocked_core.h"')
        text=r(text,'cc_test(name="host_reference_test",srcs=["linear_bench.cc","linear_core.h","optimized_core.h"],',
               'cc_test(name="host_reference_test",srcs=["linear_bench.cc","linear_core.h","optimized_core.h","blocked_core.h"],')
        text=r(text,'"lv_packet.py","lv_bench.py","optimized_core.h","vm_bench.py"',
               '"lv_packet.py","lv_bench.py","optimized_core.h","vm_bench.py","blocked_core.h","blocked_test.cc"')
        # Native blocked test headers belong in srcs, not cc_test.hdrs.
        text=r(text,'py_library(name="support",',
               'cc_test(name="host_blocked_test",srcs=["blocked_test.cc","linear_core.h","optimized_core.h","blocked_core.h"],\n    copts=["-std=c++17","-O2","-DLV_HOST=1"],)\npy_library(name="support",')
        start=text.index('    testcases=');end=text.index(',\n    verilator_model=',start)
        text=text[:start]+'    testcases='+repr(['candidate_probe_test']+['candidate_'+c[0]+'_test' for c in CASES])+text[end:]
    elif name=='vm_bench.py':
        text=text[:text.index('@cocotb.test()')]
        for i,label in [(8,'probe')]+[(i,c[0]) for i,c in enumerate(CASES)]:
            text+=f'@cocotb.test()\nasync def candidate_{label}_test(dut):await run_vm(dut,{i})\n\n'
    elif name in ('vm.py','server.py'):
        text=r(text,'choices=range(7),default=6','choices=range(9),default=8')
        text=r(text,'default=3600','default=5400') if name=='vm.py' else text
        if name=='vm.py':
            text=r(text,"sequence=(spec.PROBE_INDEX,3) if a.plan=='quick'", "sequence=(spec.PROBE_INDEX,0) if a.plan=='quick'")
            text=r(text,"print('[LLM_VME_LARGE_VM_COMPARISON] '",
                   "print('[LLM_VME_LARGE_VM_WALL] '+json.dumps(dict(case_id=index,wall_seconds=timing.get('elapsed_seconds'),includes_bazel_overhead=True)),flush=True)\n    print('[LLM_VME_LARGE_VM_COMPARISON] '")
    elif name=='summarize.py':
        text=r(text,'Need six distinct server cases','Need eight distinct server cases')
        text=r(text,"'Measured M points only: no interpolation or universal crossover threshold. Complete and reused-weight routing can differ.',",
               "'Logical M>16 is split into sequential tiles, weights packed once per logical call; no overlap/DMA.',\n        'Kernel timing includes blocking/packing/initialization/readback/writeback, excludes scalar oracle and checks. No universal crossover threshold.',")
    elif name=='build_export.sh':
        text=r(text,'"$lv_pkg:host_reference_test" "$lv_pkg:host_packing_test"',
               '"$lv_pkg:host_reference_test" "$lv_pkg:host_packing_test" "$lv_pkg:host_blocked_test"')
    elif name=='run_vm.sh':
        text=text.replace('0|1|2|3|4|5','0|1|2|3|4|5|6|7');text=r(text,'--case 6','--case 8')
    elif name=='run_server.sh':
        text=text.replace('0|1|2|3|4|5','0|1|2|3|4|5|6|7').replace('[0-5]','[0-7]')
        text=r(text,'--case 6','--case 8')
        text=r(text,'opt_cases=(3);else opt_cases=(0 1 2 3 4 5)', 'opt_cases=(0);else opt_cases=(0 1 2 3 4 5 6 7)')
    elif name=='tomorrow.sh':
        text=r(text,'quick roughly 20-45min; all roughly 80-180min',
               'quick roughly 20-60min; all roughly 3-7h, larger cases prefer stable server')
    return text


def sources(repo=REPO):
    base,digest=pinned_sweep(repo)
    inherited,parents=base.sources(repo)
    files={}
    for name,raw in inherited.items():
        if name.startswith(base.GENERATED+'/'):
            if Path(name).name=='README.md':continue
            name=GENERATED+'/'+Path(name).name
            raw=transform(Path(name).name,raw.decode(),base).encode()
        files[name]=raw
    for name in ('README.md','blocked_core.h','blocked_test.cc'):
        files[GENERATED+'/'+name]=(HERE/name).read_bytes()
    return files,dict(base_revision=base.PARENT,sweep_revision=SWEEP_PIN,sweep_generator_sha256=digest,parent_files=parents)


def expected(repo=REPO):
    files,provenance=sources(repo)
    return files,dict(schema=1,kind='llm_vme_larger_shapes_tools_v1',simulation='NOT_RUN',
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),cases=[list(c) for c in CASES],
        probe_shapes=[list(s) for s in PROBES],provenance=provenance,
        files={n:hashlib.sha256(raw).hexdigest() for n,raw in files.items()})


def materialize(destination,repo=REPO):
    files,record=expected(repo);destination=Path(destination).absolute()
    if destination.exists():raise ValueError('Destination exists; nothing overwritten')
    destination.mkdir()
    for name,raw in files.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as f:f.write(raw)
    with (destination/'tool-manifest.json').open('x',encoding='utf-8') as f:json.dump(record,f,indent=2)
    verify(destination,repo)
    print('[LLM_VME_LARGE_TOOLS] '+str(destination/GENERATED),flush=True)
    return destination/GENERATED


def verify(destination,repo=REPO):
    destination=Path(destination).resolve(strict=True);_,record=expected(repo)
    if json.loads((destination/'tool-manifest.json').read_text())!=record:raise ValueError('Tool provenance changed')
    inventory={p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
               for p in destination.rglob('*') if p.is_file() and p!=destination/'tool-manifest.json'}
    if any(p.is_symlink() for p in destination.rglob('*')) or inventory!=record['files']:
        raise ValueError('Missing/extra/changed generated tools')
    return destination/GENERATED


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--existing',action='store_true');a=p.parse_args()
    try:
        if a.existing:print('[LLM_VME_LARGE_TOOLS_VERIFIED] '+str(verify(a.output)))
        else:materialize(a.output)
    except Exception as e:print('[LLM_VME_LARGE_STOP] '+str(e),file=sys.stderr);sys.exit(1)
