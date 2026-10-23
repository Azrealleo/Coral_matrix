"""Isolate a mature-kernel-inspired K-loop trial; never upgrade RTL or ISA."""
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
PIN='add3bc4396da4023a5cc716758e408bdb8c092b5'
GENERATED='verification/google_llm_vme_mature_v1'


def pinned(repo=REPO):
    path='verification/google_llm_vme_sweep/materialize.py'
    raw=subprocess.check_output(['git','-C',str(repo),'show',PIN+':'+path])
    module=types.ModuleType('_mature_pinned_sweep');module.__file__=str(repo/path)
    exec(compile(raw,module.__file__,'exec'),module.__dict__)
    return module,hashlib.sha256(raw).hexdigest()


def qualified_header(text):
    # Only rename entry points / namespace; instructions and algorithm stay
    # unchanged. Unique names also prevent ADL from finding candidate functions.
    for old,new in (('PrepareOptimizedWeights','PrepareQualifiedWeights'),
                    ('PackOptimizedInput','PackQualifiedInput'),
                    ('RunOptimizedPrepared','RunQualifiedPrepared'),
                    ('RunOptimizedComplete','RunQualifiedComplete')):
        text=text.replace(old,new)
    return text.replace('namespace llm_vme {','namespace llm_vme { namespace qualified {',1).replace(
        '}  // namespace llm_vme','}}  // namespace llm_vme::qualified',1)


def transform(name,text,base):
    r=base.replace
    text=text.replace('llm_vme_sweep_v1','llm_vme_mature_v1').replace('llm_vme_sweep_','llm_vme_mature_')
    text=text.replace('LLM_VME_SWEEP','LLM_VME_MATURE')
    if name=='optimized_core.h':
        text=r(text,'#include "linear_core.h"','#include "linear_core.h"\n#include "hoisted_loop.h"')
        start=text.index('  for(int d=0;d<kp;d+=4) {',text.index('void FastTileToRowMajor('))
        end=text.index('  OptSet(move_type,0xd2,16,16);',start)
        text=text[:start]+'''  if(tokens==16)HoistedKLoop<false>(a,b,channels,tokens,kp,commands);
  else HoistedKLoop<true>(a,b,channels,tokens,kp,commands);
'''+text[end:]
    elif name=='linear_bench.cc':
        text=r(text,'#include "optimized_core.h"','#include "optimized_core.h"\n#include "qualified_core.h"')
        start=text.index('__attribute__((noinline)) bool Prepack(')
        end=text.index('__attribute__((noinline)) bool OptPrepack(',start)
        text=text[:start]+'''// complete/reuse are the already-qualified direct-writeback VME, NOT the
// first scalar-packed VME. Their temporary counters do not enter candidate counts.
__attribute__((noinline)) bool Prepack(int k,int n) {
  return qualified::PrepareQualifiedWeights(lv_w,k,n,lv_reuse_weights);
}
__attribute__((noinline)) bool Complete(int m,int k,int n) {
  qualified::OptimizationCounts count{};
  return qualified::RunQualifiedComplete(lv_x,lv_w,m,k,n,lv_complete_weights,lv_workspace,
      &lv_complete_commands,count,lv_complete_out.data);
}
__attribute__((noinline)) bool Reuse(int m,int k,int n) {
  qualified::OptimizationCounts count{};
  return qualified::RunQualifiedPrepared(lv_x,m,k,n,lv_reuse_weights,lv_workspace,
      &lv_reuse_commands,count,lv_reuse_out.data);
}
'''+text[end:]
    elif name=='lv_spec.py':
        text=r(text,'resident_INT8_M_sweep_same_ELF_RVV_old_VME_vs_all_M_direct_writeback_not_model',
               'resident_INT8_RVV_qualified_direct_VME_vs_configure_once_K_loop_not_model')
        text=r(text,'short_all_M_RVV_pack_VME_init_strided_store_arithmetic_not_performance',
               'short_full_partial_hoisted_K_loop_padded_operands_not_performance')
        text=r(text,'return workspace_for(m,k,n,vectors(index),direct=False)',
               'return workspace_for(m,k,n,vectors(index),direct=True)')
        # Qualify ambiguous legacy JSON field names in every accepted result.
        text=r(text,'return dict(case_id=index,case=name,M=m,K=k,N=n,',
               "return dict(baseline_path='qualified_direct_writeback_VME',candidate_path='configure_once_K_loop',case_id=index,case=name,M=m,K=k,N=n,")
    elif name=='prepare.py':
        text=r(text,'"vme_tile.h","optimized_core.h"','"vme_tile.h","optimized_core.h","qualified_core.h","hoisted_loop.h"')
        text=r(text,'srcs=["linear_bench.cc","linear_core.h","optimized_core.h"]',
               'srcs=["linear_bench.cc","linear_core.h","optimized_core.h","qualified_core.h","hoisted_loop.h"]')
        text=r(text,'srcs=["core_test.cc","linear_core.h","optimized_core.h"]',
               'srcs=["core_test.cc","linear_core.h","optimized_core.h","hoisted_loop.h"]')
        text=r(text,'"lv_packet.py","lv_bench.py","optimized_core.h","vm_bench.py"',
               '"lv_packet.py","lv_bench.py","optimized_core.h","vm_bench.py","qualified_core.h","hoisted_loop.h"')
    elif name=='lv_audit.py':
        text=r(text,"'FastTileToRowMajor':{'vsse32','signed_A_unsigned_B_matrix','vector_to_tile_row',",
               "'HoistedKLoop':{'signed_A_unsigned_B_matrix','msetmtype','mset_dimension'},\n        'FastTileToRowMajor':{'vsse32','vector_to_tile_row',")
        text=r(text,"if component=='FastTileToRowMajor' and 'ordinary_vset_clears_mtype' in ops:",
               "if component in ('FastTileToRowMajor','HoistedKLoop') and 'ordinary_vset_clears_mtype' in ops:")
        text=r(text,'report[component]=dict(functions=functions,verified_operations=sorted(required))',
               "report[component]=dict(functions=functions,verified_operations=sorted(required))\n    report['HoistedKLoop']['loop_structure']=audit_hoisted_loops(elf)")
        text=r(text,'def instruction_audit(elf):',
               (HERE/'loop_audit.py').read_text()+'\n\ndef instruction_audit(elf):')
    elif name=='summarize.py':
        text=r(text,'Old VME complete | Old VME reuse','Qualified VME complete | Qualified VME reuse')
        text=r(text,"'Measured M points only: no interpolation or universal crossover threshold. Complete and reused-weight routing can differ.',",
               "'Baseline is the qualified direct-writeback VME, NOT the initial scalar-packed implementation.',\n        'Only configure-once K scheduling changed; same prepack, correction and layout. Full/partial paths need THIS probe.',\n        'Measured M points only: no interpolation or universal crossover threshold.',")
    elif name=='export.py':
        text=r(text,"'summarize.py','README.md'):", "'summarize.py','README.md','SOURCES.md'):")
    return text


