"""Freeze a prefill/decode Attention integration and untimed bulk control."""
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
PIN='4aa41e91f598959cb856e6bd58a1b7c79a4ea03f'
GENERATED='verification/google_attention_v1'
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
    parent=types.ModuleType('_attention_parent')
    parent.__file__=str(REPO/'verification/google_ffn/materialize.py')
    exec(compile(read('verification/google_ffn/materialize.py'),parent.__file__,'exec'),parent.__dict__)
    parent.HERE=Frozen('verification/google_ffn')
    inherited=parent.sources()
    files={p:b for p,b in inherited.items() if not p.startswith(parent.GENERATED+'/')}
    transform=lambda s:s.replace('google_ffn_v1','google_attention_v1').replace('ffn_v1','attention_v1').replace(
        'ffn_','attention_').replace('ffn.cc','attention.cc').replace('ffn::','attention::').replace('FFN','ATTENTION')
    generated={Path(p).name.replace('ffn_','attention_').replace('ffn.cc','attention.cc'):transform(b.decode())
               for p,b in inherited.items() if p.startswith(parent.GENERATED+'/')}
    s=generated['lv_spec.py'];begin=s.index('CASES=');end=s.index('ATOL=',begin)
    s=s[:begin]+'''CASES=(('attention_decode','GEGLU',(1,4,3,0,0)),
       ('attention_tail','GEGLU',(3,6,7,0,0)),('attention_prefill','GEGLU',(4,8,11,0,0)))
PROBE_INDEX=3
PROBE_CASE=('attention_zero_safety','GEGLU',(1,2,0,0,0))
'''+s[end:]
    begin=s.index('SCOPE=');end=s.index('MARKER=',begin)
    s=s[:begin]+'''SCOPE='resident_FP32_single_head_causal_Attention_prefill_then_decode_scalar_project_vs_official_RMS_Linear_residual_not_model'
PROBE_SCOPE='Attention_stream_and_bulk_zero_safety_not_performance'
'''+s[end:]
    begin=s.index('def eta(');end=s.index('def packed(',begin)
    s=s[:begin]+"def eta(index):return {3:'0.5-2 minutes',0:'1-4 minutes',1:'2-7 minutes',2:'4-10 minutes'}[index]\n\n"+s[end:]
    begin=s.index('    dense=re.findall(');end=s.index('\n\n\ndef accept(',begin)
    s=s[:begin]+s[end:]
    needle="    if row.get('attention_stage_guards_exact') is not True:raise ValueError('Broken ATTENTION intermediate guard')"
    s=change(s,needle,needle+'''
    required={'cache_prefix_bitwise_retained':True,'cache_local_guards':True,'bulk_math_pass':True,
              'bulk_stream_math_pass':True,'bulk_guards_exact':True,'bulk_calls':1,'bulk_mismatches':0,
              'bulk_checked':len(data['y'])}
    if any(type(row.get(k)) is not type(v) or row[k]!=v for k,v in required.items()):
        raise ValueError('Missing/failed cache or bulk control')
    if row.get('stream_stage_counts')!=[[8,32,16,8,8,8]]*3:
        raise ValueError('Wrong prefill/decode software call counts')''')
    s=s.replace('official_FP32_Linear_RMSNorm_residual_with_qualified_MLAS_GELU',
                'official_RMSNorm_Linear_residual_with_frozen_project_RoPE_Attention_scalar_libm_exp')
    s=s.replace("attention_stage_max_abs_error=errors)","attention_stage_max_abs_error=errors,\n"
                "        stream_stage_counts=row['stream_stage_counts'],cache_prefix_bitwise_retained=True,bulk_math_pass=True,bulk_stream_math_pass=True)")
    generated['lv_spec.py']=s
    b=generated['linear_bench.cc']
    for entry in ('scalar','project','candidate'):
        b=change(b,'void attention_'+entry+'(', 'int attention_'+entry+'(')
        b=change(b,'if(path==0)attention_'+entry+'(' if entry=='scalar' else
                 ('else if(path==1)attention_'+entry+'(' if entry=='project' else 'else attention_'+entry+'('),
                 'if(path==0)cache_ok=attention_'+entry+'(' if entry=='scalar' else
                 ('else if(path==1)cache_ok=attention_'+entry+'(' if entry=='project' else 'else cache_ok=attention_'+entry+'('))
    b=change(b,'volatile unsigned lv_case', '''int attention_bulk(int,int,int,const float*,const float*,float*);
extern volatile unsigned lv_stage_counts[18];
volatile unsigned lv_stream_stage_counts[18];
volatile unsigned lv_cache_ok,lv_bulk_checked,lv_bulk_mismatches,lv_bulk_calls,lv_bulk_guard_ok;
volatile unsigned lv_case''')
    b=change(b,'Guarded lv_scalar_out,lv_project_out,lv_official_out;',
             'Guarded lv_scalar_out,lv_project_out,lv_official_out,lv_bulk_out;')
    b=change(b,'  lv_scalar_calls=lv_project_calls=lv_official_calls=0;', '''  lv_scalar_calls=lv_project_calls=lv_official_calls=0;
  lv_cache_ok=1;lv_bulk_checked=lv_bulk_mismatches=lv_bulk_calls=lv_bulk_guard_ok=0;
  for(int i=0;i<18;++i)lv_stage_counts[i]=lv_stream_stage_counts[i]=0;''')
    b=change(b,'const unsigned before=Cycle();', 'const unsigned before=Cycle();int cache_ok=0;')
    b=change(b,'      const unsigned elapsed=Cycle()-before;',
             '      const unsigned elapsed=Cycle()-before;lv_cache_ok&=cache_ok==1;')
    needle='  lv_probe_signature=2166136261u;'
    b=change(b,needle,'''  const unsigned expected_counts[6]={8,32,16,8,8,8};
  for(int i=0;i<18;++i) {
    lv_stream_stage_counts[i]=lv_stage_counts[i];
    if(lv_stream_stage_counts[i]!=expected_counts[i%6])return 1;
  }
  Reset(lv_bulk_out);lv_bulk_calls=1;
  if(attention_bulk(t.a,t.b,t.c,lv_x,lv_w,lv_bulk_out.data)!=1)return 1;
  if(!Guard(lv_bulk_out,t.ny)||!StageGuards(lv_bulk_out,t))return 1;
  lv_bulk_guard_ok=1;
  for(unsigned j=0;j<t.ny;++j) {
    lv_bulk_mismatches+=!Close(lv_bulk_out.data[j],t.gold[j])||!Close(lv_bulk_out.data[j],lv_official_out.data[j]);
    ++lv_bulk_checked;
  }
  if(!lv_cache_ok||lv_bulk_mismatches||lv_bulk_checked!=t.ny)return 1;
'''+needle)
    generated['linear_bench.cc']=b
    p=generated['prepare.py']
    p=change(p,"srcs=['attention.cc','candidate.cc'","srcs=['attention.cc'")
    p=change(p,'srcs=["attention.cc","candidate.cc"','srcs=["attention.cc"')
    begin=p.index('cc_test(name="host_accuracy_test"');end=p.index('py_library(name="support"',begin)
    p=p[:begin]+p[end:]
    p=change(p,"'candidate.cc','host_accuracy.cc','LICENSE-MLAS.txt',",'')
    generated['prepare.py']=p
    generated['build_export.sh']=change(generated['build_export.sh'],
        '"$lv_pkg:host_reference_test" "$lv_pkg:host_accuracy_test"','"$lv_pkg:host_reference_test"')
    for name in ('candidate.cc','host_accuracy.cc','LICENSE-MLAS.txt'):
        del generated[name]
    e=generated['export.py']
    e=change(e,"        'Independent high-order RVV GELU port: original strict math gate required.\\n'\n"
               "        'MLAS coefficients/algorithm: Microsoft MIT; see source/LICENSE-MLAS.txt.\\n'",
               "        'Stateful single-head Attention glue: project code; strict math, KV and bulk controls required.\\n'")
    generated['export.py']=e
    generated['SOURCES.md']='''Official Coral sources fixed at 8e4df09b4ea7e065e02d14ce3ae033d40dfd973a; Apache-2.0.
Official RMSNorm, FP32 Linear and Residual sources remain byte identical.
RoPE/Attention project kernels are frozen from the parent; exp is scalar libm.
New code is prefill/decode wiring, cache copy and diagnostics. No GELU is executed here.
'''
    a=generated['lv_audit.py']
    a=change(a,'LINKER=','''SIZES.update(lv_stage_counts=72,lv_stream_stage_counts=72,lv_bulk_out=4128,
    lv_cache_ok=4,lv_bulk_checked=4,lv_bulk_mismatches=4,lv_bulk_calls=4,lv_bulk_guard_ok=4)
LINKER=''')
    a=change(a,"('candidate_gelu_f32','candidate_gelu_f32'),",'')
    a=change(a,"        if entry=='candidate_gelu_f32' and not any(w&127==0x57 and (w>>26)&63==32 and (w>>12)&7==1 for w in instructions):\n            raise ValueError('Missing actual candidate vector FP32 division')\n",'')
    a=change(a,"('attention_scalar','attention_project','attention_candidate'):",
             "('attention_scalar','attention_project','attention_candidate','attention_bulk'):")
    needle='    return result\n\n\n\n'
    a=change(a,needle,'''    vector=[s for s in table if s.name.startswith('_Z6Vector') and s['st_info']['type']=='STT_FUNC' and s['st_size']]
    if not vector:raise ValueError('Missing real project Vector entry')
    instructions=[]
    for sym in vector:
        sec=elf.get_section(sym['st_shndx']);at=sym['st_value']-sec['sh_addr']
        instructions+=words(sec.data()[at:at+sym['st_size']])
    if not any(w&127==0x57 and (w>>12)&7!=7 for w in instructions):raise ValueError('Missing project vector arithmetic')
    result['project_Vector']='real_ELF_vector_presence_not_execution'
    return result



''')
    generated['lv_audit.py']=a
    c=generated['lv_bench.py'];needle="    canary=(await fixture.read(stack,size_bytes=64))"
    c=change(c,needle,'''    extra={name:int(await fixture.read_word('lv_'+name)) for name in
           ('cache_ok','bulk_checked','bulk_mismatches','bulk_calls','bulk_guard_ok')}
    counts=list(map(int,await fixture.read('lv_stream_stage_counts',dtype=np.dtype('<u4'),shape=(18,))))
    raw_bulk=(await fixture.read('lv_bulk_out',size_bytes=4128)).tobytes()
    bulk=np.frombuffer(raw_bulk[16:16+4*n],dtype='<f4').astype(np.float64)
    bulk_good=bool(np.isfinite(bulk).all() and np.all(np.abs(bulk-gold)<=spec.ATOL+spec.RTOL*np.abs(gold)))
    bulk_stream=bool(np.isfinite(bulk).all() and np.all(np.abs(bulk-actual)<=spec.ATOL+spec.RTOL*np.abs(actual)))
    bulk_guards=raw_bulk[:16]==spec.GUARD*4 and raw_bulk[-16:]==spec.GUARD*4 and raw_bulk[16+4*n:-16]==spec.GUARD*(1024-n)
    for _,at,ns in layout[:-1]:bulk_guards=bulk_guards and raw_bulk[16+4*(at+ns):16+4*(at+ns+4)]==spec.GUARD*4
    by_name={label:(at,ns) for label,at,ns in layout};p,h,*_=data['shape']
    prefix=True
    for pre,final,source in (('prefill_k','final_k','k_rope'),('prefill_v','final_v','v')):
        a,b,src=by_name[pre][0],by_name[final][0],by_name[source][0]
        prefix=prefix and spec.packed(actual[a:a+p*h])==spec.packed(actual[b:b+p*h])
        prefix=prefix and spec.packed(actual[b+p*h:b+(p+1)*h])==spec.packed(actual[src+p*h:src+(p+1)*h])
    canary=(await fixture.read(stack,size_bytes=64))''')
    c=change(c,'attention_stage_guards_exact=stage_guards,**arrays)', '''attention_stage_guards_exact=stage_guards,
        cache_prefix_bitwise_retained=prefix and extra['cache_ok']==1,cache_local_guards=extra['cache_ok']==1,
        bulk_math_pass=bulk_good,bulk_stream_math_pass=bulk_stream,bulk_guards_exact=bulk_guards and extra['bulk_guard_ok']==1,
        bulk_calls=extra['bulk_calls'],bulk_checked=extra['bulk_checked'],bulk_mismatches=extra['bulk_mismatches'],
        stream_stage_counts=[counts[i:i+6] for i in range(0,18,6)],**arrays)''')
    generated['lv_bench.py']=c
    generated['summarize.py']=generated['summarize.py'].replace('Six-stage synthetic FP32 ATTENTION strict comparison',
        'Single-head prefill/decode Attention strict comparison').replace('Raw ATTENTION mcycle','Raw stream mcycle').replace(
        'Candidate must pass the original strict math gate; this is not the old low-accuracy official approximation.',
        'All 13 tensors, cache-prefix retention, software call counts and untimed RTL bulk control must pass.')
    for name in ('attention.cc','attention_layout.h','README.md'):
        generated[name]=(HERE/name).read_text(encoding='utf-8')
    generated['attention_fixture.py']=(HERE/'fixture.py').read_text(encoding='utf-8')
    for name,text in generated.items():files[GENERATED+'/'+name]=text.encode('utf-8')
    return files

def expected():
    files=sources();digest=lambda b:hashlib.sha256(b).hexdigest()
    return files,dict(schema=1,kind='synthetic_stream_Attention_v1',parent=PIN,simulation='NOT_RUN',
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
    try:print('[ATTENTION_TOOLS_VERIFIED] '+str(verify(a.output) if a.existing else materialize(a.output)))
    except Exception as error:print('[ATTENTION_STOP] '+str(error),file=sys.stderr);sys.exit(1)
