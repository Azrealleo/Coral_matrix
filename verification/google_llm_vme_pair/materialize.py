"""Independent mt0/mt4 input-sharing trial, derived from frozen mature tools."""
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
PIN='6ee7fd65f44288a8a6271493acfd98397ff2c67e'
GENERATED='verification/google_llm_vme_pair_v1'
PROBES=((1,3,1),(16,4,16),(1,17,33),(16,17,33),(16,32,32),
        (1,64,64),(7,7,15),(15,63,47),(2,7,32),(4,17,48),
        (8,32,64),(12,63,63),(16,64,64))


class FrozenPath:
    """Only the parent's sibling resources are read from Git, not live files."""
    def __init__(self,repo,path):self.repo,self.path=repo,path
    def __truediv__(self,name):return FrozenPath(self.repo,self.path+'/'+name)
    def read_bytes(self):return subprocess.check_output(['git','-C',str(self.repo),'show',PIN+':'+self.path])
    def read_text(self):return self.read_bytes().decode('utf-8')


def pinned(repo=REPO):
    path='verification/google_llm_vme_mature/materialize.py'
    raw=subprocess.check_output(['git','-C',str(repo),'show',PIN+':'+path])
    module=types.ModuleType('_pair_frozen_mature');module.__file__=str(repo/path)
    exec(compile(raw,module.__file__,'exec'),module.__dict__)
    module.HERE=FrozenPath(repo,'verification/google_llm_vme_mature')
    return module,hashlib.sha256(raw).hexdigest()