def sources(repo=REPO):
    base,digest=pinned(repo);inherited,parents=base.sources(repo)
    files={};qualified=None
    for path,raw in inherited.items():
        if path.startswith(base.GENERATED+'/'):
            name=Path(path).name
            if name=='README.md':continue
            if name=='optimized_core.h':qualified=qualified_header(raw.decode()).encode()
            raw=transform(name,raw.decode(),base).encode();path=GENERATED+'/'+name
        files[path]=raw
    if qualified is None:raise ValueError('Missing pinned qualified baseline')
    files[GENERATED+'/qualified_core.h']=qualified
    for name in ('README.md','hoisted_loop.h','SOURCES.md'):
        files[GENERATED+'/'+name]=(HERE/name).read_bytes()
    return files,dict(sweep_revision=PIN,sweep_generator_sha256=digest,parent_files=parents)


def expected(repo=REPO):
    files,provenance=sources(repo)
    return files,dict(schema=1,kind='llm_vme_mature_kernel_trial_v1',simulation='NOT_RUN',
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        loop_audit_sha256=hashlib.sha256((HERE/'loop_audit.py').read_bytes()).hexdigest(),
        provenance=provenance,files={p:hashlib.sha256(b).hexdigest() for p,b in files.items()})


def verify(destination,repo=REPO):
    root=Path(destination).resolve(strict=True);_,record=expected(repo)
    if json.loads((root/'tool-manifest.json').read_text())!=record:raise ValueError('Changed tool provenance')
    actual={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and p!=root/'tool-manifest.json'}
    if any(p.is_symlink() for p in root.rglob('*')) or actual!=record['files']:
        raise ValueError('Missing/extra/changed generated tools')
    return root/GENERATED


def materialize(destination,repo=REPO):
    root=Path(destination).absolute();files,record=expected(repo)
    if root.exists():raise ValueError('Destination exists; nothing overwritten')
    root.mkdir()
    for name,raw in files.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as f:f.write(raw)
    with (root/'tool-manifest.json').open('x',encoding='utf-8') as f:json.dump(record,f,indent=2)
    return verify(root,repo)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--existing',action='store_true');a=p.parse_args()
    try:
        tools=verify(a.output) if a.existing else materialize(a.output)
        print('[LLM_VME_MATURE_TOOLS_VERIFIED] '+str(tools))
    except Exception as e:print('[LLM_VME_MATURE_STOP] '+str(e),file=sys.stderr);sys.exit(1)
