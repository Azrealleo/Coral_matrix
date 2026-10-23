"""Frozen independent direct-official-RVV benchmark; generation is NOT RTL."""
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
PIN='b9fda5482f04a663b06d4a8460920f5a0a51b216'
GENERATED='verification/google_official_rvv_v1'


def read(path):return subprocess.check_output(['git','-C',str(REPO),'show',PIN+':'+path])
class Frozen:
    def __init__(self,path):self.path=path
    def __truediv__(self,name):return Frozen(self.path+'/'+name)
    def read_bytes(self):return read(self.path)
    def read_text(self):return self.read_bytes().decode()


def sources():
    raw=read('verification/google_llm_vme_pair/materialize.py')
    m=types.ModuleType('_direct_official_parent');m.__file__=str(REPO/'verification/google_llm_vme_pair/materialize.py')
    exec(compile(raw,m.__file__,'exec'),m.__dict__);m.HERE=Frozen('verification/google_llm_vme_pair')
    inherited,_=m.sources(REPO)
    files={p:b for p,b in inherited.items() if not p.startswith(m.GENERATED+'/')}
    base={Path(p).name:b for p,b in inherited.items() if p.startswith(m.GENERATED+'/')}
    transform=lambda s:s.replace('llm_vme_pair_v2','official_rvv_v1').replace('llm_vme_pair_','official_rvv_').replace('LLM_VME_PAIR','OFFICIAL_RVV')
    r=lambda name:transform(base[name].decode())
    generated={name:r(name) for name in ('vm.py','server.py','lv_packet.py','export.py','build_export.sh','prepare_tomorrow.sh','run_vm.sh','summarize.py')}
    generated['vm.py']=generated['vm.py'].replace("sequence=(spec.PROBE_INDEX,5)","sequence=(spec.PROBE_INDEX,0)")
    generated['vm.py']=generated['vm.py'].replace('VM_RTL_PASS','VM_DIAGNOSTIC_PASS')
    generated['server.py']=generated['server.py'].replace('RTL_PASS','DIAGNOSTIC_PASS')
    generated['build_export.sh']=generated['build_export.sh'].replace('"$lv_pkg:host_reference_test" "$lv_pkg:host_packing_test"','"$lv_pkg:host_reference_test"')
    generated['build_export.sh']=generated['build_export.sh'].replace('Native packing/arithmetic reference only','Native scalar mirrors/reference only')
    generated['export.py']=generated['export.py'].replace("'lv_spec.py','lv_audit.py','lv_packet.py','server.py'", "'lv_spec.py','lv_audit.py','lv_packet.py','tx_reference.py','server.py'")
    start=generated['export.py'].index("    (packet/'NOTICES.txt').write_text(")
    end=generated['export.py'].index('    lv_packet.seal',start)
    generated['export.py']=generated['export.py'][:start]+'''    (packet/'NOTICES.txt').write_text('Unmodified official Google CoralNPU FP32 RVV kernels: Apache-2.0.\\n'
        'Project scalar/RVV controls are frozen; host mirrors are NOT hardware execution.\\n'
        'GELU rational tanh approximation quality is reported separately, not silently qualified.\\n',encoding='utf-8')
'''+generated['export.py'][end:]
    generated['lv_packet.py']=generated['lv_packet.py'].replace("'lv_bench.py','lv_packet.py'):","'lv_bench.py','lv_packet.py','tx_reference.py'):")
    audit=r('lv_audit.py')
    start=audit.index('SIZES=');end=audit.index('LINKER=',start)
    audit=audit[:start]+'''SIZES={'lv_'+n:4 for n in ('case','status','checked','mismatches','quality_mismatches','guard_ok','empty_cycles',
    'scalar_calls','project_calls','official_calls','probe_signature')}
SIZES.update(lv_scalar_cycles=16,lv_project_cycles=16,lv_official_cycles=16,lv_x=4096,lv_w=4096,
    lv_scalar_out=4128,lv_project_out=4128,lv_official_out=4128)
'''+audit[end:]
    start=audit.index('def operations(');end=audit.index('def inspect(',start)
    audit=audit[:start]+'''def instruction_audit(elf):
    table=list(elf.get_section_by_name('.symtab').iter_symbols());result={}
    for entry,fragment in (('RmsNormF','rvv_rms_norm'),('rvv_residual_add_f32','rvv_residual_add'),
                           ('rvv_tanh_gelu_mul_f32','rvv_tanh_gelu_mul')):
        if not any(s.name==entry and s['st_size'] for s in table):raise ValueError('Missing official entry '+entry)
        instructions=[]
        for s in table:
            if (s.name==entry or fragment in s.name) and s['st_info']['type']=='STT_FUNC' and s['st_size']:
                section=elf.get_section(s['st_shndx']);offset=int(s['st_value'])-int(section['sh_addr'])
                instructions+=words(section.data()[offset:offset+int(s['st_size'])])
        if not any(w&127==0x57 and (w>>12)&7!=7 for w in instructions):raise ValueError('No vector arithmetic in '+entry)
        result[entry]='real_ELF_vector_presence_not_execution'
    return result


'''+audit[end:]
    generated['lv_audit.py']=audit
    start=generated['summarize.py'].index('def markdown(');end=generated['summarize.py'].index('def main(',start)
    generated['summarize.py']=generated['summarize.py'][:start]+'''def markdown(rows):
    text=['Official RVV direct-call diagnostics; full model / VME: NOT_RUN.','',
          '| Case | Scalar | Project RVV | Official RVV | Project/official | Strict math quality |',
          '|---|---:|---:|---:|---:|---|']
    for item in rows:
        row=item['observation'];c=item['comparison'];mean=lambda name:sum(row[name][1:])/3
        text.append('| '+row['case']+' | '+' | '.join(f'{mean(k):.2f}' for k in ('scalar_cycles','project_cycles','official_cycles'))+
          f" | {c['steady_project_over_official']:.4f} | "+('PASS' if c['strict_math_quality_pass'] else 'FAIL: approximation diagnostic ONLY')+' |')
    text+=['','Raw kernel mcycle, not host wall time. Ratios >1 favor official RVV.',
           'GELU approximates tanh. Algorithm execution PASS does not mean strict mathematical quality PASS.',
           'All paths and the pre-existing project control use this same ELF. No old-cycle splicing.']
    return '\\n'.join(text)+'\\n'


'''+generated['summarize.py'][end:]
    prefix=r('lv_bench.py').split('async def run_case(',1)[0]
    generated['lv_bench.py']=prefix+(HERE/'bench.py').read_text(encoding='utf-8')
    old_spec=r('lv_spec.py');names=['residual256','rms64','rms_tail37','gelu32','gelu_tail37','gelu256']
    wrapper=r('vm_bench.py');start=wrapper.index('@cocotb.test()')
    generated['vm_bench.py']=wrapper[:start]+'\n'.join('@cocotb.test()\nasync def '+('candidate_probe_test' if i==6 else 'candidate_'+names[i]+'_test')+'(dut): await run_vm(dut,'+str(i)+')\n' for i in (6,*range(6)))
    generated['run_server.sh']='#!/usr/bin/env bash\nset -euo pipefail\necho "This first direct-call pilot is VM-only; server export is not yet qualified." >&2\nexit 2\n'
    for local,target in (('spec.py','lv_spec.py'),('prepare.py','prepare.py'),('bench.cc','linear_bench.cc'),('host_mirrors.cc','host_mirrors.cc'),('README.md','README.md')):
        generated[target]=(HERE/local).read_text(encoding='utf-8')
    generated['SOURCES.md']='Official kernels are byte-identical to '+old_spec.split('UPSTREAM="',1)[1].split('"',1)[0]+'; source file SHA256 values are in source-manifest.json.\n'
    for name in ('kernels.h','kernels.cc'):
        generated[name]=read('verification/google_llm_ops/transformer/'+name).decode()
    generated['tx_reference.py']=read('verification/google_llm_ops/transformer/tx_spec.py').decode()
    for name,text in generated.items():files[GENERATED+'/'+name]=text.encode()
    return files


