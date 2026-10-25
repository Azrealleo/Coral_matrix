"""Freeze a new synthetic three-stage chain without changing accepted packages."""
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
PIN='6193f5a4ce223d752cff846f62985ac78ee68b54'
GENERATED='verification/google_transformer_chain_v2'

def read(path):return subprocess.check_output(['git','-C',str(REPO),'show',PIN+':'+path])
class Frozen:
    def __init__(self,path):self.path=path
    def __truediv__(self,name):return Frozen(self.path+'/'+name)
    def read_bytes(self):return read(self.path)
    def read_text(self,**kwargs):return self.read_bytes().decode('utf-8')

def change(text,old,new):
    if text.count(old)!=1:raise ValueError('Frozen interface changed: '+old[:100])
    return text.replace(old,new)

def sources():
    parent=types.ModuleType('_chain_parent')
    parent.__file__=str(REPO/'verification/google_gelu_rvv_mlas/materialize.py')
    exec(compile(read('verification/google_gelu_rvv_mlas/materialize.py'),parent.__file__,'exec'),parent.__dict__)
    parent.HERE=Frozen('verification/google_gelu_rvv_mlas')
    inherited=parent.sources()
    files={p:b for p,b in inherited.items() if not p.startswith(parent.GENERATED+'/')}
    transform=lambda s:s.replace('google_gelu_rvv_mlas_v2','google_transformer_chain_v2').replace(
        'gelu_rvv_mlas_v2','transformer_chain_v2').replace('gelu_rvv_mlas_','transformer_chain_').replace(
        'GELU_RVV_MLAS','TRANSFORMER_CHAIN').replace('GELU_MLAS_HOST','TRANSFORMER_CHAIN_HOST')
    generated={Path(p).name:transform(b.decode()) for p,b in inherited.items() if p.startswith(parent.GENERATED+'/')}
    s=generated['lv_spec.py']
    start=s.index('CASES=');end=s.index('ATOL=',start)
    s=s[:start]+'''CASES=(('chain_decode32','GEGLU',(1,32,0,0,0)),
       ('chain_tail37','GEGLU',(1,37,0,0,0)),('chain_prefill4x64','GEGLU',(4,64,0,0,0)))
PROBE_INDEX=3
PROBE_CASE=('chain_zero_safety','GEGLU',(1,1,0,0,0))
'''+s[end:]
    s=s.replace('resident_FP32_scalar_project_RVV_vs_MLAS_based_RVV_GELU_strict_not_model',
                'resident_FP32_RMSNorm_GELUxUp_Residual_chain_scalar_project_vs_qualified_RVV_not_Transformer_model')
    s=s.replace('MLAS_based_RVV_GELU_zero_safety_probe_not_performance','three_stage_chain_zero_safety_probe_not_performance')
    begin=s.index('def eta(');end=s.index('def packed(',begin)
    s=s[:begin]+"def eta(index):return {3:'0.5-2 minutes',0:'1-4 minutes',1:'1-4 minutes',2:'2-6 minutes'}[index]\n\n"+s[end:]
    begin=s.index('def fixture(');end=s.index('def signature(',begin)
    s=s[:begin]+'''def fixture(index):
    path=Path(__file__).with_name('chain_fixture.py')
    ms=importlib.util.spec_from_file_location('_chain_fixture',path)
    module=importlib.util.module_from_spec(ms);ms.loader.exec_module(module)
    return module.fixture(index)


'''+s[end:]
    needle="    if not q:raise ValueError('Non-approximate official kernel fails strict math reference')"
    s=change(s,needle,needle+'''
    if row.get('chain_stage_math_pass')!={'norm':True,'activation':True,'output':True}:
        raise ValueError('Missing/failed intermediate chain stage')
    errors=row.get('chain_stage_max_abs_error')
    if not isinstance(errors,dict) or set(errors)!={'norm','activation','output'}:
        raise ValueError('Missing per-stage errors')
    n=data['shape'][0]*data['shape'][1]
    for name,begin in (('norm',0),('activation',n+4),('output',2*n+8)):
        limit=ATOL+RTOL*max(map(abs,data['y'][begin:begin+n]))
        if type(errors[name]) not in (int,float) or not math.isfinite(errors[name]) or not 0<=errors[name]<=limit:
            raise ValueError('Invalid chain stage error')
    if row.get('chain_stage_guards_exact') is not True:raise ValueError('Broken intermediate guard')''')
    s=s.replace("approximation='MLAS_v1_20_1_high_order_rational_tanh' if data['kind']=='GEGLU' else 'none_intended')",
                "approximation='qualified_MLAS_GELU_with_official_RMSNorm_and_residual',\n"
                "        chain_stage_math_pass=row['chain_stage_math_pass'],chain_stage_max_abs_error=errors)")
    generated['lv_spec.py']=s
    b=generated['linear_bench.cc']
    begin=b.index('void RmsNormF(');end=b.index('volatile unsigned lv_case',begin)
    b=b[:begin]+'''void chain_scalar(int,int,const float*,const float*,float*);
void chain_project(int,int,const float*,const float*,float*);
void chain_candidate(int,int,const float*,const float*,float*);
'''+b[end:]
    begin=b.index('__attribute__((noinline)) void Official');end=b.index('int Run(',begin)
    b=b[:begin]+'''bool StageGuards(const Guarded& o,unsigned n) {
  for(unsigned at:{n,2*n+4})for(unsigned j=0;j<4;++j) {
    unsigned u;std::memcpy(&u,o.data+at+j,4);if(u!=guard)return false;
  }
  return true;
}
'''+b[end:]
    b=b.replace('#include <cstring>','#include <cstring>\n#include <initializer_list>')
    b=change(b,'if(path==0)Scalar(t,lv_x,lv_w,nullptr,lv_scalar_out.data);',
             'if(path==0)chain_scalar(t.a,t.b,lv_x,lv_w,lv_scalar_out.data);')
    b=change(b,'else if(path==1)Vector(t,lv_x,lv_w,nullptr,lv_project_out.data);',
             'else if(path==1)chain_project(t.a,t.b,lv_x,lv_w,lv_project_out.data);')
    b=change(b,'else Official(t,lv_official_out.data);',
             'else chain_candidate(t.a,t.b,lv_x,lv_w,lv_official_out.data);')
    b=change(b,'    if(!Guard(lv_scalar_out,t.ny)',
             '    if(!StageGuards(lv_scalar_out,t.a*t.b)||!StageGuards(lv_project_out,t.a*t.b)||!StageGuards(lv_official_out,t.a*t.b))return 1;\n    if(!Guard(lv_scalar_out,t.ny)')
    generated['linear_bench.cc']=b
    p=generated['prepare.py']
    p=change(p,"srcs=['candidate.cc'","srcs=['chain.cc','candidate.cc'")
    p=change(p,'srcs=["candidate.cc","linear_bench.cc"','srcs=["chain.cc","candidate.cc","linear_bench.cc"')
    p=change(p,'"baseline_spec.py","tx_reference.py"]','"baseline_spec.py","tx_reference.py","chain_fixture.py"]')
    p=change(p,"'candidate.cc','host_accuracy.cc','LICENSE-MLAS.txt')",
             "'candidate.cc','host_accuracy.cc','LICENSE-MLAS.txt','chain.cc','chain_fixture.py')")
    generated['prepare.py']=p
    a=generated['lv_audit.py']
    a=change(a,"for entry,fragment in (('candidate_gelu_f32','candidate_gelu_f32'),):",
             "for entry,fragment in (('candidate_gelu_f32','candidate_gelu_f32'),('RmsNormF','rvv_rms_norm'),('rvv_residual_add_f32','rvv_residual_add')):")
    a=change(a,"        result[entry]='real_ELF_vector_presence_not_execution'\n    return result",
             '''        result[entry]='real_ELF_vector_presence_not_execution'
    for entry in ('chain_scalar','chain_project','chain_candidate'):
        if not any(s.name==entry and s['st_size'] for s in table):raise ValueError('Missing chain entry '+entry)
    return result
''')
    generated['lv_audit.py']=a
    c=generated['lv_bench.py']
    c=change(c,'    canary=(await fixture.read(stack,size_bytes=64))', '''    nstage=data['shape'][0]*data['shape'][1]
    stage_guards=True
    for label in ('scalar','project','official'):
        raw=(await fixture.read('lv_'+label+'_out',size_bytes=4128)).tobytes()
        for at in (nstage,2*nstage+4):stage_guards=stage_guards and raw[16+4*at:16+4*(at+4)]==spec.GUARD*4
    stage_pass={};stage_error={}
    for label,at in (('norm',0),('activation',nstage+4),('output',2*nstage+8)):
        delta=np.abs(actual[at:at+nstage]-gold[at:at+nstage])
        stage_pass[label]=bool(np.isfinite(actual[at:at+nstage]).all() and np.all(delta<=spec.ATOL+spec.RTOL*np.abs(gold[at:at+nstage])))
        stage_error[label]=float(np.max(delta)) if bool(np.isfinite(delta).all()) else None
    canary=(await fixture.read(stack,size_bytes=64))''')
    c=change(c,'execution_wall_seconds=elapsed,probe_signature=values[\'probe_signature\'],**arrays)',
             "execution_wall_seconds=elapsed,probe_signature=values['probe_signature'],\n"
             '        chain_stage_math_pass=stage_pass,chain_stage_max_abs_error=stage_error,chain_stage_guards_exact=stage_guards,**arrays)')
    generated['lv_bench.py']=c
    for name in ('export.py','lv_packet.py'):
        generated[name]=change(generated[name],"'lv_packet.py','tx_reference.py'", "'lv_packet.py','tx_reference.py','chain_fixture.py'") if name=='lv_packet.py' else change(
            generated[name],"'lv_packet.py','tx_reference.py','server.py'","'lv_packet.py','tx_reference.py','chain_fixture.py','server.py'")
    v=generated['vm_bench.py']
    for old,new in (('gelu32','chain_decode32'),('gelu_tail37','chain_tail37'),('gelu256','chain_prefill4x64')):
        v=v.replace('candidate_'+old+'_test','candidate_'+new+'_test')
    generated['vm_bench.py']=v
    s=generated['summarize.py'].replace('Independent MLAS-based RVV GELU strict comparison','Three-stage FP32 chain strict comparison')
    s=s.replace('Project/official','Project/candidate').replace('Ratios >1 favor official RVV.','Ratios >1 favor the composed candidate.')
    s=s.replace('Raw kernel mcycle','Raw chain mcycle (calls and intermediate stores included)')
    generated['summarize.py']=s
    generated['README.md']=(HERE/'README.md').read_text(encoding='utf-8')
    generated['chain.cc']=(HERE/'chain.cc').read_text(encoding='utf-8')
    generated['chain_fixture.py']=(HERE/'fixture.py').read_text(encoding='utf-8')
    for name,text in generated.items():files[GENERATED+'/'+name]=text.encode('utf-8')
    return files

def expected():
    files=sources();digest=lambda b:hashlib.sha256(b).hexdigest()
    return files,dict(schema=1,kind='transformer_three_stage_chain_v2',parent=PIN,simulation='NOT_RUN',
                      generator_sha256=digest(Path(__file__).read_bytes()),files={p:digest(b) for p,b in files.items()})

def verify(destination):
    root=Path(destination).resolve(strict=True);_,record=expected()
    if json.loads((root/'tool-manifest.json').read_text())!=record:raise ValueError('Tool identity differs')
    actual={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and p.name!='tool-manifest.json'}
    if actual!=record['files'] or any(p.is_symlink() for p in root.rglob('*')):raise ValueError('Changed/missing/extra tool file')
    return root/GENERATED

def materialize(destination):
    root=Path(destination).absolute();files,record=expected();root.mkdir()
    for name,data in files.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(data)
    with (root/'tool-manifest.json').open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    return verify(root)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--existing',action='store_true');a=p.parse_args()
    try:print('[TRANSFORMER_CHAIN_TOOLS_VERIFIED] '+str(verify(a.output) if a.existing else materialize(a.output)))
    except Exception as error:print('[TRANSFORMER_CHAIN_STOP] '+str(error),file=sys.stderr);sys.exit(1)
