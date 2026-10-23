"""Derive an isolated M sweep from an immutable, already tested tool revision.

This writes NEW generated experiment tools only. It never edits the parent
candidate, its prepared directories, upstream RTL or any accepted evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PARENT = 'a2497c05e44e3e911c24a57e3100ab687992bf7d'
MS = (1, 2, 4, 8, 12, 16)
CASES = tuple((f'm{m}_k64_n64', m, 64, 64) for m in MS)
PROBES = ((1,3,1),(16,4,16),(1,17,17),(16,17,17),(16,32,32),
          (1,64,64),(7,7,15),(15,63,31),(2,7,17),(4,17,31),
          (8,32,32),(12,63,63),(16,64,64))
GENERATED = 'verification/google_llm_vme_sweep_v1'


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError('Pinned template mismatch: '+repr(old))
    return text.replace(old, new)


def transform(name, text):
    # Version identity and markers, not measured numerical results.
    text = text.replace('llm_vme_opt_v1', 'llm_vme_sweep_v1')
    text = text.replace('llm_vme_opt_', 'llm_vme_sweep_')
    text = text.replace('LLM_VME_OPT', 'LLM_VME_SWEEP')
    if name == 'optimized_core.h':
        text = replace(text, 'if(m==1 || m==16)', 'if(m>=1 && m<=16)')
        # Broadcast initialization is correct in all VALID token lanes; unused
        # columns never get stored. Keep the qualified M1 special initialization.
    elif name == 'core_test.cc':
        text = replace(text, '(m==1||m==16?2u*tiles:0u)', '2u*tiles')
        text = replace(text, '(m==1||m==16?0u:2u*tiles)', '0u')
    elif name == 'linear_bench.cc':
        text = replace(text, '{{1,32,32},{16,32,32},{1,64,64},{16,64,64}}',
                       '{'+','.join('{'+f'{m},64,64'+'}' for m in MS)+'}')
        begin = text.index('constexpr int kProbeShapes[][3]=')
        end = text.index(';', begin)
        text = text[:begin]+'constexpr int kProbeShapes[][3]={'+','.join(
            '{'+','.join(map(str, shape))+'}' for shape in PROBES)+'}'+text[end:]
        text = replace(text, 'q<9', 'q<13')
        text = replace(text, 'for(unsigned i=0;i<4;++i)', 'for(unsigned i=0;i<6;++i)')
        text = replace(text, 'if(selected==4)', 'if(selected==6)')
        text = replace(text, 'if(selected>=4)', 'if(selected>=6)')
    elif name == 'lv_spec.py':
        begin = text.index('CASES=');end = text.index('\nSAMPLES=', begin)
        text = text[:begin]+'CASES='+repr(CASES)+text[end:]
        text = replace(text, 'PROBE_INDEX=4', 'PROBE_INDEX=6')
        begin = text.index('PROBE_SHAPES=');end = text.index('\nBASE_RTL_PACKAGE=', begin)
        text = text[:begin]+'PROBE_SHAPES='+repr(PROBES)+text[end:]
        text = replace(text, 'resident_INT8_linear_RVV_old_VME_vs_RVV_packing_direct_writeback_candidate_not_model',
                       'resident_INT8_M_sweep_same_ELF_RVV_old_VME_vs_all_M_direct_writeback_not_model')
        text = replace(text, 'short_candidate_RVV_pack_VME_init_strided_store_and_fallback_arithmetic_not_performance',
                       'short_all_M_RVV_pack_VME_init_strided_store_arithmetic_not_performance')
        text = replace(text, "return {4:'3-10 minutes',0:'4-10 minutes',1:'10-20 minutes',2:'5-15 minutes',3:'20-45 minutes'}[index]",
                       "return {6:'4-12 minutes',0:'5-15 minutes',1:'8-20 minutes',2:'10-25 minutes',3:'15-30 minutes',4:'20-40 minutes',5:'20-45 minutes'}[index]")
        text = replace(text, 'if m.CASES!=CASES:raise ValueError("Original shape set changed")',
                       '# Reuse the frozen generator, but supply this independent shape set.\n    m.CASES=CASES')
        text = replace(text, 'if m in (1,16):fast+=tiles\n        else:fallback+=tiles', 'fast+=tiles')
        text = replace(text, "case_id=4,case='optimized_instruction_probe'", "case_id=PROBE_INDEX,case='optimized_instruction_probe'", 1)
        text = replace(text, 'case_id=4,probe_cases=', 'case_id=PROBE_INDEX,probe_cases=')
        text = replace(text, 'probe_current_case=8,probe_step=6', 'probe_current_case=12,probe_step=6')
        text = replace(text, 'if len(rows)!=4 or', 'if len(rows)!=len(CASES) or')
    elif name == 'prepare.py':
        text = replace(text,
            'testcases=["candidate_probe_test","candidate_decode_tiny_test","candidate_prefill_tiny_test",\n        "candidate_decode_small_test","candidate_prefill_small_test"],',
            'testcases='+repr(['candidate_probe_test']+['candidate_'+c[0]+'_test' for c in CASES])+',')
    elif name == 'vm_bench.py':
        text = text[:text.index('@cocotb.test()')]
        for index, label in [(6,'probe')]+[(i,c[0]) for i,c in enumerate(CASES)]:
            text += f'@cocotb.test()\nasync def candidate_{label}_test(dut):await run_vm(dut,{index})\n\n'
    elif name == 'vm.py':
        text = replace(text, 'def model_query(index=4):', 'def model_query(index=spec.PROBE_INDEX):')
        text = replace(text, 'targets=[spec.target(i) for i in (4,0,1,2,3)]',
                       'targets=[spec.target(i) for i in (spec.PROBE_INDEX,*range(len(spec.CASES)))]')
        text = text.replace('index==4', 'index==spec.PROBE_INDEX')
        text = replace(text, 'checked_run_proof(prepared,record,packet,4)',
                       'checked_run_proof(prepared,record,packet,spec.PROBE_INDEX)')
        text = replace(text, 'choices=range(5),default=4', 'choices=range(7),default=6')
        text = replace(text, "sequence=(4,1) if a.plan=='quick' else (4,0,1,2,3)",
                       "sequence=(spec.PROBE_INDEX,3) if a.plan=='quick' else (spec.PROBE_INDEX,*range(len(spec.CASES)))")
    elif name == 'server.py':
        text = replace(text, 'choices=range(5),default=4', 'choices=range(7),default=6')
    elif name == 'summarize.py':
        text = text.replace('range(4)', 'range(len(spec.CASES))')
        text = replace(text, '0<=index<4', '0<=index<len(spec.CASES)')
        text = replace(text, 'Need four distinct server cases', 'Need six distinct server cases')
        text = replace(text, '{len(rows)}/4', '{len(rows)}/{len(spec.CASES)}')
        text = replace(text, 'total_cases=4', 'total_cases=len(spec.CASES)')
        text = replace(text, "'All comparisons use this same new ELF; do not splice old v2 or profiling cycles into these ratios.',",
                       "'All comparisons use this same new ELF; do not splice parent/profiling cycles into these ratios.',\n        'Measured M points only: no interpolation or universal crossover threshold. Complete and reused-weight routing can differ.',")
    elif name == 'run_vm.sh':
        text = text.replace('0|1|2|3', '0|1|2|3|4|5')
        text = replace(text, '--case 4', '--case 6')
    elif name == 'run_server.sh':
        text = text.replace('0|1|2|3', '0|1|2|3|4|5').replace('[0-3]', '[0-5]')
        text = replace(text, '--case 4', '--case 6')
        text = replace(text, 'opt_cases=(1);else opt_cases=(0 1 2 3)', 'opt_cases=(3);else opt_cases=(0 1 2 3 4 5)')
    elif name == 'tomorrow.sh':
        text = replace(text, 'quick roughly 15-35min; all roughly 45-100min',
                       'quick roughly 20-45min; all roughly 80-180min')
    return text


def sources(repo=REPO):
    paths = subprocess.check_output(['git','-C',str(repo),'ls-tree','-r','--name-only',PARENT,
        'verification/google_llm_vme_opt','verification/google_llm_ops',
        'verification/google_tcm_capacity','verification/google_person_vme/vme_tile.h',
        'verification/google_person_pool/model_runner.py'], text=True).splitlines()
    selected = []
    for path in paths:
        p = Path(path)
        if path.startswith('verification/google_llm_vme_opt/') and p.name not in ('test_lv.py','README.md'):
            selected.append(path)
        elif p.parent.as_posix() == 'verification/google_llm_ops' and p.suffix in ('.py','.cc','.h') and not p.name.startswith('test_'):
            selected.append(path)
        elif p.parent.as_posix() == 'verification/google_tcm_capacity' and p.name in ('prepare.py','capacity_spec.py','capacity_bench.py'):
            selected.append(path)
        elif path in ('verification/google_person_vme/vme_tile.h','verification/google_person_pool/model_runner.py'):
            selected.append(path)
    files={};parents={}
    for path in selected:
        raw = subprocess.check_output(['git','-C',str(repo),'show',PARENT+':'+path])
        parents[path] = hashlib.sha256(raw).hexdigest()
        if path.startswith('verification/google_llm_vme_opt/'):
            destination = GENERATED+'/'+Path(path).name
            raw = transform(Path(path).name, raw.decode('utf-8')).encode('utf-8')
        else:destination=path
        files[destination] = raw
    if len(files)<25:raise ValueError('Missing pinned parent tool dependencies')
    files[GENERATED+'/README.md']=(HERE/'README.md').read_bytes()
    return files,parents


def materialize(destination,repo=REPO):
    files,parents=sources(repo)
    # Fail before writing if any destination exists. Never silently reuse stale
    # transformed tools. Resumption uses the explicit --existing verification.
    destination=Path(destination).absolute()
    if destination.exists():raise ValueError('Tool destination already exists; nothing overwritten')
    destination.mkdir(parents=False)
    for name,raw in files.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)
    record=dict(schema=1,kind='llm_vme_M_sweep_tools_v1',parent_revision=PARENT,
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        cases=CASES,probe_shapes=PROBES,parent_files=parents,
        files={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()},simulation='NOT_RUN')
    with (destination/'tool-manifest.json').open('x',encoding='utf-8') as f:json.dump(record,f,indent=2)
    verify(destination,repo)
    print('[LLM_VME_SWEEP_TOOLS] '+str(destination/GENERATED),flush=True)
    return destination/GENERATED


def verify(destination,repo=REPO):
    destination=Path(destination).resolve(strict=True)
    files,parents=sources(repo);record=json.loads((destination/'tool-manifest.json').read_text())
    expected=dict(schema=1,kind='llm_vme_M_sweep_tools_v1',parent_revision=PARENT,
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        cases=[list(c) for c in CASES],probe_shapes=[list(s) for s in PROBES],parent_files=parents,
        files={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()},simulation='NOT_RUN')
    if record!=expected:raise ValueError('Tool manifest/parent/generator changed')
    actual={p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in destination.rglob('*') if p.is_file() and p!=destination/'tool-manifest.json'}
    if any(p.is_symlink() for p in destination.rglob('*')) or actual!=record['files']:
        raise ValueError('Missing/extra/changed generated tool files')
    return destination/GENERATED


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--existing',action='store_true');a=p.parse_args()
    try:
        if a.existing:print('[LLM_VME_SWEEP_TOOLS_VERIFIED] '+str(verify(a.output)))
        else:materialize(a.output)
    except Exception as error:print('[LLM_VME_SWEEP_STOP] '+str(error),file=sys.stderr);sys.exit(1)
