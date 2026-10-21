"""Serial, explicit, resumable VM operator suite. Not a model inference runner."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from tx_spec import CASES,PACKAGE
import tx_summary

HERE=Path(__file__).resolve().parent
BAZEL_SHA="a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f"


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp():return datetime.now(timezone.utc).isoformat()


def write_state(path,value):
    # Atomic update of this job's own metadata, never old simulation evidence.
    with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=path.parent,prefix="state.",delete=False) as stream:
        json.dump(value,stream,indent=2,allow_nan=False);stream.write("\n");temp=stream.name
    os.replace(temp,path)


def tools_identity():
    files=list(HERE.glob("*.py"))+list(HERE.glob("*.cc"))+list(HERE.glob("*.h"))+list(HERE.glob("*.sh"))
    files+=list(HERE.parent.glob("*.py"))+[HERE.parent/"run.sh",HERE.parent/"run_all.sh"]
    return {str(path.relative_to(HERE.parent)):sha(path) for path in sorted(files)}


def plan(mode):
    if mode=="all":return [("int8",i) for i in range(4)]+[("fp32",i) for i in range(len(CASES))]
    # Representative first cases, plus both causal-mask controls.
    if mode=="smoke":return [("int8",0)]+[("fp32",i) for i in (0,2,5,7,9,10,11,12,13,14,15,16)]
    raise ValueError("Unknown suite mode")


def preflight(study):
    if platform.system()!="Linux" or sys.version_info[:2]!=(3,11):
        raise ValueError("Run with Ubuntu VM coral-matrix Python3.11")
    import importlib.metadata
    importlib.metadata.version("numpy");importlib.metadata.version("pyelftools")
    if sha(study/"bazel-9.1.0")!=BAZEL_SHA:raise ValueError("Bazel checksum mismatch")
    if shutil.disk_usage(study).free<5*1024**3:raise ValueError("Less than 5GiB free disk; inspect before continuing")
    if not (study/"source/tcm_capacity_manifest.json").is_file():raise ValueError("Missing qualified source")


def run_process(argv,cwd,log,timeout=7200):
    start=time.monotonic()
    with log.open("xb") as stream:
        child=subprocess.Popen(argv,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            code=child.wait(timeout=timeout)
        except BaseException:
            # Only the newly created child process group, never other users'
            # jobs or a shared Bazel server. Old evidence is preserved.
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGKILL);child.wait()
            raise
    if code:
        print("\n".join(log.read_text(errors="replace").splitlines()[-60:]),flush=True)
        raise RuntimeError("Command failed; raw log preserved: "+str(log))
    return time.monotonic()-start


def linear_summary(run,index):
    sys.path.insert(0,str(HERE.parent))
    module_spec=importlib.util.spec_from_file_location("_suite_original_linear_summary",HERE.parent/"summarize.py")
    module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
    value=module.summarize(run,index)
    if value!=json.loads((run/"comparison.json").read_text()):raise ValueError("Stored INT8 comparison changed")
    return value


def accepted(record):
    if record.get("status")!="PASS":raise ValueError("Case is not complete")
    run=Path(record["run"])
    if sha(run/"test.log")!=record["test_log_sha256"]:raise ValueError("Completed raw test log changed")
    result=linear_summary(run,record["index"]) if record["family"]=="int8" else tx_summary.summarize(run,record["index"])
    if result!=record["comparison"]:raise ValueError("Completed comparison differs from raw acceptance")
    return result


def collect(job,state):
    expected={family+"_"+str(index):(family,index) for family,index in state["plan"]}
    if not expected or len(expected)!=len(state["plan"]):raise ValueError("Empty/duplicate suite plan")
    rows=[]
    for key,record in state["cases"].items():
        if key not in expected or (record.get("family"),record.get("index"))!=expected[key]:
            raise ValueError("Case outside recorded suite plan")
        if record.get("status")=="PASS":rows.append(dict(family=record["family"],**accepted(record)))
    complete=len(rows)==len(state["plan"])
    report=dict(schema=1,status="ALL_PASS" if complete else "INCOMPLETE",mode=state["mode"],
        expected=len(state["plan"]),passed=len(rows),full_model="NOT_RUN",VME="NOT_RUN",rows=rows)
    # Reports are regenerated from checked raw files, not trusted as test evidence.
    write_state(job/"summary.json",report)
    text=["# LLM operator suite\n", "Status: "+report["status"]+"; "+str(len(rows))+"/"+str(len(state["plan"]))+" passed. Full model / VME: NOT_RUN.\n",
          "| Family | Case | Scalar cycles (first / steady median) | RVV cycles (first / steady median) | Steady scalar/RVV |",
          "|---|---|---:|---:|---:|"]
    for row in rows:
        a,b=row["scalar_cycles"],row["rvv_cycles"]
        text.append("| %s | %s | %d / %d | %d / %d | %.6f |" %
            (row["family"],row["case"],a[0],sorted(a[1:])[1],b[0],sorted(b[1:])[1],row["steady_scalar_over_rvv"]))
    text.extend(["", "Resident synthetic operator calls only, not tokens/s or full inference.",
        "FP32 matmul is pinned official RVV; other FP32 operators are project baselines. Exp/tanh remain scalar libm."])
    (job/"summary.md").write_text("\n".join(text)+"\n",encoding="utf-8")
    return report


def execute_case(job,state,family,index):
    study=Path(state["study"]);source=study/"source"
    console=job/(family+"_"+str(index)+"_"+str(time.time_ns())+".log")
    if family=="int8":
        seconds=run_process(["bash",str(HERE.parent/"run.sh"),str(index),str(study)],source,console)
        hits=re.findall(r"^\[LLM_LINEAR_PASS\].* results=(.+)$",console.read_text(),re.M)
        if len(hits)!=1:raise ValueError("Missing unique INT8 completion marker")
        run=Path(hits[0]).resolve(strict=True)
        if run.parent!=study or not run.name.startswith("llm_linear_c"+str(index)+"."):
            raise ValueError("Unexpected INT8 evidence directory")
        result=linear_summary(run,index)
    else:
        prep=Path(state["fp32_prepare"])
        run=Path(tempfile.mkdtemp(prefix="fp32_"+str(index)+".",dir=job))
        for name in ("probe_program.elf","resources.json","rtl-identity.json"):
            shutil.copyfile(prep/name,run/name)
        bazel=study/"bazel-9.1.0"
        argv=[str(bazel),"--output_user_root="+str(study/"bazel-user"),"--host_jvm_args=-Xmx2g","--noblock_for_lock",
            "test","--noshow_progress","--color=no","--curses=no","--jobs=2","--local_resources=memory=4096",
            "--lockfile_mode=error","--repo_env=CORALNPU_MAKE_JOBS=2","--action_env=LANG=C.UTF-8",
            "--action_env=LC_ALL=C.UTF-8","--cache_test_results=no","--test_output=all","--test_timeout=5400",
            "//"+PACKAGE+":ops_tx_"+CASES[index][0]+"_test"]
        (run/"command.json").write_text(json.dumps(argv,indent=2)+"\n")
        seconds=run_process(argv,source,run/"test.log")
        result=tx_summary.summarize(run,index)
        console.write_text("[LLM_TX_PASS] results="+str(run)+"\n")
    return dict(family=family,index=index,status="PASS",run=str(run),console=str(console),
        command_wall_seconds=seconds,test_log_sha256=sha(run/"test.log"),comparison=result)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study",type=Path,default=Path.home()/"coral_tcm_capacity_8e4_v1")
    p.add_argument("--mode",choices=("all","smoke"),default="all")
    p.add_argument("--prepare-only",action="store_true")
    p.add_argument("--resume",type=Path)
    p.add_argument("--collect",type=Path)
    a=p.parse_args()
    for name in ("WAVES","GUI","COCOTB_ENABLE_PROFILING","COCOTB_TESTCASE","COCOTB_TEST_FILTER"):
        os.environ.pop(name,None)
    if a.collect:
        job=a.collect.resolve(strict=True);state=json.loads((job/"state.json").read_text())
        if state["tools"]!=tools_identity():raise ValueError("Tools changed; do not relabel old evidence")
        report=collect(job,state);print("[LLM_SUITE_REPORT] "+str(job/"summary.md"))
        return 0 if report["status"]=="ALL_PASS" else 2
    study=a.study.resolve(strict=True);preflight(study)
    if a.resume:
        job=a.resume.resolve(strict=True);state=json.loads((job/"state.json").read_text())
        if state["tools"]!=tools_identity() or state["study"]!=str(study):
            raise ValueError("Study/tools changed; preserve old evidence and create a new job")
        if state["plan"]!=[list(x) for x in plan(state["mode"])]:raise ValueError("Job plan changed")
    else:
        job=Path(tempfile.mkdtemp(prefix="llm_suite.",dir=study))
        state=dict(schema=1,created=stamp(),study=str(study),mode=a.mode,tools=tools_identity(),
            plan=[list(x) for x in plan(a.mode)],cases={},status="PREPARING")
        write_state(job/"state.json",state)
    print("[LLM_SUITE_DIRECTORY] "+str(job),flush=True)
    print("[LLM_SUITE_MODE] "+state["mode"]+" cases="+str(len(state["plan"]))+" foreground_serial=true",flush=True)
    import fcntl
    with (job/"job.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            # Re-prepare cached firmware on resume; never resume a stopped CPU.
            log=job/("prepare_"+str(time.time_ns())+".log")
            print("[LLM_SUITE_STAGE] native qualification / cross-link / cached model build; see "+str(log),flush=True)
            run_process(["bash",str(HERE/"prepare_vm.sh"),str(study)],study/"source",log)
            hits=re.findall(r"^\[LLM_TX_BUILD_READY\] RTL=NOT_RUN results=(.+)$",log.read_text(),re.M)
            if len(hits)!=1:raise ValueError("Missing unique build/resource acceptance")
            prep=Path(hits[0]).resolve(strict=True)
            if prep.parent!=study or not prep.name.startswith("llm_tx_prepare."):raise ValueError("Unexpected preparation path")
            identity={name:sha(prep/name) for name in ("probe_program.elf","resources.json","rtl-identity.json")}
            if "fp32_identity" in state and state["fp32_identity"]!=identity:
                raise ValueError("FP32 ELF/RTL changed; do not mix old/new measurements")
            state["fp32_identity"]=identity
            state.pop("error",None)
            state["fp32_prepare"]=str(prep);state["status"]="BUILD_READY";write_state(job/"state.json",state)
            if a.prepare_only:
                print("[LLM_SUITE_BUILD_READY] RTL=NOT_RUN resume="+str(job),flush=True);return 0
            for family,index in state["plan"]:
                key=family+"_"+str(index);old=state["cases"].get(key,{})
                if old.get("status")=="PASS":
                    accepted(old);print("[LLM_SUITE_REVALIDATED] "+key+" raw_evidence_unchanged=true",flush=True);continue
                state["status"]="RUNNING";state["active_case"]=key;write_state(job/"state.json",state)
                print("[LLM_SUITE_CASE_START] "+key+" "+stamp(),flush=True)
                record=execute_case(job,state,family,index);state["cases"][key]=record
                write_state(job/"state.json",state);collect(job,state)
                print("[LLM_SUITE_CASE_PASS] "+key+" steady_scalar_over_rvv="+
                    str(record["comparison"]["steady_scalar_over_rvv"])+" results="+record["run"],flush=True)
            report=collect(job,state)
            if report["status"]!="ALL_PASS":raise ValueError("Suite incomplete")
            state["status"]="ALL_PASS";state["finished"]=stamp();state.pop("active_case",None)
            write_state(job/"state.json",state)
            print("[LLM_SUITE_ALL_PASS] cases="+str(len(state["plan"]))+" full_model=NOT_RUN VME=NOT_RUN report="+str(job/"summary.md"),flush=True)
        except BaseException as error:
            state["status"]="INCOMPLETE";state["error"]=str(error);write_state(job/"state.json",state)
            print("[LLM_SUITE_STOP] "+str(error)+"; all logs preserved; resume="+str(job),flush=True)
            raise
    return 0


if __name__=="__main__":sys.exit(main())
