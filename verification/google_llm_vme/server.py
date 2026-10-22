#!/usr/bin/env python3
"""One selected RVV/VME case, using the original qualified Pool model read-only."""
import argparse
import importlib.util
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
import lv_packet
HERE=Path(__file__).resolve().parent


def helper(root):
    p=root/'qualified_model.py'
    if spec.sha(p)!=spec.QUALIFIED_SHA:raise ValueError('Qualified model checker changed')
    s=importlib.util.spec_from_file_location('_lv_qualified_model',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def checked_results(run,packet,index):
    timing=json.loads((run/'_test-status.json').read_text())
    if type(timing.get('exit_code')) is not int or timing['exit_code']!=0 or timing.get('timed_out') is not False:
        raise ValueError('Test process failed/timed out')
    tree=ET.parse(run/'results.xml').getroot();tests=list(tree.iter('testcase'))
    if len(tests)!=1 or tests[0].get('name')!='llm_vme_linear_test' or any(list(tree.iter(n)) for n in ('failure','error','skipped')):
        raise ValueError('Missing/failed/skipped RVV/VME testcase')
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',(run/'_test.log').read_text())
    summaries=re.findall(r'TESTS=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)\s+SKIP=(\d+)',text)
    if not summaries or summaries[-1]!=('1','1','0','0'):raise ValueError('Missing Cocotb regression PASS')
    row=helper(packet.root).json_row(text,spec.MARKER);comparison=spec.accept(row,index)
    if row['elf_sha256']!=packet.report['elf_sha256']:raise ValueError('Wrong executed ELF')
    return row,comparison,timing


def execute(packet,rtl,env,base,run,model,index,timeout):
    argv=[sys.executable,'-u','-B',str(HERE/'server.py'),'--packet',str(packet.root),'--rtl-package',str(rtl.root),
        '_test','--case',str(index),'--directory',str(run),'--model-dir',str(model)]
    base.write_json(run/'_test-command.json',argv)
    child=base.child_environment(rtl,env)
    child.update(LV_CHILD='1',LV_PACKET=str(packet.root),LV_CASE=str(index),PYTHONDONTWRITEBYTECODE='1',
        PYTHONPATH=os.pathsep.join((str(packet.root),str(rtl.root),str(rtl.root/'python'))))
    for name in ('WAVES','GUI','COCOTB_ENABLE_PROFILING','COCOTB_TEST_FILTER','COCOTB_TESTCASE'):child.pop(name,None)
    start=time.monotonic();timed_out=False
    with (run/'_test.log').open('xb') as stream:
        process=subprocess.Popen(argv,stdout=stream,stderr=subprocess.STDOUT,env=child,start_new_session=True)
        try:code=process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired,KeyboardInterrupt) as error:
            timed_out=isinstance(error,subprocess.TimeoutExpired)
            try:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=10)
            except ProcessLookupError:pass
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL)
            code=process.wait()
            if not timed_out:code=130
    timing=dict(argv=argv,elapsed_seconds=time.monotonic()-start,exit_code=code,timed_out=timed_out,
        timeout_seconds=timeout,log=str(run/'_test.log'))
    base.write_json(run/'_test-status.json',timing)
    if code or timed_out:raise ValueError('Simulation failed/incomplete; log preserved: '+str(run/'_test.log'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--packet',type=Path,required=True);p.add_argument('--rtl-package',type=Path,required=True)
    p.add_argument('command',choices=('check','run','_test'));p.add_argument('--case',type=int,choices=range(4),default=0)
    p.add_argument('--timeout',type=int,default=5400)
    for n in ('probe-run','directory','model-dir'):p.add_argument('--'+n,type=Path)
    a=p.parse_args()
    if not 1<=a.timeout<=86400:p.error('Invalid timeout')
    packet=lv_packet.load(a.packet)
    if HERE!=packet.root:raise ValueError('Run server.py from the immutable packet')
    q=helper(packet.root);producer,base,common,rtl=q.load_runtime(a.rtl_package);env=base.environment(common)
    if rtl.manifest['rtl_sha256']!=spec.RTL_SHA:raise ValueError('Wrong qualified hardware')
    if a.command=='_test':
        if os.environ.get('LV_CHILD')!='1' or a.directory is None or a.model_dir is None:raise ValueError('Internal phase needs parent')
        from cocotb_tools.runner import get_runner
        get_runner('verilator').test(hdl_toplevel=spec.TOP,hdl_toplevel_lang='verilog',test_module='lv_bench',
            testcase='llm_vme_linear_test',seed=137,build_dir=a.model_dir,test_dir=a.directory,
            waves=False,gui=False,results_xml=str(a.directory/'results.xml'));return
    if a.probe_run is None:p.error('Requires original qualified Pool --probe-run')
    if packet.root==rtl.root or packet.root.is_relative_to(rtl.root):raise ValueError('Keep new packet outside original RTL package')
    with common.state_lock(common.state_directory(rtl.root)):
        build,model=q.checked_build(rtl,env,common);proof=q.checked_probe(a.probe_run,producer,rtl,build,common)
        print('[LLM_VME_MODEL_REUSED_READ_ONLY] '+str(model),flush=True)
        if a.command=='check':print('[LLM_VME_SERVER_READY] hardware=NOT_RUN');return
        state=Path(str(packet.root)+'_runtime');(state/'runs').mkdir(parents=True,exist_ok=True)
        run=Path(tempfile.mkdtemp(prefix='case'+str(a.case)+'.',dir=state/'runs'))
        for n,v in (('environment.json',env),('producer-build-record.json',build),('probe-evidence.json',proof)):
            base.write_json(run/n,v)
        print('[LLM_VME_RUN_DIRECTORY] '+str(run),flush=True)
        execute(packet,rtl,env,base,run,model,a.case,a.timeout)
        row,comparison,timing=checked_results(run,packet,a.case)
        lv_packet.load(packet.root);rtl.library.verify(rtl.root)
        final,final_model=q.checked_build(rtl,env,common)
        if final!=build or final_model!=model:raise ValueError('Original model changed during run')
        base.write_json(run/'result.json',dict(observation=row,comparison=comparison,timing=timing,producer_build=build,probe=proof,
            packet_manifest_sha256=spec.sha(packet.root/'manifest.json'),rtl_manifest_sha256=spec.sha(rtl.root/'manifest.json'),
            raw_log_sha256=spec.sha(run/'_test.log'),xml_sha256=spec.sha(run/'results.xml'),status_sha256=spec.sha(run/'_test-status.json')))
        print('[LLM_VME_CYCLE_COMPARISON] '+json.dumps(comparison,sort_keys=True))
        print('[LLM_VME_RTL_PASS] full_model=NOT_RUN wall_seconds='+str(round(timing['elapsed_seconds'],3))+' results='+str(run))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('[LLM_VME_STOP] '+str(error),file=sys.stderr);sys.exit(1)
