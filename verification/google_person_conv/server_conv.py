#!/usr/bin/env python3
"""Single-case Conv cycle comparison, using the qualified existing RTL model."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
import conv_contract
import audit_conv
sha=conv_contract.sha
HELPER_SHA="3d6753e12b348d8816ca377156233f9ce0b544c773ece8b4376e54b1b78d8d7e"
MARKER="[PERSON_CONV_RTL_OBSERVATION] "


def helper():
    path=HERE/"qualified_model.py"
    if not path.is_file():path=HERE.parent/"google_person_pool/model_runner.py"
    if sha(path)!=HELPER_SHA:raise ValueError("Qualified read-only model checker changed")
    spec=importlib.util.spec_from_file_location("_conv_qualified_model",path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def load_packet(root):
    root=Path(root).resolve(strict=True);manifest=conv_contract.verify(root)
    data=(root/"conv_program.elf").read_bytes();report=audit_conv.inspect(data)
    if report!=json.loads((root/"resources.json").read_text()):raise ValueError("Small ELF/report changed")
    linked=conv_contract.layout(data,manifest["cases"])
    if linked!=json.loads((root/"layout.json").read_text()):raise ValueError("ELF fixture addresses/bytes changed")
    native=audit_conv.checked_host((root/"host-test.log").read_text(),manifest["cases"])
    if native!=json.loads((root/"host-signatures.json").read_text()):raise ValueError("Native Conv signature evidence changed")
    source=json.loads((root/"candidate-manifest.json").read_text())
    if source["cases"]!=manifest["cases"] or source["scope"]!=manifest["timing_scope"]:
        raise ValueError("Source manifest differs")
    for n,digest in source["files"].items():
        if sha(root/"source"/Path(n).name)!=digest:raise ValueError("Source snapshot changed")
    return SimpleNamespace(root=root,manifest=manifest,report=report,layout=linked,native=native)


def commands_per_case(case):return 4*((case["M"]+15)//16)*((case["N"]+15)//16)*((case["K"]+3)//4)


def checked_results(text,xml,packet,rtl,case_id,cycles):
    tree=ET.parse(xml).getroot();tests=list(tree.iter("testcase"))
    if len(tests)!=1 or tests[0].get("name")!="conv_rtl_test" or any(list(tree.iter(n)) for n in ("failure","error","skipped")):
        raise ValueError("Missing/failed/skipped Conv testcase")
    row=helper().json_row(text,MARKER);case=packet.manifest["cases"][case_id];gold=packet.native[case["name"]]
    expected=dict(schema=1,scope=conv_contract.SCOPE,case_id=case_id,case=case["name"],M=case["M"],K=case["K"],N=case["N"],
        useful_macs_per_call=case["useful_macs"],elf_sha256=packet.manifest["elf_sha256"],rtl_sha256=rtl.manifest["rtl_sha256"],
        source_model_sha256=packet.manifest["source_model_sha256"],derived_model_sha256=case["derived_model_sha256"],
        input_sha256=case["input_sha256"],fixture_model_readback_equal=True,input_readback_equal=True,
        itcm_kib=256,dtcm_kib=512,fault=False,natural_halt=True,firmware_status=3,stack_low_canary_intact=True,
        requested_cycles=cycles,cases=1,checked=gold["checked_elements"],signature=gold["signature"],mismatches=0,
        commands=commands_per_case(case),vme_calls=4,vme_fallbacks=0,vme_mismatches=0,vme_internal_validations=0,
        vme_commands=commands_per_case(case))
    if any(type(row.get(n)) is not type(v) or row.get(n)!=v for n,v in expected.items()):
        raise ValueError("Wrong Conv identity, incomplete/incorrect comparison or safety checks: "+str(row))
    elapsed=row.get("observation_elapsed_cycles");empty=row.get("empty_boundary_cycles")
    if type(elapsed) is not int or not 0<elapsed<=cycles+1 or type(empty) is not int or not 0<empty<=elapsed:
        raise ValueError("Invalid cycle observation/boundary")
    arrays=[]
    for n in ("reference_cycles","vme_cycles"):
        values=row.get(n)
        if not isinstance(values,list) or len(values)!=4 or any(type(v) is not int or not empty<=v<=elapsed for v in values):
            raise ValueError("Missing/invalid first+three steady cycle samples")
        arrays.append(values)
    if sum(map(sum,arrays))>elapsed:raise ValueError("Reported kernel windows exceed total observation")
    for n in ("arena_used_reference","arena_used_vme"):
        if type(row.get(n)) is not int or not 0<row[n]<=65536:raise ValueError("Invalid isolated interpreter arena")
    return row


def summary(row):
    reference,vme=row["reference_cycles"],row["vme_cycles"]
    return dict(case=row["case"],M=row["M"],K=row["K"],N=row["N"],
        first_reference_cycles=reference[0],first_vme_cycles=vme[0],first_ref_over_vme=reference[0]/vme[0],
        steady_reference_cycles=reference[1:],steady_vme_cycles=vme[1:],
        steady_reference_median=statistics.median(reference[1:]),steady_vme_median=statistics.median(vme[1:]),
        steady_ref_over_vme=sum(reference[1:])/sum(vme[1:]),empty_boundary_cycles=row["empty_boundary_cycles"],
        speedup_scope="single_op_spatial_fragment_not_full_layer_or_model",raw_cycles_not_boundary_subtracted=True)


def execute(packet,rtl,env,base,run,model,args):
    argv=[sys.executable,"-u","-B",str(Path(__file__).resolve()),"--packet",str(packet.root),
        "--rtl-package",str(rtl.root),"_test","--case",str(args.case),"--cycles",str(args.cycles),
        "--directory",str(run),"--model-dir",str(model)]
    base.write_json(run/"_test-command.json",argv)
    child=base.child_environment(rtl,env)
    child.update(CONV_CHILD="1",CONV_PACKET=str(packet.root),CONV_CASE=str(args.case),CONV_CYCLES=str(args.cycles),
        PYTHONPATH=os.pathsep.join((str(HERE),str(packet.root),str(rtl.root),str(rtl.root/"python"))))
    start=time.monotonic();timed_out=False;log=run/"_test.log"
    with log.open("xb") as stream:
        process=subprocess.Popen(argv,stdout=stream,stderr=subprocess.STDOUT,env=child,start_new_session=True)
        try:code=process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
            try:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=10)
            except ProcessLookupError:pass
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL)
            code=process.wait()
    timing=dict(argv=argv,elapsed_seconds=time.monotonic()-start,exit_code=code,timed_out=timed_out,
        timeout_seconds=args.timeout,log=str(log))
    base.write_json(run/"_test-status.json",timing)
    if code or timed_out:raise ValueError("Conv simulation failed/incomplete; preserved log: "+str(log))
    return timing


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--packet",type=Path,required=True);p.add_argument("--rtl-package",type=Path,required=True)
    p.add_argument("command",choices=("check","run","_test"));p.add_argument("--case",type=int,choices=range(5),default=0)
    p.add_argument("--cycles",type=int,default=2000000);p.add_argument("--timeout",type=int,default=1800)
    for n in ("probe-run","directory","model-dir"):p.add_argument("--"+n,type=Path)
    a=p.parse_args()
    if not 1000<=a.cycles<=100000000 or not 1<=a.timeout<=86400:p.error("Invalid cycle/time limits")
    packet=load_packet(a.packet);qualified=helper()
    producer,base,common,rtl=qualified.load_runtime(a.rtl_package);env=base.environment(common)
    if a.command=="_test":
        if os.environ.get("CONV_CHILD")!="1" or a.directory is None or a.model_dir is None:raise ValueError("Internal phase needs parent")
        from cocotb_tools.runner import get_runner
        get_runner("verilator").test(hdl_toplevel=rtl.manifest["hdl_top"],hdl_toplevel_lang="verilog",
            test_module="conv_rtl_bench",testcase="conv_rtl_test",seed=137,build_dir=a.model_dir,test_dir=a.directory,
            waves=False,gui=False,results_xml=str(a.directory/"results.xml"))
        return
    if a.probe_run is None:p.error("check/run requires the qualified Pool --probe-run")
    if packet.root==rtl.root or packet.root.is_relative_to(rtl.root):raise ValueError("Small packet must be outside original RTL package")
    with common.state_lock(common.state_directory(rtl.root)):
        build,model=qualified.checked_build(rtl,env,common)
        proof=qualified.checked_probe(a.probe_run,producer,rtl,build,common)
        print("[PERSON_CONV_MODEL_REUSED_READ_ONLY] "+str(model),flush=True)
        if a.command=="check":
            print("[PERSON_CONV_READY] case="+str(a.case)+" full_model=NOT_RUN NPU_RTL=NOT_RUN");return
        state=Path(str(packet.root)+"_runtime");(state/"runs").mkdir(parents=True,exist_ok=True)
        run=Path(tempfile.mkdtemp(prefix="case"+str(a.case)+".",dir=state/"runs"))
        tools={n:sha(HERE/n) for n in ("server_conv.py","conv_rtl_bench.py")}
        for n,v in (("environment.json",env),("producer-build-record.json",build),("probe-evidence.json",proof),("adapter.json",tools)):
            base.write_json(run/n,v)
        print("[PERSON_CONV_RUN_DIRECTORY] "+str(run),flush=True)
        timing=execute(packet,rtl,env,base,run,model,a)
        row=checked_results((run/"_test.log").read_text(),run/"results.xml",packet,rtl,a.case,a.cycles)
        conv_contract.verify(packet.root);rtl.library.verify(rtl.root)
        final_record,final_model=qualified.checked_build(rtl,env,common)
        if final_record!=build or final_model!=model or tools!={n:sha(HERE/n) for n in tools}:raise ValueError("Model/adapter changed during test")
        comparison=summary(row)
        base.write_json(run/"result.json",dict(observation=row,comparison=comparison,timing=timing,producer_build=build,probe=proof,
            packet_manifest_sha256=sha(packet.root/"manifest.json"),rtl_manifest_sha256=sha(rtl.root/"manifest.json"),
            raw_log_sha256=sha(run/"_test.log"),xml_sha256=sha(run/"results.xml"),adapter=tools))
        print(MARKER+json.dumps(row,sort_keys=True))
        print("[PERSON_CONV_CYCLE_COMPARISON] "+json.dumps(comparison,sort_keys=True))
        print("[PERSON_CONV_RTL_PASS] full_model=NOT_RUN wall_seconds="+str(round(timing["elapsed_seconds"],3))+" results="+str(run))


if __name__=="__main__":
    try:main()
    except Exception as error:
        print("[PERSON_CONV_STOP] "+str(error),file=sys.stderr);sys.exit(1)
