#!/usr/bin/env python3
"""Serial standalone operator tests; read-only reuse, no Bazel/model build."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

sys.dont_write_bytecode=True
import packet
HERE=Path(__file__).resolve().parent


def helper(root):
    path=root/"qualified_model.py"
    if packet.sha(path)!=packet.HELPER_SHA:raise ValueError("Qualified checker changed")
    return packet.module("_llm_qualified_model",path)


def budget(family,index):return 2000000 if family=="int8" and index==0 else 10000000


def plan(family=None,index=None):
    return [[family,index]] if family is not None else [[f,i] for f,n in (("int8",4),("fp32",17)) for i in range(n)]


def checked_results(directory,bundle,family,index):
    directory=Path(directory)
    timing=json.loads((directory/"_test-status.json").read_text())
    if type(timing.get("exit_code")) is not int or timing["exit_code"]!=0 or timing.get("timed_out") is not False:
        raise ValueError("Simulation process failed/timed out")
    tree=ET.parse(directory/"results.xml").getroot();tests=list(tree.iter("testcase"))
    if len(tests)!=1 or tests[0].get("name")!="server_operator_test" or any(list(tree.iter(n)) for n in ("failure","error","skipped")):
        raise ValueError("Missing/failed/skipped operator testcase")
    spec=bundle.helpers.linear if family=="int8" else bundle.helpers.tx
    text=(directory/"_test.log").read_text()
    # Both the raw regression summary AND the single observation are required.
    spec.checked_log(text,index)
    row=helper(bundle.root).json_row(text,spec.MARKER)
    comparison=spec.accept(row,index)
    if row["elf_sha256"]!=bundle.manifest["firmwares"][family] or row["rtl_sha256"]!=packet.RTL_SHA:
        raise ValueError("Test used different ELF/RTL bytes")
    limit=budget(family,index)
    if row.get("requested_cycles")!=limit or not 0<row["observation_elapsed_cycles"]<=limit+1:
        raise ValueError("Wrong case budget or exhausted observation")
    return dict(family=family,case_id=index,observation=row,comparison=comparison,timing=timing,
        raw_log_sha256=packet.sha(directory/"_test.log"),xml_sha256=packet.sha(directory/"results.xml"),
        status_sha256=packet.sha(directory/"_test-status.json"))


def execute(bundle,rtl,env,base,directory,model,family,index,timeout):
    argv=[sys.executable,"-u","-B",str(HERE/"server_ops.py"),"--packet",str(bundle.root),
        "--rtl-package",str(rtl.root),"_test","--family",family,"--case",str(index),
        "--directory",str(directory),"--model-dir",str(model)]
    base.write_json(directory/"_test-command.json",argv)
    child=base.child_environment(rtl,env)
    child.update(LLM_SERVER_CHILD="1",LLM_PACKET=str(bundle.root),LLM_RTL_PACKAGE=str(rtl.root),
        LLM_FAMILY=family,LLM_CASE=str(index),COCOTB_USE_FRONTDOOR="1",PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=os.pathsep.join((str(bundle.root),str(rtl.root),str(rtl.root/"python"))))
    # Cocotb treats nonempty strings (including '0') as enabled. Never request
    # trace from the existing no-trace model or silently profile a speed run.
    for name in ("WAVES","GUI","COCOTB_ENABLE_PROFILING","COCOTB_TEST_FILTER","COCOTB_TESTCASE"):
        child.pop(name,None)
    start=time.monotonic();timed_out=False
    with (directory/"_test.log").open("xb") as stream:
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
        timeout_seconds=timeout,log=str(directory/"_test.log"))
    base.write_json(directory/"_test-status.json",timing)
    if code or timed_out:raise ValueError("Simulation failed/incomplete; log preserved: "+str(directory/"_test.log"))


def evidence(job,key,bundle):
    item=json.loads((job/"completed"/(key+".json")).read_text())
    name=item["attempt"];packet.safe_name(name)
    directory=(job/"attempts"/name).resolve(strict=True)
    if directory.parent!=(job/"attempts").resolve():raise ValueError("Attempt escaped job")
    saved=json.loads((directory/"result.json").read_text())
    if item["result_sha256"]!=packet.sha(directory/"result.json"):raise ValueError("Completed result changed")
    family,index=item["family"],item["case_id"]
    if key!=family+"_"+str(index):raise ValueError("Completed case selector differs")
    if checked_results(directory,bundle,family,index)!=saved:raise ValueError("Result differs from raw evidence")
    return saved


def summarize(job,bundle,selected):
    rows=[]
    for family,index in selected:
        key=family+"_"+str(index)
        if (job/"completed"/(key+".json")).is_file():rows.append(evidence(job,key,bundle))
    report=dict(schema=1,scope="serial_resident_operator_microbenchmarks_not_LLM_inference",
        completed=len(rows),planned=len(selected),all_pass=len(rows)==len(selected),results=rows)
    (job/"summary.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    lines=["# Server operator results","",f"Validated {len(rows)}/{len(selected)} cases. Full model and VME: NOT RUN.","",
        "| Family | Case | First scalar/RVV | Steady scalar/RVV | Simulation wall (s) |",
        "|---|---|---:|---:|---:|"]
    for row in rows:
        c=row["comparison"]
        lines.append(f'| {row["family"]} | {c["case"]} | {c["first_scalar_over_rvv"]:.4f} | '
            f'{c["steady_scalar_over_rvv"]:.4f} | {row["timing"]["elapsed_seconds"]:.3f} |')
    lines.extend(["","Ratios >1 favor RVV; <1 mean RVV is slower. Raw kernel mcycle, not host wall-time speedup.",
        "Only FP32 matmul uses official Gemma kernels; the other FP32 operators are project baselines.",
        "FP32 exp/tanh remain scalar libm; no claim that all work is vectorized.",""])
    (job/"summary.md").write_text("\n".join(lines),encoding="utf-8")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--packet",type=Path,required=True);p.add_argument("--rtl-package",type=Path,required=True)
    p.add_argument("command",choices=("check","run","all","resume","_test"))
    p.add_argument("--family",choices=("int8","fp32"),default="int8");p.add_argument("--case",type=int,default=0)
    p.add_argument("--timeout",type=int,default=5400)
    for name in ("probe-run","job","directory","model-dir"):p.add_argument("--"+name,type=Path)
    a=p.parse_args()
    if not 0<=a.case<(4 if a.family=="int8" else 17) or not 1<=a.timeout<=86400:p.error("Invalid case/timeout")
    bundle=packet.load(a.packet)
    # Always execute the sealed adapter, not another copy passed different
    # files. This also makes provenance/resume independent of PATH scripts.
    if HERE!=bundle.root:raise ValueError("Run server_ops.py FROM the exported packet")
    qualified=helper(bundle.root)
    producer,base,common,rtl=qualified.load_runtime(a.rtl_package);env=base.environment(common)
    if rtl.manifest["rtl_sha256"]!=packet.RTL_SHA:raise ValueError("Wrong qualified RTL")
    if a.command=="_test":
        if os.environ.get("LLM_SERVER_CHILD")!="1" or a.directory is None or a.model_dir is None:
            raise ValueError("Internal phase requires qualified parent")
        from cocotb_tools.runner import get_runner
        get_runner("verilator").test(hdl_toplevel=packet.TOP,hdl_toplevel_lang="verilog",
            test_module="server_bench",testcase="server_operator_test",seed=137,build_dir=a.model_dir,
            test_dir=a.directory,waves=False,gui=False,results_xml=str(a.directory/"results.xml"))
        return
    if a.probe_run is None:p.error("Requires the original qualified Pool --probe-run")
    if bundle.root==rtl.root or bundle.root.is_relative_to(rtl.root):raise ValueError("Keep packet outside original RTL package")
    state=Path(str(bundle.root)+"_server_runtime");jobs=state/"jobs"
    with common.state_lock(common.state_directory(rtl.root)):
        build,model=qualified.checked_build(rtl,env,common)
        proof=qualified.checked_probe(a.probe_run,producer,rtl,build,common)
        identity=dict(packet_manifest_sha256=packet.sha(bundle.root/"manifest.json"),
            rtl_manifest_sha256=packet.sha(rtl.root/"manifest.json"),environment=env,producer_build=build,probe=proof)
        # Roundtrip normalizes tuples etc exactly as the original producer.
        identity=json.loads(json.dumps(identity))
        print("[LLM_SERVER_MODEL_REUSED_READ_ONLY] "+str(model),flush=True)
        if a.command=="check":print("[LLM_SERVER_READY] cases=21 full_model=NOT_RUN simulation=NOT_RUN");return
        jobs.mkdir(parents=True,exist_ok=True)
        if a.command=="resume":
            if a.job is None:p.error("resume requires --job")
            job=a.job.resolve(strict=True)
            if job.parent!=jobs.resolve():raise ValueError("Resume job outside this packet's private runtime")
            record=json.loads((job/"job.json").read_text())
            if record["identity"]!=identity:raise ValueError("Resume package/model/environment/probe differs")
            selected=record["plan"]
            if selected not in (plan(),*[plan(f,i) for f,n in (("int8",4),("fp32",17)) for i in range(n)]):
                raise ValueError("Changed case plan")
        else:
            if a.job is not None:p.error("--job is for resume only")
            selected=plan(a.family,a.case) if a.command=="run" else plan()
            job=Path(tempfile.mkdtemp(prefix="operators.",dir=jobs))
            (job/"attempts").mkdir();(job/"completed").mkdir()
            base.write_json(job/"job.json",dict(schema=1,identity=identity,plan=selected))
        print("[LLM_SERVER_JOB_DIRECTORY] "+str(job),flush=True)
        summarize(job,bundle,selected)
        for family,index in selected:
            key=family+"_"+str(index)
            if (job/"completed"/(key+".json")).is_file():
                evidence(job,key,bundle);print("[LLM_SERVER_CASE_REVALIDATED] "+key,flush=True);continue
            directory=Path(tempfile.mkdtemp(prefix=key+".",dir=job/"attempts"))
            print("[LLM_SERVER_CASE_START] "+key+" log="+str(directory/"_test.log"),flush=True)
            execute(bundle,rtl,env,base,directory,model,family,index,a.timeout)
            result=checked_results(directory,bundle,family,index)
            packet.load(bundle.root);rtl.library.verify(rtl.root)
            final,final_model=qualified.checked_build(rtl,env,common)
            if final!=build or final_model!=model:raise ValueError("Original compiled model changed during run")
            base.write_json(directory/"result.json",result)
            base.write_json(job/"completed"/(key+".json"),dict(family=family,case_id=index,
                attempt=directory.name,result_sha256=packet.sha(directory/"result.json")))
            summarize(job,bundle,selected)
            print("[LLM_SERVER_CASE_PASS] "+json.dumps(dict(family=family,**result["comparison"]),sort_keys=True),flush=True)
        report=summarize(job,bundle,selected)
        if not report["all_pass"]:raise ValueError("Incomplete suite")
        print("[LLM_SERVER_JOB_PASS] cases="+str(len(selected))+" full_model=NOT_RUN VME=NOT_RUN results="+str(job),flush=True)


if __name__=="__main__":
    try:main()
    except Exception as error:
        print("[LLM_SERVER_STOP] "+str(error),file=sys.stderr);sys.exit(1)
