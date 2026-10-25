"""Independent strict GELU RVV candidate; frozen original verification tools."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PIN = '72e940b74b4bb03dfb75244d23c0447e553ffad9'
GENERATED = 'verification/google_gelu_rvv_mlas_v2'


def read(path):
    return subprocess.check_output(['git', '-C', str(REPO), 'show', PIN+':'+path])


class Frozen:
    def __init__(self, path): self.path = path
    def __truediv__(self, name): return Frozen(self.path+'/'+name)
    def read_bytes(self): return read(self.path)
    def read_text(self, **kwargs): return self.read_bytes().decode('utf-8')


def change(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Frozen generator interface changed: '+old[:100])
    return text.replace(old, new)


def sources():
    parent = types.ModuleType('_gelu_mlas_parent')
    parent.__file__ = str(REPO/'verification/google_official_rvv/materialize.py')
    exec(compile(read('verification/google_official_rvv/materialize.py'), parent.__file__, 'exec'), parent.__dict__)
    parent.HERE = Frozen('verification/google_official_rvv')
    inherited = parent.sources()
    files = {p: b for p,b in inherited.items() if not p.startswith(parent.GENERATED+'/')}
    transform = lambda s: s.replace('google_official_rvv_v1', 'google_gelu_rvv_mlas_v2').replace(
        'official_rvv_v1', 'gelu_rvv_mlas_v2').replace('official_rvv_', 'gelu_rvv_mlas_').replace(
        'OFFICIAL_RVV', 'GELU_RVV_MLAS').replace('OFFICIAL_HOST', 'GELU_MLAS_HOST')
    generated = {Path(p).name: transform(b.decode()) for p,b in inherited.items()
                 if p.startswith(parent.GENERATED+'/')}
    s = generated['lv_spec.py']
    start = s.index('CASES='); end = s.index('ATOL=', start)
    s = s[:start]+'''CASES=(('gelu32','GEGLU',(32,0,0,0,0)),
       ('gelu_tail37','GEGLU',(37,0,0,0,0)),('gelu256','GEGLU',(256,0,0,0,0)))
PROBE_INDEX=3
PROBE_CASE=('gelu_safety','GEGLU',(1,0,0,0,0))
'''+s[end:]
    s = s.replace('resident_FP32_scalar_project_RVV_vs_unmodified_official_RVV_diagnostic_not_model',
                  'resident_FP32_scalar_project_RVV_vs_MLAS_based_RVV_GELU_strict_not_model')
    s = s.replace('official_RVV_residual_safety_probe_not_performance',
                  'MLAS_based_RVV_GELU_zero_safety_probe_not_performance')
    s = s.replace("if index==6 else", "if index==PROBE_INDEX else")
    begin = s.index('def eta('); end = s.index('def packed(', begin)
    s = s[:begin]+'''def eta(index):return {3:'0.5-2 minutes',0:'1-4 minutes',1:'1-4 minutes',2:'2-5 minutes'}[index]

'''+s[end:]
    begin = s.index('def fixture('); end = s.index('def signature(', begin)
    s = s[:begin]+'''def fixture(index):
    path=Path(__file__).with_name('tx_reference.py')
    module_spec=importlib.util.spec_from_file_location('_mlas_reference',path)
    m=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(m)
    # Preserve the ORIGINAL case indices/seeds used by the accepted benchmark.
    m.CASES=(('residual256','RESIDUAL',(256,0,0,0,0)),('rms64','RMS',(1,64,0,0,0)),
             ('rms_tail37','RMS',(3,37,0,0,0)),*CASES,PROBE_CASE)
    data=m.fixture(index+3 if index<3 else 6);data['id']=index
    if index==PROBE_INDEX:
        # Zero exercises the actual GELU vector entry with an exact FP32 result;
        # it is a startup/guard probe, NOT adequate standalone accuracy coverage.
        data.update(x=[0.0],w=[2.0],v=[],y=[0.0])
        data['vector_sha256']=hashlib.sha256(packed(data['x'])+packed(data['w'])).hexdigest()
    data['algorithm']=data['y'][:]
    data['algorithm_sha256']=hashlib.sha256(packed(data['algorithm'])).hexdigest()
    return data


'''+s[end:]
    s = s.replace('len(rows)!=7', 'len(rows)!=4')
    needle = "        if (int(index),int(count))!=(i,12*len(fixture(i)['y'])):raise ValueError('Wrong native case/signature')"
    s = change(s, needle, needle+'''
    dense=re.findall(r'^\\[GELU_MLAS_HOST_NUMERICS_PASS\\] checked=81925 max_abs_error=([0-9.eE+-]+) max_tolerance_multiple=([0-9.eE+-]+) hardware=NOT_RUN$',text,re.M)
    if len(dense)!=1 or not all(math.isfinite(float(x)) and float(x)>=0 for x in dense[0]) or float(dense[0][1])>1:
        raise ValueError('Missing/failed bounded host accuracy sweep')''')
    s = s.replace("if data['kind']!='GEGLU' and not q:", 'if not q:')
    s = s.replace("'official_clamped_rational_tanh'", "'MLAS_v1_20_1_high_order_rational_tanh'")
    s = s.replace('official_cycles=arrays[2]', 'candidate_cycles=arrays[2]').replace(
        'steady_scalar_over_official=', 'steady_scalar_over_candidate=').replace(
        'steady_project_over_official=', 'steady_project_over_candidate=')
    generated['lv_spec.py'] = s
    b = generated['linear_bench.cc']
    b = change(b, 'void rvv_tanh_gelu_mul_f32(', 'void candidate_gelu_f32(')
    b = change(b, 'rvv_tanh_gelu_mul_f32(lv_x,lv_w,y,t.a)', 'candidate_gelu_f32(lv_x,lv_w,y,t.a)')
    b = change(b, 'if(t.kind!=GEGLU&&lv_quality_mismatches)', 'if(lv_quality_mismatches)')
    generated['linear_bench.cc'] = b
    p = generated['prepare.py']
    p = change(p, "for i in range(7):", 'for i in range(4):')
    p = change(p, 'kCaseCount=7;', 'kCaseCount=4;')
    p = change(p, "srcs=['linear_bench.cc'", "srcs=['candidate.cc','linear_bench.cc'")
    p = change(p, 'srcs=["linear_bench.cc"', 'srcs=["candidate.cc","linear_bench.cc"')
    p = change(p, 'for i in (6,*range(6))', 'for i in (3,0,1,2)')
    p = change(p, "'lv_bench.py','vm_bench.py','tx_reference.py')",
               "'lv_bench.py','vm_bench.py','tx_reference.py','candidate.cc','host_accuracy.cc','LICENSE-MLAS.txt')")
    p = change(p, 'py_library(name="support"', '''cc_test(name="host_accuracy_test",srcs=["candidate.cc","host_accuracy.cc"],
    copts=["-std=c++17","-O2","-DTX_HOST=1","-ffp-contract=off","-fno-tree-vectorize"],)
py_library(name="support"''')
    generated['prepare.py'] = p
    generated['build_export.sh'] = change(generated['build_export.sh'],
        '"$lv_pkg:host_reference_test" 2>&1', '"$lv_pkg:host_reference_test" "$lv_pkg:host_accuracy_test" 2>&1')
    generated['vm.py'] = change(generated['vm.py'],
        'choices=range(7),default=6', 'choices=range(4),default=spec.PROBE_INDEX')
    generated['run_vm.sh'] = generated['run_vm.sh'].replace('probe|0|1|2|3|4|5', 'probe|0|1|2').replace(
        '--case 6', '--case 3').replace('0|1|2|3|4|5)', '0|1|2)')
    generated['lv_bench.py'] = generated['lv_bench.py'].replace('if index==6 else', 'if index==spec.PROBE_INDEX else')
    wrapper = generated['vm_bench.py']; begin = wrapper.index('@cocotb.test()')
    generated['vm_bench.py'] = wrapper[:begin]+'\n'.join(
        '@cocotb.test()\nasync def '+('candidate_probe_test' if i==3 else 'candidate_'+
        ('gelu32','gelu_tail37','gelu256')[i]+'_test')+'(dut): await run_vm(dut,'+str(i)+')\n'
        for i in (3,0,1,2))
    # The linked candidate intentionally does not call the old approximate
    # GELU. --gc-sections may remove that function. Audit the LIVE candidate
    # entry, not unused controls. Their source byte identities are still sealed.
    generated['lv_audit.py'] = change(generated['lv_audit.py'],
        "for entry,fragment in (('RmsNormF','rvv_rms_norm'),('rvv_residual_add_f32','rvv_residual_add'),\n"
        "                           ('rvv_tanh_gelu_mul_f32','rvv_tanh_gelu_mul')):",
        "for entry,fragment in (('candidate_gelu_f32','candidate_gelu_f32'),):")
    generated['lv_audit.py'] = change(generated['lv_audit.py'],
        "        result[entry]='real_ELF_vector_presence_not_execution'",
        "        if entry=='candidate_gelu_f32' and not any(w&127==0x57 and (w>>26)&63==32 and (w>>12)&7==1 for w in instructions):\n"
        "            raise ValueError('Missing actual candidate vector FP32 division')\n"
        "        result[entry]='real_ELF_vector_presence_not_execution'")
    summary = generated['summarize.py']
    summary = summary.replace('Official RVV direct-call diagnostics', 'Independent MLAS-based RVV GELU strict comparison')
    summary = summary.replace('| Official RVV |', '| Candidate RVV |').replace(
        "c['steady_project_over_official']", "c['steady_project_over_candidate']")
    summary = summary.replace('GELU approximates tanh. Algorithm execution PASS does not mean strict mathematical quality PASS.',
        'Candidate must pass the original strict math gate; this is not the old low-accuracy official approximation.')
    generated['summarize.py'] = summary
    generated['export.py'] = change(generated['export.py'],
        "'GELU rational tanh approximation quality is reported separately, not silently qualified.\\n'",
        "'Independent high-order RVV GELU port: original strict math gate required.\\n'\n"
        "        'MLAS coefficients/algorithm: Microsoft MIT; see source/LICENSE-MLAS.txt.\\n'")
    for name in ('candidate.cc','host_accuracy.cc','LICENSE-MLAS.txt','README.md'):
        generated[name] = (HERE/name).read_text(encoding='utf-8')
    generated['SOURCES.md'] = '''MLAS tanh algorithm/coefficient provenance:
ONNX Runtime v1.20.1, commit 5c1b7ccbff7e5141c1da7a9d963d660e5741c319.
onnxruntime/core/mlas/lib/tanh.cpp SHA256 d899b5fdb6bc78214668fa30e1281fad851cd3241504ba24f2551659c275cb89.
https://github.com/microsoft/onnxruntime/blob/5c1b7ccbff7e5141c1da7a9d963d660e5741c319/onnxruntime/core/mlas/lib/tanh.cpp
Microsoft MIT notice is in LICENSE-MLAS.txt and included in exported sources.
RVV glue/fused GELU is a new project port, not an unmodified upstream kernel.
Original Coral control kernels and FP64 reference remain frozen and unchanged.
'''
    for name, text in generated.items(): files[GENERATED+'/'+name] = text.encode('utf-8')
    return files


def expected():
    files=sources(); digest=lambda b:hashlib.sha256(b).hexdigest()
    return files, dict(schema=1,kind='strict_gelu_rvv_mlas_v2',parent=PIN,simulation='NOT_RUN',
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
    try:print('[GELU_RVV_MLAS_TOOLS_VERIFIED] '+str(verify(a.output) if a.existing else materialize(a.output)))
    except Exception as error:print('[GELU_RVV_MLAS_STOP] '+str(error),file=sys.stderr);sys.exit(1)
