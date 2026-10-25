"""Freeze a six-stage synthetic FP32 FFN, retaining the qualified RTL model."""
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
PIN='198cf34dc460ea96fcb56e3a2edfa491884d57a3'
GENERATED='verification/google_ffn_v1'
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
    parent=types.ModuleType('_ffn_parent')
    parent.__file__=str(REPO/'verification/google_transformer_chain/materialize.py')
    exec(compile(read('verification/google_transformer_chain/materialize.py'),parent.__file__,'exec'),parent.__dict__)
    parent.HERE=Frozen('verification/google_transformer_chain')
    inherited=parent.sources()
    files={p:b for p,b in inherited.items() if not p.startswith(parent.GENERATED+'/')}
    transform=lambda s:s.replace('google_transformer_chain_v2','google_ffn_v1').replace(
        'transformer_chain_v2','ffn_v1').replace('transformer_chain_','ffn_').replace(
        'TRANSFORMER_CHAIN','FFN').replace('chain_','ffn_').replace('chain.cc','ffn.cc')
    generated={Path(p).name.replace('chain_','ffn_').replace('chain.cc','ffn.cc'):transform(b.decode())
               for p,b in inherited.items() if p.startswith(parent.GENERATED+'/')}
    s=generated['lv_spec.py']
    begin=s.index('CASES=');end=s.index('ATOL=',begin)
    s=s[:begin]+'''CASES=(('ffn_decode','GEGLU',(1,8,16,0,0)),
       ('ffn_tail','GEGLU',(3,7,13,0,0)),('ffn_prefill','GEGLU',(4,8,32,0,0)))
PROBE_INDEX=3
PROBE_CASE=('ffn_zero_safety','GEGLU',(1,1,1,0,0))
'''+s[end:]
    s=change(s,"SCOPE='resident_FP32_RMSNorm_GELUxUp_Residual_ffn_scalar_project_vs_qualified_RVV_not_Transformer_model'",
             "SCOPE='resident_synthetic_FP32_pre_norm_GEGLU_FFN_with_three_Linear_scalar_project_vs_qualified_RVV_not_model'")
    s=change(s,"PROBE_SCOPE='three_stage_ffn_zero_safety_probe_not_performance'",
             "PROBE_SCOPE='six_stage_FFN_zero_safety_probe_not_performance'")
    begin=s.index('def eta(');end=s.index('def packed(',begin)
    s=s[:begin]+"def eta(index):return {3:'0.5-2 minutes',0:'1-4 minutes',1:'2-6 minutes',2:'4-10 minutes'}[index]\n\n"+s[end:]
    begin=s.index('def fixture(');end=s.index('def signature(',begin)
    s=s[:begin]+'from ffn_fixture import fixture,layout as stage_layout\n\n\n'+s[end:]
    begin=s.index("    if row.get('ffn_stage_math_pass')");end=s.index('    if probe and',begin)
    s=s[:begin]+'''    names={name for name,_,_ in stage_layout(data['shape'])}
    stage_pass=row.get('ffn_stage_math_pass');errors=row.get('ffn_stage_max_abs_error')
    if not isinstance(stage_pass,dict) or set(stage_pass)!=names or any(v is not True for v in stage_pass.values()):
        raise ValueError('Missing/failed FFN stage')
    if not isinstance(errors,dict) or set(errors)!=names:raise ValueError('Missing FFN stage errors')
    for name,begin,n in stage_layout(data['shape']):
        limit=ATOL+RTOL*max(map(abs,data['y'][begin:begin+n]))
        if type(errors[name]) not in (int,float) or not math.isfinite(errors[name]) or not 0<=errors[name]<=limit:
            raise ValueError('Invalid FFN stage error')
    if row.get('ffn_stage_guards_exact') is not True:raise ValueError('Broken FFN intermediate guard')
'''+s[end:]
    s=s.replace('qualified_MLAS_GELU_with_official_RMSNorm_and_residual',
                'official_FP32_Linear_RMSNorm_residual_with_qualified_MLAS_GELU')
    generated['lv_spec.py']=s
    b=generated['linear_bench.cc'].replace('#include "kernels.h"','#include "kernels.h"\n#include "ffn_layout.h"')
    for entry in ('scalar','project','candidate'):
        b=change(b,'void ffn_'+entry+'(int,int,const float*,const float*,float*);',
                 'void ffn_'+entry+'(int,int,int,const float*,const float*,float*);')
        b=b.replace('ffn_'+entry+'(t.a,t.b,','ffn_'+entry+'(t.a,t.b,t.c,')
    begin=b.index('bool StageGuards(');end=b.index('int Run(',begin)
    b=b[:begin]+'''bool StageGuards(const Guarded& o,const Case& t) {
  const ffn::Layout l(t.a,t.b,t.c);
  if(l.total!=int(t.ny)||l.total>1024)return false;
  for(unsigned at:l.guard)for(unsigned j=0;j<4;++j) {
    unsigned u;std::memcpy(&u,o.data+at+j,4);if(u!=guard)return false;
  }
  return true;
}
'''+b[end:]
    b=b.replace('StageGuards(lv_scalar_out,t.a*t.b)','StageGuards(lv_scalar_out,t)').replace(
        'StageGuards(lv_project_out,t.a*t.b)','StageGuards(lv_project_out,t)').replace('StageGuards(lv_official_out,t.a*t.b)','StageGuards(lv_official_out,t)')
    generated['linear_bench.cc']=b
    p=generated['prepare.py']
    p=change(p,"headers=['kernels.h','rvv_common_vec.h']","headers=['kernels.h','rvv_common_vec.h','ffn_layout.h']")
    p=change(p,'"kernels.cc","kernels.h","fixtures.cc"','"kernels.cc","kernels.h","ffn_layout.h","fixtures.cc"')
    p=change(p,"'ffn.cc','ffn_fixture.py')","'ffn.cc','ffn_fixture.py','ffn_layout.h')")
    generated['prepare.py']=p
    a=generated['lv_audit.py']
    a=change(a,"('rvv_residual_add_f32','rvv_residual_add')):",
             "('rvv_residual_add_f32','rvv_residual_add'),('rvv_gemv_1d_f32','rvv_gemv_1d_f32'),('rvv_tiled_matmul_2d_f32','rvv_tiled_matmul_2d_f32')):")
    generated['lv_audit.py']=a
    c=generated['lv_bench.py']
    begin=c.index("    nstage=data['shape'][0]");end=c.index('    canary=',begin)
    c=c[:begin]+'''    layout=spec.stage_layout(data['shape']);stage_guards=True
    for label in ('scalar','project','official'):
        raw=(await fixture.read('lv_'+label+'_out',size_bytes=4128)).tobytes()
        for _,at,nstage in layout[:-1]:
            stage_guards=stage_guards and raw[16+4*(at+nstage):16+4*(at+nstage+4)]==spec.GUARD*4
    stage_pass={};stage_error={}
    for label,at,nstage in layout:
        delta=np.abs(actual[at:at+nstage]-gold[at:at+nstage])
        stage_pass[label]=bool(np.isfinite(actual[at:at+nstage]).all() and np.all(delta<=spec.ATOL+spec.RTOL*np.abs(gold[at:at+nstage])))
        stage_error[label]=float(np.max(delta)) if bool(np.isfinite(delta).all()) else None
'''+c[end:]
    generated['lv_bench.py']=c
    mirrors=generated['host_mirrors.cc']+'''
// Native mirrors of official matmul entry points. NOT RVV execution.
extern "C" void rvv_gemv_1d_f32(const float* a,const float* b,float* y,int k,int n) {
  for(int c=0;c<n;++c){float sum=0;for(int i=0;i<k;++i)sum=std::fma(a[i],b[i*n+c],sum);y[c]=sum;}
}
extern "C" void rvv_tiled_matmul_2d_f32(const float* a,const float* b,float* y,int m,int k,int n) {
  for(int r=0;r<m;++r)rvv_gemv_1d_f32(a+r*k,b,y+r*n,k,n);
}
'''
    generated['host_mirrors.cc']=mirrors
    v=generated['vm_bench.py']
    for old,new in (('ffn_decode32','ffn_decode'),('ffn_tail37','ffn_tail'),('ffn_prefill4x64','ffn_prefill')):
        v=v.replace('candidate_'+old+'_test','candidate_'+new+'_test')
    generated['vm_bench.py']=v
    generated['summarize.py']=generated['summarize.py'].replace('Three-stage FP32 chain strict comparison','Six-stage synthetic FP32 FFN strict comparison').replace(
        'Raw chain mcycle','Raw FFN mcycle').replace('composed candidate','FFN candidate')
    for name,local in (('ffn.cc','ffn.cc'),('ffn_layout.h','ffn_layout.h'),('ffn_fixture.py','fixture.py'),('README.md','README.md')):
        generated[name]=(HERE/local).read_text(encoding='utf-8')
    for name,text in generated.items():files[GENERATED+'/'+name]=text.encode('utf-8')
    return files

def expected():
    files=sources();digest=lambda b:hashlib.sha256(b).hexdigest()
    return files,dict(schema=1,kind='synthetic_FP32_FFN_v1',parent=PIN,simulation='NOT_RUN',
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
    try:print('[FFN_TOOLS_VERIFIED] '+str(verify(a.output) if a.existing else materialize(a.output)))
    except Exception as error:print('[FFN_STOP] '+str(error),file=sys.stderr);sys.exit(1)