def transform(name,text,r):
    text=text.replace('llm_vme_mature_v1','llm_vme_pair_v1').replace('llm_vme_mature_','llm_vme_pair_')
    text=text.replace('LLM_VME_MATURE','LLM_VME_PAIR')
    if name=='optimized_core.h':
        text=r(text,'struct OptimizationCounts {uint32_t fast_tiles=0,fallback_tiles=0;};',
               'struct OptimizationCounts {uint32_t fast_tiles=0,fallback_tiles=0,pair_groups=0,single_groups=0;};')
        start=text.index('inline __attribute__((noinline)) bool RunOptimizedPrepared(')
        end=text.index('inline __attribute__((noinline)) bool RunOptimizedComplete(',start)
        text=text[:start]+'''} // namespace llm_vme
#include "pair_tile.h"
namespace llm_vme {
inline __attribute__((noinline)) bool RunOptimizedPrepared(const int8_t* x,int m,int k,int n,
    const PackedWeights& weights,Workspace& work,uint32_t* commands,OptimizationCounts& counts,int32_t* y) {
  return RunPairPrepared(x,m,k,n,weights,work,commands,counts,y);
}
'''+text[end:]
    elif name=='linear_bench.cc':
        start=text.index('constexpr int kProbeShapes[][3]=');end=text.index(';',start)
        text=text[:start]+'constexpr int kProbeShapes[][3]={'+','.join('{'+','.join(map(str,s))+'}' for s in PROBES)+'}'+text[end:]
        text=r(text,'for(unsigned q=0;q<13;++q) {',
               '''uint32_t expected_tiles=0,expected_pairs=0,expected_singles=0,expected_probe_commands=0;
  for(unsigned q=0;q<13;++q) {''')
        text=r(text,'lv_probe_step=4;',
               '''expected_tiles+=static_cast<uint32_t>((n+15)/16);
    expected_pairs+=static_cast<uint32_t>(n/32);
    expected_singles+=static_cast<uint32_t>((n+15)/16-2*(n/32));
    expected_probe_commands+=static_cast<uint32_t>(((n+15)/16)*((k+3)/4));
    if(lv_probe_tiles.fast_tiles!=expected_tiles||lv_probe_tiles.fallback_tiles||
       lv_probe_tiles.pair_groups!=expected_pairs||lv_probe_tiles.single_groups!=expected_singles||
       lv_probe_commands!=expected_probe_commands) {lv_status=45;lv_probe_fail_case=q;return 1;}
    lv_probe_step=4;''')
        text=r(text,'lv_opt_complete_tiles.fallback_tiles||lv_opt_reuse_tiles.fallback_tiles)',
               '''lv_opt_complete_tiles.fallback_tiles||lv_opt_reuse_tiles.fallback_tiles||
     lv_opt_complete_tiles.pair_groups!=4u*(n/32)||lv_opt_reuse_tiles.pair_groups!=4u*(n/32)||
     lv_opt_complete_tiles.single_groups!=4u*(((n+15)/16)-2*(n/32))||
     lv_opt_reuse_tiles.single_groups!=4u*(((n+15)/16)-2*(n/32)))''')
    elif name=='core_test.cc':
        text=r(text,'opt_counts.fallback_tiles!=0u)',
               'opt_counts.fallback_tiles!=0u||opt_counts.pair_groups!=2u*(n/32)||opt_counts.single_groups!=2u*(tiles-2u*(n/32)))')
    elif name=='lv_spec.py':
        start=text.index('PROBE_SHAPES=');end=text.index('\nBASE_RTL_PACKAGE=',start)
        text=text[:start]+'PROBE_SHAPES='+repr(PROBES)+text[end:]
        text=r(text,'resident_INT8_RVV_qualified_direct_VME_vs_configure_once_K_loop_not_model',
               'resident_INT8_RVV_configure_once_single_VME_vs_paired_mt0_mt4_shared_input_not_model')
        text=r(text,'short_full_partial_hoisted_K_loop_padded_operands_not_performance',
               'short_mt0_mt4_isolation_shared_input_and_single_tail_not_performance')
        text=r(text,"baseline_path='qualified_direct_writeback_VME',candidate_path='configure_once_K_loop'",
               "baseline_path='configure_once_single_tile_VME',candidate_path='paired_mt0_mt4_shared_input'")
        text=r(text,'probe_fast_tiles=fast,probe_fallback_tiles=fallback,',
               '''probe_fast_tiles=fast,probe_fallback_tiles=fallback,
        probe_pair_groups=sum(n//32 for m,k,n in PROBE_SHAPES),
        probe_single_groups=sum((n+15)//16-2*(n//32) for m,k,n in PROBE_SHAPES),''')
        text=r(text,'opt_complete_fallback_tiles=0,opt_reuse_fallback_tiles=0,',
               '''opt_complete_fallback_tiles=0,opt_reuse_fallback_tiles=0,
        opt_complete_pair_groups=4*(n//32),opt_reuse_pair_groups=4*(n//32),
        opt_complete_single_groups=4*((n+15)//16-2*(n//32)),
        opt_reuse_single_groups=4*((n+15)//16-2*(n//32)),''')
        text=r(text,'requested_cycles=5000000','requested_cycles=10000000')
        text=r(text,'total<=5000001','total<=10000001')
        text=r(text,"6:'4-12 minutes'", "6:'5-20 minutes'")
    elif name=='lv_bench.py':
        text=r(text,'budget=5000000 if probe else 10000000','budget=10000000')
        text=r(text,"fast,fallback=map(int,await fixture.read('lv_'+label+'_tiles',dtype=np.dtype('<u4'),shape=(2,)))",
               "fast,fallback,pairs,singles=map(int,await fixture.read('lv_'+label+'_tiles',dtype=np.dtype('<u4'),shape=(4,)))")
        text=r(text,"tiles[label+'_fallback_tiles']=fallback",
               "tiles[label+'_fallback_tiles']=fallback\n        tiles[label+'_pair_groups']=pairs;tiles[label+'_single_groups']=singles")
    elif name=='lv_audit.py':
        for field in ('lv_opt_complete_tiles','lv_opt_reuse_tiles','lv_probe_tiles'):
            text=r(text,field+'=8',field+'=16')
        text=r(text,"'HoistedKLoop':{'signed_A_unsigned_B_matrix','msetmtype','mset_dimension'},",
               "'PairKLoop':{'signed_A_unsigned_B_matrix','msetmtype','mset_dimension'},\n        'PairTileToRowMajor':{'vsse32','vector_to_tile_row','tile_row_to_vector','msetmtype','mset_dimension'},\n        'HoistedKLoop':{'signed_A_unsigned_B_matrix','msetmtype','mset_dimension'},")
        text=r(text,"component in ('FastTileToRowMajor','HoistedKLoop')",
               "component in ('FastTileToRowMajor','HoistedKLoop','PairKLoop','PairTileToRowMajor')")
        text=r(text,"report['HoistedKLoop']['loop_structure']=audit_hoisted_loops(elf)",
               "report['HoistedKLoop']['loop_structure']=audit_hoisted_loops(elf)\n    report['PairKLoop']['loop_structure']=audit_pair_loops(elf)\n    report['PairTileToRowMajor']['tile_selector']=audit_pair_tile_selector(elf)")
        text=r(text,'def instruction_audit(elf):',(HERE/'pair_audit.py').read_text()+'\n\ndef instruction_audit(elf):')
    elif name=='prepare.py':
        text=r(text,'"qualified_core.h","hoisted_loop.h"','"qualified_core.h","hoisted_loop.h","pair_tile.h","pair_loop.h"',3)
        text=r(text,'"optimized_core.h","hoisted_loop.h"]',
               '"optimized_core.h","hoisted_loop.h","pair_tile.h","pair_loop.h"]')
    elif name=='vm.py':
        text=r(text,"sequence=(spec.PROBE_INDEX,3) if a.plan=='quick'", "sequence=(spec.PROBE_INDEX,5) if a.plan=='quick'")
    elif name=='run_server.sh':
        text=r(text,'opt_cases=(3);','opt_cases=(5);')
    elif name=='summarize.py':
        text=r(text,'Qualified VME complete | Qualified VME reuse','Configure-once VME complete | Configure-once VME reuse')
        text=r(text,'Baseline is the qualified direct-writeback VME, NOT the initial scalar-packed implementation.',
               'Baseline is the qualified configure-once single-tile VME, NOT the original slow implementation.')
        text=r(text,'Only configure-once K scheduling changed; same prepack, correction and layout. Full/partial paths need THIS probe.',
               'Candidate shares one B load between mt0/mt4; same packing/correction/output. Pair/single counters must match.')
    return text


