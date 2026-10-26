"""Freeze one Attention -> GEGLU FFN layer with interleaved prefill/decode phases."""
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
PIN='445c3d838e0ea857a90c21a49918ab10c776dc62'
GENERATED='verification/google_transformer_layer_v2'

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
    parent=types.ModuleType('_layer_parent')
    parent.__file__=str(REPO/'verification/google_attention/materialize.py')
    exec(compile(read('verification/google_attention/materialize.py'),parent.__file__,'exec'),parent.__dict__)
    parent.HERE=Frozen('verification/google_attention')
    inherited=parent.sources()
    files={p:b for p,b in inherited.items() if not p.startswith(parent.GENERATED+'/')}
    transform=lambda s:s.replace('google_attention_v1','google_transformer_layer_v2').replace(
        'attention_v1','transformer_layer_v2').replace('attention_','layer_').replace(
        'attention.cc','layer.cc').replace('attention::','layer::').replace('ATTENTION_','LAYER_')
    generated={Path(p).name.replace('attention_','layer_').replace('attention.cc','layer.cc'):transform(b.decode())
               for p,b in inherited.items() if p.startswith(parent.GENERATED+'/')}
    s=generated['lv_spec.py'];begin=s.index('CASES=');end=s.index('ATOL=',begin)
    s=s[:begin]+'''CASES=(('layer_decode','GEGLU',(1,4,8,3,0)),
       ('layer_tail','GEGLU',(3,6,13,7,0)),('layer_prefill','GEGLU',(4,8,16,11,0)))
PROBE_INDEX=3
PROBE_CASE=('layer_zero_safety','GEGLU',(1,2,3,0,0))
'''+s[end:]
    begin=s.index('SCOPE=');end=s.index('MARKER=',begin)
    s=s[:begin]+'''SCOPE='resident_FP32_single_head_Transformer_layer_Attention_GEGLU_FFN_interleaved_prefill_decode_not_model'
PROBE_SCOPE='Transformer_layer_zero_safety_not_performance'
'''+s[end:]
    begin=s.index('def eta(');end=s.index('def packed(',begin)
    s=s[:begin]+"def eta(index):return {3:'1-3 minutes',0:'2-6 minutes',1:'4-10 minutes',2:'7-18 minutes'}[index]\n\n"+s[end:]
    needle="    if row.get('stream_stage_counts')!=[[8,32,16,8,8,8]]*3:"
    s=change(s,needle,"    if row.get('ffn_phase_counts')!=[[4,4]]*3:raise ValueError('Wrong FFN prefill/decode counts')\n"+needle)
    s=s.replace('official_RMSNorm_Linear_residual_with_frozen_project_RoPE_Attention_scalar_libm_exp',
        'official_RMSNorm_Linear_residual_strict_MLAS_GELU_project_RoPE_Attention_scalar_libm_exp')
    s=s.replace("stream_stage_counts=row['stream_stage_counts'],", "ffn_phase_counts=row['ffn_phase_counts'],stream_stage_counts=row['stream_stage_counts'],")
    generated['lv_spec.py']=s
    core=read('verification/google_attention/attention.cc').decode()
    core=change(core,'int Stream(int path,int p,int h,int base,const float* x,const float* w,float* y) {',
        'int Stream(int path,int p,int h,int base,const float* x,const float* w,float* y,int f=0,const float* fw=nullptr,float* fy=nullptr) {')
    core=change(core,'  Finish(path,p,h,0,x,w,l,y);',
        '  Finish(path,p,h,0,x,w,l,y);\n  if(f)layer_ffn_phase(path,s,p,h,f,0,y+l.offset[Output],fw,fy);')
    core=change(core,'  Finish(path,1,h,p,x,w,l,y);',
        '  Finish(path,1,h,p,x,w,l,y);\n  if(f)layer_ffn_phase(path,s,1,h,f,p,y+l.offset[Output],fw,fy);')
    core+='''
extern "C" int attention_layer_stream(int path,int p,int h,int f,const float* x,const float* w,float* y,const float* fw,float* fy) {
  return Stream(path,p,h,0,x,w,y,f,fw,fy);
}
'''
    generated['attention_core.h']=core
    generated['attention_layout.h']=read('verification/google_attention/attention_layout.h').decode()
    generated['ffn_layout.h']=read('verification/google_ffn/ffn_layout.h').decode()
    generated['attention_reference.py']=read('verification/google_attention/fixture.py').decode()
    generated['ffn_reference.py']=read('verification/google_ffn/fixture.py').decode()
    generated['candidate.cc']=read('verification/google_gelu_rvv_mlas/candidate.cc').decode()
    generated['LICENSE-MLAS.txt']=read('verification/google_gelu_rvv_mlas/LICENSE-MLAS.txt').decode()
    b=generated['linear_bench.cc']
    b=change(b,'volatile unsigned lv_stream_stage_counts[18];',
        'volatile unsigned lv_stream_stage_counts[18];\nextern volatile unsigned lv_ffn_phase_counts[6];\nvolatile unsigned lv_stream_ffn_counts[6];')
    b=change(b,'  lv_cache_ok=1;', '  for(int i=0;i<6;++i)lv_ffn_phase_counts[i]=lv_stream_ffn_counts[i]=0;\n  lv_cache_ok=1;')
    b=change(b,'  Reset(lv_bulk_out);lv_bulk_calls=1;', '''  for(int i=0;i<6;++i){
    lv_stream_ffn_counts[i]=lv_ffn_phase_counts[i];
    if(lv_stream_ffn_counts[i]!=4)return 1;
  }
  Reset(lv_bulk_out);lv_bulk_calls=1;''')
    generated['linear_bench.cc']=b
    p=generated['prepare.py']
    p=change(p,"'layer_layout.h']", "'layer_layout.h','attention_layout.h','ffn_layout.h','attention_core.h']")
    p=change(p,"srcs=['layer.cc'", "srcs=['layer.cc','candidate.cc'")
    p=change(p,'srcs=["layer.cc"', 'srcs=["layer.cc","candidate.cc","attention_core.h","attention_layout.h","ffn_layout.h"')
    p=change(p,"'layer_fixture.py'", "'layer_fixture.py','attention_reference.py','ffn_reference.py'")
    # The prior replacement also touches the source-name inventory.
    p=change(p,"'layer.cc','layer_fixture.py','attention_reference.py','ffn_reference.py','layer_layout.h')",
        "'layer.cc','candidate.cc','LICENSE-MLAS.txt','attention_core.h','attention_layout.h','ffn_layout.h',"
        "'layer_fixture.py','attention_reference.py','ffn_reference.py','layer_layout.h')")
    p=change(p,'"layer_fixture.py"]','"layer_fixture.py","attention_reference.py","ffn_reference.py"]')
    generated['prepare.py']=p
    for name in ('export.py','lv_packet.py'):
        generated[name]=change(generated[name],"'layer_fixture.py'", "'layer_fixture.py','attention_reference.py','ffn_reference.py'")
    generated['export.py']=change(generated['export.py'],
        "        'Stateful single-head Attention glue: project code; strict math, KV and bulk controls required.\\n'",
        "        'Stateful Transformer layer glue; strict math, KV and bulk controls required.\\n'\n"
        "        'MLAS high-order GELU coefficients/algorithm: Microsoft MIT; source/LICENSE-MLAS.txt.\\n'")
    a=generated['lv_audit.py']
    a=change(a,'LINKER=', 'SIZES.update(lv_ffn_phase_counts=24,lv_stream_ffn_counts=24)\nLINKER=')
    a=change(a,"(('RmsNormF','rvv_rms_norm'),", "(('candidate_gelu_f32','candidate_gelu_f32'),('RmsNormF','rvv_rms_norm'),")
    a=change(a,"        result[entry]='real_ELF_vector_presence_not_execution'", '''        if entry=='candidate_gelu_f32' and not any(w&127==0x57 and (w>>26)&63==32 and (w>>12)&7==1 for w in instructions):
            raise ValueError('Missing actual candidate vector FP32 division')
        result[entry]='real_ELF_vector_presence_not_execution' ''')
    generated['lv_audit.py']=a
    c=generated['lv_bench.py']
    c=change(c,"    raw_bulk=", "    ffn_counts=list(map(int,await fixture.read('lv_stream_ffn_counts',dtype=np.dtype('<u4'),shape=(6,))))\n    raw_bulk=")
    c=change(c,'        stream_stage_counts=[counts[i:i+6]', '        ffn_phase_counts=[ffn_counts[i:i+2] for i in range(0,6,2)],stream_stage_counts=[counts[i:i+6]')
    generated['lv_bench.py']=c
    generated['summarize.py']=generated['summarize.py'].replace('Single-head prefill/decode Attention',
        'Single-layer Attention + GEGLU FFN prefill/decode').replace('All 13 tensors','All 19 tensors')
    generated['SOURCES.md']='''Pinned official Coral FP32 RMSNorm/Linear/residual, Apache-2.0, unchanged.
Frozen project RoPE/Attention and scalar/RVV controls; exp remains scalar libm.
MLAS-derived high-order GELU, Microsoft MIT, unchanged from qualified v2 candidate.
New glue inserts two FFN callbacks in a COPY of Attention source; originals unchanged.
No pretrained model, VME or RTL changes.
'''
    for name in ('layer.cc','layer_layout.h','README.md'):generated[name]=(HERE/name).read_text(encoding='utf-8')
    generated['layer_fixture.py']=(HERE/'fixture.py').read_text(encoding='utf-8')
    for name,text in generated.items():files[GENERATED+'/'+name]=text.encode('utf-8')
    return files

def expected():
    files=sources();digest=lambda b:hashlib.sha256(b).hexdigest()
    return files,dict(schema=1,kind='synthetic_Transformer_layer_v2',parent=PIN,simulation='NOT_RUN',
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
    try:print('[LAYER_TOOLS_VERIFIED] '+str(verify(a.output) if a.existing else materialize(a.output)))
    except Exception as error:print('[LAYER_STOP] '+str(error),file=sys.stderr);sys.exit(1)