def expected():
    files=sources()
    digest=lambda b:hashlib.sha256(b).hexdigest()
    record=dict(schema=1,kind='direct_official_rvv_v1',parent=PIN,simulation='NOT_RUN',
        generator_sha256=digest(Path(__file__).read_bytes()),files={n:digest(b) for n,b in files.items()})
    return files,record


def verify(destination):
    root=Path(destination).resolve(strict=True);_,record=expected()
    if json.loads((root/'tool-manifest.json').read_text())!=record:raise ValueError('Tool identity changed')
    actual={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.name!='tool-manifest.json'}
    if any(p.is_symlink() for p in root.rglob('*')) or actual!=record['files']:raise ValueError('Missing/extra/changed tool snapshot')
    return root/GENERATED


def materialize(destination):
    root=Path(destination).absolute();files,record=expected()
    if root.exists():raise ValueError('Destination exists; preserve old job')
    root.mkdir()
    for name,data in files.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:f.write(data)
    with (root/'tool-manifest.json').open('x',encoding='utf-8') as f:json.dump(record,f,indent=2)
    return verify(root)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--existing',action='store_true');a=p.parse_args()
    try:print('[OFFICIAL_RVV_TOOLS_VERIFIED] '+str(verify(a.output) if a.existing else materialize(a.output)))
    except Exception as error:print('[OFFICIAL_RVV_STOP] '+str(error),file=sys.stderr);sys.exit(1)