def sources(repo=REPO):
    parent,digest=pinned(repo);base,_=parent.pinned(repo);inherited,provenance=parent.sources(repo)
    files={};baseline=None
    for path,raw in inherited.items():
        if path.startswith(parent.GENERATED+'/'):
            name=Path(path).name
            if name in ('README.md','SOURCES.md','qualified_core.h'):continue
            if name=='optimized_core.h':baseline=parent.qualified_header(raw.decode()).encode()
            raw=transform(name,raw.decode(),base.replace).encode();path=GENERATED+'/'+name
        files[path]=raw
    if baseline is None:raise ValueError('Missing qualified configure-once baseline')
    files[GENERATED+'/qualified_core.h']=baseline
    for name in ('pair_loop.h','pair_tile.h','README.md','SOURCES.md'):
        files[GENERATED+'/'+name]=(HERE/name).read_bytes()
    return files,dict(parent_revision=PIN,parent_generator_sha256=digest,parent_provenance=provenance)


def expected(repo=REPO):
    files,provenance=sources(repo)
    return files,dict(schema=1,kind='llm_vme_paired_accumulators_v1',simulation='NOT_RUN',
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        pair_audit_sha256=hashlib.sha256((HERE/'pair_audit.py').read_bytes()).hexdigest(),
        provenance=provenance,probe_shapes=[list(s) for s in PROBES],
        files={p:hashlib.sha256(b).hexdigest() for p,b in files.items()})


def verify(destination,repo=REPO):
    root=Path(destination).resolve(strict=True);_,record=expected(repo)
    if json.loads((root/'tool-manifest.json').read_text())!=record:raise ValueError('Changed pair provenance')
    actual={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and p!=root/'tool-manifest.json'}
    if any(p.is_symlink() for p in root.rglob('*')) or actual!=record['files']:
        raise ValueError('Missing/extra/changed pair tools')
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
    try:print('[LLM_VME_PAIR_TOOLS_VERIFIED] '+str(verify(a.output) if a.existing else materialize(a.output)))
    except Exception as e:print('[LLM_VME_PAIR_STOP] '+str(e),file=sys.stderr);sys.exit(1)
