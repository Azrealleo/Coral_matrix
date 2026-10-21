#!/usr/bin/env python3
"""Standalone short VME RTL probe. Never reports a model inference PASS."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from types import SimpleNamespace

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
import portable_vme
import probe_audit
sha=portable_vme.sha
MARKER="[PERSON_VME_PROBE_OBSERVATION] "
BASE_SHA="597dfe711e95ee9168be7c77b32a39c0ebc02a97444a6fe8fa5025210914593a"


def module_at(name,path,digest):
    if sha(path)!=digest: raise ValueError("Unqualified helper: "+str(path))
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m


def runtime():
    path=HERE/"_baseline_runner.py"
    if not path.exists(): path=HERE.parent/"google_person_detect/person_runner.py"
    return module_at("_qualified_person_environment",path,BASE_SHA)


def load_bundle(root):
    root=Path(root).resolve(strict=True)
    manifest=portable_vme.verify(root)
    base=runtime()
    sys.path.insert(0,str(root))
    for name in ("spec.py","firmware_report.py"):
        if sha(root/name)!=base.PACKAGE_TOOLS[name]: raise ValueError("Changed baseline resource helper")
    spec=module_at("spec",root/"spec.py",base.PACKAGE_TOOLS["spec.py"]);sys.modules["spec"]=spec
    fw=module_at("firmware_report",root/"firmware_report.py",base.PACKAGE_TOOLS["firmware_report.py"])
    sys.modules["firmware_report"]=fw
    source=HERE/"audit.py"
    if not source.exists(): source=HERE/"vme_audit.py"
    audit=module_at("_packaged_vme_audit",root/"vme_audit.py",sha(source))
    reports={}
    for mode in ("probe","validate","fast"):
        data=(root/manifest["firmwares"][mode]["file"]).read_bytes()
        reports[mode]=probe_audit.inspect(data) if mode=="probe" else audit.inspect(data,mode)
        if json.loads((root/"firmware"/mode/"resources.json").read_text())!=reports[mode]:
            raise ValueError("Packaged resource report changed: "+mode)
    for name in spec.ASSETS: spec.checked_asset(root/"assets",name)
    return SimpleNamespace(root=root,manifest=manifest,report=reports["probe"],library=portable_vme)


def checked_results(text,xml,bundle,cycles):
    tree=ET.parse(xml).getroot();tests=list(tree.iter("testcase"))
    if len(tests)!=1 or tests[0].get("name")!="person_vme_probe_test" or any(
            list(tree.iter(tag)) for tag in ("failure","error","skipped")):
        raise ValueError("Missing/failed/skipped probe testcase")
    rows=[json.loads(line.split(MARKER,1)[1]) for line in text.splitlines() if MARKER in line]
    if len(rows)!=1: raise ValueError("Missing/duplicate probe observation")
    row=rows[0]
    required=dict(schema=1,scope="short_VME_arithmetic_not_model_inference",fault=False,natural_halt=True,
        firmware_status=3,requested_cycles=cycles,itcm_kib=256,dtcm_kib=512,
        elf_sha256=bundle.manifest["firmwares"]["probe"]["sha256"],
        rtl_sha256=bundle.manifest["rtl_sha256"],stack_low_canary_intact=True,
        cases=8,checked=840,mismatches=0,commands=233,signature=3016346044)
    if any(type(row.get(k)) is not type(v) or row.get(k)!=v for k,v in required.items()):
        raise ValueError("Probe failed or identity/counters differ: "+str(row))
    elapsed=row.get("observation_elapsed_cycles")
    if type(elapsed) is not int or not 0<=elapsed<=cycles+1: raise ValueError("Probe cycle window invalid")
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package",type=Path,required=True)
    parser.add_argument("command",choices=("verify","check","build","probe","_build","_test"))
    parser.add_argument("--cycles",type=int,default=2000000)
    parser.add_argument("--timeout",type=int,default=1800)
    parser.add_argument("--jobs",type=int,choices=range(1,9),default=2)
    parser.add_argument("--directory",type=Path)
    parser.add_argument("--model-dir",type=Path)
    a=parser.parse_args()
    if not 1000<=a.cycles<=10000000 or not 1<=a.timeout<=86400: parser.error("Invalid cycle/time bound")
    base=runtime(); common=base.helpers(); bundle=load_bundle(a.package)
    if a.command=="verify":
        print("[PERSON_VME_SERVER_PACKAGE_VERIFIED] original_RTL_model=true NPU_RTL=NOT_RUN");return
    env=base.environment(common)
    if a.command=="check":
        print("[PERSON_VME_SERVER_ENV_CHECK] "+json.dumps(dict(python=env["python"],tools=env["tools"],
            versions=env["versions"],NPU_RTL="NOT_RUN")));return
    if a.command in ("_build","_test"):
        if os.environ.get("PERSON_VME_CHILD")!="1": raise ValueError("Internal phase needs parent launcher")
        if a.command=="_build":
            commands=common.build_commands(bundle,env,a.directory,a.jobs)
            base.write_json(a.directory/"compile-commands.json",commands)
            for argv in commands: subprocess.run(argv,cwd=a.directory,check=True)
            if "not found" in common.command_output(["ldd",str(a.directory/bundle.manifest["hdl_top"])]):
                raise ValueError("Unresolved compiled model libraries")
        else:
            from cocotb_tools.runner import get_runner
            get_runner("verilator").test(hdl_toplevel=bundle.manifest["hdl_top"],hdl_toplevel_lang="verilog",
                test_module="probe_bench",testcase="person_vme_probe_test",seed=137,
                build_dir=a.model_dir,test_dir=a.directory,waves=False,gui=False,
                results_xml=str(a.directory/"results.xml"),extra_env=dict(PERSON_CYCLES=str(a.cycles)))
        return
    state=common.state_directory(bundle.root);state.mkdir(parents=True,exist_ok=True)
    identity=common.digest(dict(manifest=sha(bundle.root/"manifest.json"),environment=env,
        server=sha(__file__),bench=sha(HERE/"probe_bench.py"),environment_helper=BASE_SHA,
        warnings=common.WARNINGS,visibility=common.VISIBILITY))

    def current():
        r=json.loads((state/"current_build.json").read_text());p=Path(r["directory"]).resolve(strict=True)
        if (p.parent!=(state/"builds").resolve() or r["identity"]!=identity or
                r["model_files"]!=common.model_hashes(bundle,p) or r["timing"]["exit_code"]!=0 or
                r["timing"]["timed_out"] is not False or r!=json.loads((p/"build-record.json").read_text())):
            raise ValueError("Model/package/tools/environment changed; build a new model")
        return r,p

    def execute(phase,directory,extra):
        argv=[sys.executable,"-B",str(Path(__file__).resolve()),"--package",str(bundle.root),phase,
              "--directory",str(directory)]+list(extra)
        base.write_json(directory/(phase+"-command.json"),argv)
        child=base.child_environment(bundle,env)
        child.update(PERSON_VME_CHILD="1",PYTHONPATH=os.pathsep.join((str(HERE),str(bundle.root),str(bundle.root/"python"))))
        start=time.monotonic();timed_out=False
        log=directory/(phase+".log")
        with log.open("xb") as stream:
            process=subprocess.Popen(argv,stdout=stream,stderr=subprocess.STDOUT,env=child,start_new_session=True)
            try: code=process.wait(timeout=a.timeout)
            except subprocess.TimeoutExpired:
                timed_out=True
                try:
                    os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=10)
                except ProcessLookupError: pass
                except subprocess.TimeoutExpired: os.killpg(process.pid,signal.SIGKILL)
                code=process.wait()
        timing=dict(argv=argv,elapsed_seconds=time.monotonic()-start,exit_code=code,timed_out=timed_out,
                    timeout_seconds=a.timeout,log=str(log))
        base.write_json(directory/(phase+"-status.json"),timing)
        if code or timed_out: raise ValueError("Phase failed/incomplete; preserved log: "+str(log))
        return timing

    with common.state_lock(state):
        if a.command=="build":
            try:
                _,path=current();print("[PERSON_VME_MODEL_REUSED] "+str(path));return
            except (OSError,ValueError,KeyError): pass
            (state/"builds").mkdir(exist_ok=True)
            path=Path(tempfile.mkdtemp(prefix=identity[:12]+".",dir=state/"builds"))
            base.write_json(path/"environment.json",env)
            print("[PERSON_VME_BUILD_DIRECTORY] "+str(path),flush=True)
            timing=execute("_build",path,("--jobs",str(a.jobs)))
            portable_vme.verify(bundle.root)
            record=dict(directory=str(path),identity=identity,timing=timing,model_files=common.model_hashes(bundle,path))
            base.write_json(path/"build-record.json",record)
            pointer=state/("pointer."+str(os.getpid())+".json");base.write_json(pointer,record)
            os.replace(pointer,state/"current_build.json")
            print("[PERSON_VME_BUILD_PASS] compile_seconds="+str(round(timing["elapsed_seconds"],3)));return
        record,model=current();(state/"runs").mkdir(exist_ok=True)
        run=Path(tempfile.mkdtemp(prefix="probe.",dir=state/"runs"))
        base.write_json(run/"environment.json",env);base.write_json(run/"build-record.json",record)
        print("[PERSON_VME_PROBE_RUN_DIRECTORY] "+str(run),flush=True)
        timing=execute("_test",run,("--model-dir",str(model),"--cycles",str(a.cycles)))
        row=checked_results((run/"_test.log").read_text(),run/"results.xml",bundle,a.cycles)
        portable_vme.verify(bundle.root)
        if common.model_hashes(bundle,model)!=record["model_files"]: raise ValueError("Compiled model changed")
        base.write_json(run/"result.json",dict(observation=row,timing=timing,build=record,
            manifest_sha256=sha(bundle.root/"manifest.json"),raw_log_sha256=sha(run/"_test.log"),xml_sha256=sha(run/"results.xml")))
        print(MARKER+json.dumps(row,sort_keys=True))
        print("[PERSON_VME_HARDWARE_PROBE_PASS] full_model_inference=NOT_RUN wall_seconds="+
              str(round(timing["elapsed_seconds"],3))+" results="+str(run))


if __name__=="__main__":
    try: main()
    except Exception as error:
        print("[PERSON_VME_PROBE_STOP] "+str(error),file=sys.stderr);sys.exit(1)
