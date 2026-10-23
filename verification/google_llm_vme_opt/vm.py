"""VM build-only preparation and explicitly requested sequential RTL runs."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
sys.dont_write_bytecode=True
import lv_spec as spec
import lv_audit as audit
import lv_packet
import prepare as source_prepare

HERE=Path(__file__).resolve().parent
BAZEL_SHA='a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f'
FLAGS=['--noshow_progress','--color=no','--curses=no','--jobs=2','--local_resources=memory=4096',
    '--lockfile_mode=error','--repo_env=CORALNPU_MAKE_JOBS=2','--action_env=LANG=C.UTF-8','--action_env=LC_ALL=C.UTF-8']


def write(path,value):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)


def environment():
    result=os.environ.copy()
    for name in ('WAVES','GUI','COCOTB_ENABLE_PROFILING','COCOTB_TEST_FILTER','COCOTB_TESTCASE'):
        result.pop(name,None)
    result['PYTHONDONTWRITEBYTECODE']='1'
    return result


def bazel(study):
    binary=study/'bazel-9.1.0'
    if spec.sha(binary)!=BAZEL_SHA:raise ValueError('Unexpected VM Bazel executable')
    return [str(binary),'--output_user_root='+str(study/'bazel-user'),'--host_jvm_args=-Xmx2g','--noblock_for_lock']


def process(argv,cwd,directory,label,timeout):
    """Own one process group; never stop another user's/model's process."""
    log=directory/(label+'.log');write(directory/(label+'-command.json'),argv)
    start=time.monotonic();timed_out=False
    print('[LLM_VME_OPT_VM_PHASE] '+label+' log='+str(log),flush=True)
    with log.open('xb') as stream:
        child=subprocess.Popen(argv,cwd=cwd,env=environment(),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        try:code=child.wait(timeout=timeout)
        except (subprocess.TimeoutExpired,KeyboardInterrupt) as error:
            timed_out=isinstance(error,subprocess.TimeoutExpired)
            try:os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10)
            except ProcessLookupError:pass
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL)
            code=child.wait()
            if not timed_out:code=130
    status=dict(exit_code=code,timed_out=timed_out,elapsed_seconds=time.monotonic()-start,timeout_seconds=timeout,
        argv=argv,log=str(log))
    write(directory/(label+'-status.json'),status)
    return status


def query(prefix,source,args):
    return subprocess.check_output(prefix+args,cwd=source,env=environment(),text=True,timeout=600).strip()


def model_query(index=4):
    return "filter('//"+spec.BASE_RTL_PACKAGE+":model$', deps("+spec.target(index)+"))"


def checked_configured_model(study,source,record,index):
    prefix=bazel(study)
    execution_root=Path(query(prefix,source,['info','execution_root'])).resolve(strict=True)
    listing=query(prefix,source,['cquery',*FLAGS,'--universe_scope='+spec.target(index),'--output=files',model_query(index)])
    model=audit.configured(execution_root,listing,spec.TOP)
    if str(model)!=record['model'] or spec.sha(model)!=record['model_sha256']:
        raise ValueError('Actual configured test model changed; refusing to substitute/relabel/rebuild during run')
    return dict(target=spec.target(index),model=str(model),model_sha256=record['model_sha256'])


def prepare_vm(study,source,prepared):
    """Build test executables, NOT test: this does NOT start RTL simulation."""
    prepared=prepared.resolve(strict=True)
    packet=lv_packet.load(prepared/'firmware'/spec.PACKET_NAME)
    source_prepare.prepare(source)
    prefix=bazel(study)
    targets=[spec.target(i) for i in (4,0,1,2,3)]
    status=process(prefix+['build',*FLAGS,*targets],source,prepared,'model-build',7200)
    if status['exit_code'] or status['timed_out']:raise ValueError('Model build incomplete; NOT simulated; inspect '+status['log'])
    execution_root=Path(query(prefix,source,['info','execution_root'])).resolve(strict=True)
    model_listing=query(prefix,source,['cquery',*FLAGS,'--output=files',model_query()])
    model=audit.configured(execution_root,model_listing,spec.TOP)
    elf_listing=query(prefix,source,['cquery',*FLAGS,'--universe_scope=//'+spec.PACKAGE+':probe_program.elf',
        '--output=files','config(//'+spec.PACKAGE+':probe_program.elf, target)'])
    elf=audit.configured(execution_root,elf_listing,'probe_program.elf')
    if elf.read_bytes()!=(packet.root/'probe_program.elf').read_bytes():raise ValueError('Built tests no longer use the exported ELF')
    record=dict(schema=1,kind='llm_vme_opt_vm_preparation_v1',simulation='NOT_RUN',study=str(study),source=str(source),
        packet=str(packet.root),packet_manifest_sha256=spec.sha(packet.root/'manifest.json'),
        elf_sha256=packet.report['elf_sha256'],rtl_sha256=spec.RTL_SHA,model=str(model),model_sha256=spec.sha(model),
        model_query=model_query(),source_manifest_sha256=spec.sha(source/source_prepare.MANIFEST),controller_sha256=spec.sha(__file__),
        generated_files=packet.manifest['files'],targets=targets)
    write(prepared/'preparation.json',record)
    print('[LLM_VME_OPT_VM_PREPARED] RTL_simulation=NOT_RUN directory='+str(prepared),flush=True)


def checked_preparation(prepared):
    prepared=Path(prepared).resolve(strict=True);record=json.loads((prepared/'preparation.json').read_text())
    if record.get('schema')!=1 or record.get('kind')!='llm_vme_opt_vm_preparation_v1' or record.get('simulation')!='NOT_RUN':
        raise ValueError('Wrong VM preparation record')
    if record.get('controller_sha256')!=spec.sha(__file__):raise ValueError('VM controller changed since preparation')
    packet=lv_packet.load(record['packet']);source=Path(record['source']).resolve(strict=True)
    study=Path(record['study']).resolve(strict=True)
    if packet.root!=prepared/'firmware'/spec.PACKET_NAME:raise ValueError('Prepared packet moved/replaced')
    if spec.sha(packet.root/'manifest.json')!=record['packet_manifest_sha256'] or packet.report['elf_sha256']!=record['elf_sha256']:
        raise ValueError('Prepared firmware identity changed')
    if record['rtl_sha256']!=spec.RTL_SHA or spec.sha(record['model'])!=record['model_sha256']:
        raise ValueError('Prepared hardware/model binary changed; prepare again in a NEW directory')
    if spec.sha(source/source_prepare.MANIFEST)!=record['source_manifest_sha256']:
        raise ValueError('Prepared source manifest changed')
    # No new compilation or source rewriting here; verify generated snapshot.
    manifest=json.loads((source/source_prepare.MANIFEST).read_text())
    if manifest['scope']!=spec.SCOPE:raise ValueError('Wrong prepared source scope')
    for name,digest in manifest['files'].items():
        lv_packet.safe_name(name)
        if spec.sha(source/name)!=digest:raise ValueError('Generated source changed: '+name)
    bazel(study)
    return record,packet,source,study


def checked_results(directory,packet,index):
    directory=Path(directory).resolve(strict=True)
    status=json.loads((directory/'test-status.json').read_text())
    if type(status.get('exit_code')) is not int or status['exit_code']!=0 or status.get('timed_out') is not False:
        raise ValueError('VM test failed/timed out/interrupted')
    # Bazel's XML may wrap the simulator as a shell testcase. Pair it with the
    # exact Cocotb test name, summary, observation, exit status and ELF identity.
    tree=ET.parse(directory/'test.xml').getroot()
    spec.checked_xml(tree)
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',(directory/'test.log').read_text())
    if not re.search(r'running\s+vm_bench\.'+re.escape(spec.testcase(index))+r'\s',text):
        raise ValueError('Wrong/missing actual Cocotb VM testcase')
    summaries=re.findall(r'TESTS=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)\s+SKIP=(\d+)',text)
    if not summaries or summaries[-1]!=('1','1','0','0'):raise ValueError('Cocotb did not pass exactly one VM test')
    rows=[json.loads(line.split(spec.MARKER,1)[1].strip()) for line in text.splitlines() if spec.MARKER in line]
    if len(rows)!=1:raise ValueError('Missing/duplicate VM observation')
    row=rows[0];comparison=spec.accept(row,index)
    if row['elf_sha256']!=packet.report['elf_sha256']:raise ValueError('VM executed a different ELF')
    return row,comparison,status


def proof_name(index):return 'probe-proof.json' if index==4 else 'case'+str(index)+'-proof.json'


def checked_run_proof(prepared,record,packet,index):
    path=prepared/proof_name(index)
    if not path.is_file():raise ValueError('Candidate VM probe missing: run probe FIRST with this preparation' if index==4 else 'Missing accepted case proof')
    proof=json.loads(path.read_text());directory=Path(proof['directory']).resolve(strict=True)
    if not directory.is_relative_to(prepared/'runs'):raise ValueError('Accepted result escaped preparation runs')
    row,_,_=checked_results(directory,packet,index)
    identity=json.loads((directory/'preparation-identity.json').read_text())
    if identity['model_sha256']!=record['model_sha256'] or identity['elf_sha256']!=record['elf_sha256'] or identity['preparation_sha256']!=spec.sha(prepared/'preparation.json'):
        raise ValueError('VM accepted run is from another preparation/model')
    configured=dict(target=spec.target(index),model=record['model'],model_sha256=record['model_sha256'])
    for phase in ('before','after'):
        if json.loads((directory/('configured-model-'+phase+'.json')).read_text())!=configured:
            raise ValueError('Accepted test configured another model')
    actual=dict(directory=str(directory),elf_sha256=row['elf_sha256'],model_sha256=record['model_sha256'],
        log_sha256=spec.sha(directory/'test.log'),xml_sha256=spec.sha(directory/'test.xml'),
        status_sha256=spec.sha(directory/'test-status.json'),preparation_sha256=identity['preparation_sha256'],
        identity_sha256=spec.sha(directory/'preparation-identity.json'),
        configured_before_sha256=spec.sha(directory/'configured-model-before.json'),
        configured_after_sha256=spec.sha(directory/'configured-model-after.json'))
    if proof!=actual:raise ValueError('Candidate VM probe/case evidence changed')
    return actual


def checked_probe(prepared,record,packet):return checked_run_proof(prepared,record,packet,4)


def checked_case(prepared,record,packet,index):
    proof=checked_run_proof(prepared,record,packet,index)
    probe=checked_probe(prepared,record,packet)
    actual=json.loads((Path(proof['directory'])/'candidate-probe-evidence.json').read_text())
    if actual!=probe:raise ValueError('Accepted case no longer matches its candidate probe')
    return proof


def run_vm(prepared,index,timeout):
    record,packet,source,study=checked_preparation(prepared);prepared=Path(prepared).resolve()
    proof=None if index==4 else checked_probe(prepared,record,packet)
    if (prepared/proof_name(index)).exists():
        if index==4:checked_probe(prepared,record,packet)
        else:checked_case(prepared,record,packet,index)
        raise ValueError('This preparation already has a valid probe/case; use sequence to reuse evidence, or a NEW preparation for an intentional rerun')
    configured_model=checked_configured_model(study,source,record,index)
    runs=prepared/'runs';runs.mkdir(exist_ok=True)
    directory=Path(tempfile.mkdtemp(prefix='probe.' if index==4 else 'case'+str(index)+'.',dir=runs))
    write(directory/'preparation-identity.json',dict(preparation_sha256=spec.sha(prepared/'preparation.json'),
        model_sha256=record['model_sha256'],elf_sha256=record['elf_sha256']))
    write(directory/'configured-model-before.json',configured_model)
    if proof:write(directory/'candidate-probe-evidence.json',proof)
    print('[LLM_VME_OPT_VM_RUN_DIRECTORY] '+str(directory),flush=True)
    print('[LLM_VME_OPT_VM_ETA] case='+str(index)+' rough_wall='+spec.eta(index)+' excludes_build_needs_VM_calibration',flush=True)
    status=process(bazel(study)+['test',*FLAGS,'--cache_test_results=no','--test_output=all',
        '--test_timeout='+str(timeout),spec.target(index)],source,directory,'test',timeout+120)
    # Preserve the exact Bazel test outputs in this attempt, including failures.
    testdir=source/'bazel-testlogs'/spec.PACKAGE/('opt_'+spec.testcase(index))
    for name in ('test.log','test.xml'):
        path=testdir/name
        if path.is_file():
            destination=directory/name if name!='test.log' else directory/'bazel-test.log'
            with destination.open('xb') as f:f.write(path.read_bytes())
    # Validation uses the raw child test log, not the parent's combined console.
    if (directory/'bazel-test.log').is_file():
        (directory/'test.log').rename(directory/'bazel-console.log')
        (directory/'bazel-test.log').rename(directory/'test.log')
    if status['exit_code'] or status['timed_out']:raise ValueError('VM simulation failed/incomplete; preserved '+str(directory))
    row,comparison,timing=checked_results(directory,packet,index)
    checked_preparation(prepared)
    after=checked_configured_model(study,source,record,index)
    if after!=configured_model:raise ValueError('Configured model changed during VM test')
    write(directory/'configured-model-after.json',after)
    if proof and checked_probe(prepared,record,packet)!=proof:raise ValueError('Probe evidence changed during VM test')
    write(directory/'result.json',dict(observation=row,comparison=comparison,timing=timing,
        log_sha256=spec.sha(directory/'test.log'),xml_sha256=spec.sha(directory/'test.xml'),
        status_sha256=spec.sha(directory/'test-status.json'),elf_sha256=record['elf_sha256'],model_sha256=record['model_sha256']))
    write(prepared/proof_name(index),dict(directory=str(directory),elf_sha256=row['elf_sha256'],model_sha256=record['model_sha256'],
        log_sha256=spec.sha(directory/'test.log'),xml_sha256=spec.sha(directory/'test.xml'),
        status_sha256=spec.sha(directory/'test-status.json'),preparation_sha256=spec.sha(prepared/'preparation.json'),
        identity_sha256=spec.sha(directory/'preparation-identity.json'),
        configured_before_sha256=spec.sha(directory/'configured-model-before.json'),
        configured_after_sha256=spec.sha(directory/'configured-model-after.json')))
    print('[LLM_VME_OPT_VM_COMPARISON] '+json.dumps(comparison,sort_keys=True),flush=True)
    print('[LLM_VME_OPT_VM_'+('PROBE_PASS' if index==4 else 'RTL_PASS')+'] results='+str(directory),flush=True)
    return directory


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('prepare','check','run','sequence'));p.add_argument('--prepared',type=Path,required=True)
    p.add_argument('--study',type=Path);p.add_argument('--source',type=Path)
    p.add_argument('--case',type=int,choices=range(5),default=4);p.add_argument('--timeout',type=int,default=3600)
    p.add_argument('--plan',choices=('quick','all'),default='quick');p.add_argument('--allow-rtl-simulation',action='store_true')
    a=p.parse_args()
    if not 1<=a.timeout<=5400:p.error('VM per-case timeout must be 1..5400 seconds; limit is NOT ETA')
    if a.command=='prepare':
        if a.study is None or a.source is None:p.error('prepare requires --study and --source')
        prepare_vm(a.study.resolve(strict=True),a.source.resolve(strict=True),a.prepared);return
    if a.command=='check':checked_preparation(a.prepared);print('[LLM_VME_OPT_VM_CHECK] simulation=NOT_RUN');return
    if not a.allow_rtl_simulation:p.error('Explicit --allow-rtl-simulation required; preparation NEVER runs RTL')
    if a.command=='run':run_vm(a.prepared,a.case,a.timeout);return
    sequence=(4,1) if a.plan=='quick' else (4,0,1,2,3)
    for index in sequence:
        if (a.prepared/proof_name(index)).exists():
            record,packet,_,_=checked_preparation(a.prepared)
            if index==4:checked_probe(a.prepared.resolve(),record,packet)
            else:checked_case(a.prepared.resolve(),record,packet,index)
            print('[LLM_VME_OPT_VM_CASE_REUSED] case='+str(index)+' previously accepted same preparation; NOT rerun',flush=True);continue
        run_vm(a.prepared,index,a.timeout)
    print('[LLM_VME_OPT_VM_PLAN_PASS] plan='+a.plan+' full_model=NOT_RUN',flush=True)


if __name__=='__main__':
    try:main()
    except Exception as error:print('[LLM_VME_OPT_VM_STOP] '+str(error),file=sys.stderr);sys.exit(1)
