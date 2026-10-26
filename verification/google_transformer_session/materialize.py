"""Freeze caller-owned KV state and multiple independent decode function calls."""
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
# The parent is the accepted layer commit, not a mutable checkout.
PIN='6b03b0a8705fc02f96016d014f5257896896fb9e'
GENERATED='verification/google_transformer_session_v2'

def read(path):return subprocess.check_output(['git','-C',str(REPO),'show',PIN+':'+path])
class Frozen:
    def __init__(self,path):self.path=path
    def __truediv__(self,name):return Frozen(self.path+'/'+name)
    def read_bytes(self):return read(self.path)
    def read_text(self,**kwargs):return self.read_bytes().decode('utf-8')

def change(text,old,new):
    if text.count(old)!=1:raise ValueError('Frozen interface changed: '+old[:110])
    return text.replace(old,new)

def sources():
    parent=types.ModuleType('_session_parent')
    parent.__file__=str(REPO/'verification/google_transformer_layer/materialize.py')
    exec(compile(read('verification/google_transformer_layer/materialize.py'),parent.__file__,'exec'),parent.__dict__)
    parent.HERE=Frozen('verification/google_transformer_layer')
    inherited=parent.sources()
    files={p:b for p,b in inherited.items() if not p.startswith(parent.GENERATED+'/')}
    transform=lambda s:s.replace('google_transformer_layer_v2','google_transformer_session_v2').replace(
        'transformer_layer_v2','transformer_session_v2').replace('layer_','session_').replace(
        'layer.cc','session.cc').replace('layer::','session::').replace('LAYER_','SESSION_')
    generated={Path(p).name.replace('layer_','session_').replace('layer.cc','session.cc'):transform(b.decode())
               for p,b in inherited.items() if p.startswith(parent.GENERATED+'/')}
    old_layer=inherited[parent.GENERATED+'/layer.cc'].decode()
    generated['ffn_core.h']=old_layer[:old_layer.index('// Frozen Attention')].replace('#include "layer_layout.h"','#include "ffn_layout.h"')
    original=read('verification/google_attention/attention.cc').decode()
    ops=original[:original.index('void Init(Cache&')]
    # API calls receive just the current rows, whereas output/RoPE use a global row offset.
    ops=ops.replace('x+at','x')
    ops+='}\nextern "C" {\n'+original[original.index('__attribute__((noinline)) int attention_bulk'):]
    generated['attention_ops.h']=ops
    del generated['attention_core.h']
    s=generated['lv_spec.py'];begin=s.index('CASES=');end=s.index('ATOL=',begin)
    s=s[:begin]+'''CASES=(('session_decode2','GEGLU',(1,4,8,2,3)),
       ('session_tail3','GEGLU',(2,6,13,3,7)),('session_prefill3','GEGLU',(3,8,8,3,11)))
PROBE_INDEX=3
PROBE_CASE=('session_zero_safety','GEGLU',(1,2,3,2,0))
'''+s[end:]
    begin=s.index('SCOPE=');end=s.index('MARKER=',begin)
    s=s[:begin]+'''SCOPE='resident_FP32_single_layer_caller_owned_KV_prefill_multiple_decode_calls_not_model'
PROBE_SCOPE='caller_owned_KV_session_zero_safety_not_performance'
'''+s[end:]
    begin=s.index('def eta(');end=s.index('def packed(',begin)
    s=s[:begin]+"def eta(index):return {3:'2-5 minutes',0:'3-8 minutes',1:'5-12 minutes',2:'7-16 minutes'}[index]\n\n"+s[end:]
    s=change(s,"    if row.get('ffn_phase_counts')!=[[4,4]]*3:raise ValueError('Wrong FFN prefill/decode counts')",
        "    if row.get('ffn_phase_counts')!=[[4,4*data['shape'][3]]]*3:raise ValueError('Wrong FFN multi-call counts')")
    s=change(s,"    if row.get('stream_stage_counts')!=[[8,32,16,8,8,8]]*3:",
        "    count=4*(1+data['shape'][3])\n    if row.get('stream_stage_counts')!=[[count,4*count,2*count,count,count,count]]*3:")
    needle="    if probe and row.get('probe_signature')"
    at=s.index(needle)
    s=s[:at]+'''    contract=dict(contract_mask=63,contract_calls=1,contract_guards_exact=True,
        isolation_math_pass=True,alternate_math_pass=True,alternate_checked=len(data['y']),alternate_mismatches=0,
        alternate_reference_sha256=data['alternate_sha256'],unused_phase_slots_zero=True)
    if any(type(row.get(k)) is not type(v) or row[k]!=v for k,v in contract.items()):
        raise ValueError('Missing/failed independent-state lifecycle contract')
    p,_,_,t,_=data['shape'];phases=row.get('phase_cycles');lengths=row.get('session_lengths')
    names=('scalar','project','candidate')
    if not isinstance(phases,dict) or set(phases)!=set(names) or not isinstance(lengths,dict) or set(lengths)!=set(names):
        raise ValueError('Missing phase cycles or cache lengths')
    for path,outer in zip(names,arrays):
        a,b=phases[path],lengths[path]
        if not isinstance(a,list) or len(a)!=4 or not isinstance(b,list) or len(b)!=4:raise ValueError('Wrong phase samples')
        for i,(cycles,history) in enumerate(zip(a,b)):
            if not isinstance(cycles,list) or len(cycles)!=t+1 or any(type(c) is not int or c<=0 for c in cycles) or sum(cycles)>outer[i]:
                raise ValueError('Phase windows exceed enclosing session or are invalid')
            if not isinstance(history,list) or any(type(n) is not int for n in history) or history!=list(range(p,p+t+1)):
                raise ValueError('Wrong observed KV history lengths')
'''+s[at:]
    s=change(s,"ffn_phase_counts=row['ffn_phase_counts'],", "phase_cycles=phases,session_lengths=lengths,contract_mask=row['contract_mask'],alternate_math_pass=True,ffn_phase_counts=row['ffn_phase_counts'],")
    generated['lv_spec.py']=s
    b=generated['linear_bench.cc']
    for entry in ('scalar','project','candidate','bulk'):
        b=b.replace('session_'+entry+'(int,int,int,const', 'session_'+entry+'(int,int,int,int,int,const')
        b=b.replace('session_'+entry+'(t.a,t.b,t.c,','session_'+entry+'(t.a,t.b,t.c,t.d,t.p,')
    b=change(b,'extern volatile unsigned lv_stage_counts[18];', '''extern volatile unsigned lv_stage_counts[18];
extern volatile unsigned lv_session_round[3],lv_session_cycles[48],lv_session_lengths[48];
unsigned session_contract(int,int,int,int,int,const float*,const float*,float*,float*);
volatile unsigned lv_contract_mask,lv_contract_calls,lv_contract_guard_ok,lv_alt_checked,lv_alt_mismatches;''')
    b=change(b,'Guarded lv_scalar_out,lv_project_out,lv_official_out,lv_bulk_out;',
        'Guarded lv_scalar_out,lv_project_out,lv_official_out,lv_bulk_out,lv_isolation_a,lv_isolation_b;')
    b=change(b,'session::Layout l(t.a,t.b,t.c);','session::Layout l(t.a,t.b,t.c,t.d,t.p);')
    b=change(b,'  lv_cache_ok=1;', '''  for(int i=0;i<3;++i)lv_session_round[i]=0;
  for(int i=0;i<48;++i)lv_session_cycles[i]=lv_session_lengths[i]=0;
  lv_contract_mask=lv_contract_calls=lv_contract_guard_ok=lv_alt_checked=lv_alt_mismatches=0;
  lv_cache_ok=1;''')
    b=change(b,'  const unsigned expected_counts[6]={8,32,16,8,8,8};',
        '  const unsigned q=4*(1+t.d);const unsigned expected_counts[6]={q,4*q,2*q,q,q,q};')
    b=change(b,'    if(lv_stream_ffn_counts[i]!=4)return 1;','    if(lv_stream_ffn_counts[i]!=unsigned(i%2?4*t.d:4))return 1;')
    needle='  lv_probe_signature=2166136261u;'
    b=change(b,needle,'''  if(t.nv!=t.ny)return 1;
  Reset(lv_isolation_a);Reset(lv_isolation_b);lv_contract_calls=1;
  lv_contract_mask=session_contract(t.a,t.b,t.c,t.d,t.p,lv_x,lv_w,lv_isolation_a.data,lv_isolation_b.data);
  if(lv_contract_mask!=63||!Guard(lv_isolation_a,t.ny)||!Guard(lv_isolation_b,t.ny)||
     !StageGuards(lv_isolation_a,t)||!StageGuards(lv_isolation_b,t))return 1;
  lv_contract_guard_ok=1;
  for(unsigned j=0;j<t.ny;++j) {
    lv_alt_mismatches+=!Close(lv_isolation_a.data[j],t.gold[j])||!Close(lv_isolation_b.data[j],t.v[j]);
    ++lv_alt_checked;
  }
  if(lv_alt_mismatches||lv_alt_checked!=t.ny)return 1;
'''+needle)
    generated['linear_bench.cc']=b
    p=generated['prepare.py'].replace('attention_core.h','attention_ops.h')
    p=change(p,"'session_layout.h','attention_layout.h'", "'session_layout.h','session_state.h','ffn_core.h','attention_layout.h'")
    p=change(p,'"session_layout.h","fixtures.cc"','"session_layout.h","session_state.h","ffn_core.h","fixtures.cc"')
    p=change(p,"'ffn_reference.py','session_layout.h')", "'ffn_reference.py','session_layout.h','session_state.h','ffn_core.h')")
    generated['prepare.py']=p
    generated['vm_bench.py']=generated['vm_bench.py'].replace('candidate_session_decode_test',
        'candidate_session_decode2_test').replace('candidate_session_tail_test',
        'candidate_session_tail3_test').replace('candidate_session_prefill_test','candidate_session_prefill3_test')
    a=generated['lv_audit.py']
    a=change(a,'LINKER=', '''SIZES.update(lv_session_round=12,lv_session_cycles=192,lv_session_lengths=192,
    lv_isolation_a=4128,lv_isolation_b=4128,lv_contract_mask=4,lv_contract_calls=4,
    lv_contract_guard_ok=4,lv_alt_checked=4,lv_alt_mismatches=4)
LINKER=''')
    a=change(a,"('session_scalar','session_project','session_candidate','session_bulk'):",
        "('session_scalar','session_project','session_candidate','session_bulk','session_init','session_prefill','session_decode','session_contract'):")
    generated['lv_audit.py']=a
    c=generated['lv_bench.py']
    c=c.replace('b+(p+1)*h','b+(p+data[\'shape\'][3])*h').replace('src+(p+1)*h','src+(p+data[\'shape\'][3])*h')
    needle='    canary=(await fixture.read(stack,size_bytes=64))'
    c=change(c,needle,'''    phase_raw=list(map(int,await fixture.read('lv_session_cycles',dtype=np.dtype('<u4'),shape=(48,))))
    length_raw=list(map(int,await fixture.read('lv_session_lengths',dtype=np.dtype('<u4'),shape=(48,))))
    steps=data['shape'][3];phase_cycles={};session_lengths={};unused=True
    for pi,name in enumerate(('scalar','project','candidate')):
        phase_cycles[name]=[phase_raw[pi*16+i*4:pi*16+i*4+steps+1] for i in range(4)]
        session_lengths[name]=[length_raw[pi*16+i*4:pi*16+i*4+steps+1] for i in range(4)]
        for i in range(4):
            unused=unused and all(v==0 for v in phase_raw[pi*16+i*4+steps+1:pi*16+i*4+4]+length_raw[pi*16+i*4+steps+1:pi*16+i*4+4])
    contract={name:int(await fixture.read_word('lv_'+name)) for name in
              ('contract_mask','contract_calls','contract_guard_ok','alt_checked','alt_mismatches')}
    iso_ok=[];iso_guards=True
    for label,expected in (('a',gold),('b',np.array(data['v'],dtype=np.float64))):
        raw=(await fixture.read('lv_isolation_'+label,size_bytes=4128)).tobytes()
        out=np.frombuffer(raw[16:16+4*n],dtype='<f4').astype(np.float64)
        iso_ok.append(bool(np.isfinite(out).all() and np.all(np.abs(out-expected)<=spec.ATOL+spec.RTOL*np.abs(expected))))
        iso_guards=iso_guards and raw[:16]==spec.GUARD*4 and raw[-16:]==spec.GUARD*4 and raw[16+4*n:-16]==spec.GUARD*(1024-n)
        for _,at,ns in layout[:-1]:iso_guards=iso_guards and raw[16+4*(at+ns):16+4*(at+ns+4)]==spec.GUARD*4
    canary=(await fixture.read(stack,size_bytes=64))''')
    c=change(c,'        ffn_phase_counts=', '''        phase_cycles=phase_cycles,session_lengths=session_lengths,unused_phase_slots_zero=unused,
        contract_mask=contract['contract_mask'],contract_calls=contract['contract_calls'],
        contract_guards_exact=iso_guards and contract['contract_guard_ok']==1,
        isolation_math_pass=iso_ok[0],alternate_math_pass=iso_ok[1],alternate_checked=contract['alt_checked'],
        alternate_mismatches=contract['alt_mismatches'],alternate_reference_sha256=data['alternate_sha256'],
        ffn_phase_counts=''')
    generated['lv_bench.py']=c
    generated['summarize.py']=generated['summarize.py'].replace('Single-layer Attention + GEGLU FFN prefill/decode',
        'Caller-owned KV single-layer multi-decode session').replace('ATTENTION candidate','session candidate')
    generated['summarize.py']=change(generated['summarize.py'],"    return '\\n'.join(text)+'\\n'",'''    text+=['','Nested API windows (steady mean, initialization excluded):','',
           '| Case | Phase | KV length after call | Project RVV | Candidate RVV | Project/candidate |',
           '|---|---|---:|---:|---:|---:|']
    for item in rows:
        r=item['observation'];p,_,_,t,_=r['shape']
        for phase in range(t+1):
            mean=lambda path:sum(sample[phase] for sample in r['phase_cycles'][path][1:])/3
            project,candidate=mean('project'),mean('candidate')
            label='prefill' if phase==0 else 'decode'+str(phase)
            text.append(f"| {r['case']} | {label} | {p+phase} | {project:.2f} | {candidate:.2f} | {project/candidate:.4f} |")
    text+=['','Phase windows include API checks and diagnostic copies; sum must fit the enclosing whole-session sample.',
           'Lifecycle rejection/reset and two independent interleaved contexts must pass, untimed.']
    return '\\n'.join(text)+'\\n' ''')
    e=generated['export.py'].replace('Stateful Transformer layer glue;', 'Caller-owned KV multi-call Transformer session;')
    generated['export.py']=e
    generated['SOURCES.md']='''Official Coral FP32 kernels and qualified MLAS-derived GELU remain frozen.
New code manages explicit caller-owned state across prefill and one-token decode API calls.
Synthetic FP32 inputs only; project RoPE/Attention exp is scalar libm. No VME/RTL changes.
'''
    for name in ('session.cc','session_state.h','session_layout.h','README.md'):
        generated[name]=(HERE/name).read_text(encoding='utf-8')
    generated['session_fixture.py']=(HERE/'fixture.py').read_text(encoding='utf-8')
    for name,text in generated.items():files[GENERATED+'/'+name]=text.encode('utf-8')
    return files

def expected():
    files=sources();digest=lambda b:hashlib.sha256(b).hexdigest()
    return files,dict(schema=1,kind='synthetic_Transformer_session_v2',parent=PIN,simulation='NOT_RUN',
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
    try:print('[SESSION_TOOLS_VERIFIED] '+str(verify(a.output) if a.existing else materialize(a.output)))
    except Exception as error:print('[SESSION_STOP] '+str(error),file=sys.stderr);sys.exit(1)
