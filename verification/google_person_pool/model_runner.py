#!/usr/bin/env python3
"""External complete-model runner; read-only reuse of the qualified Pool model."""
import argparse
import hashlib
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
HERE=Path(__file__).resolve().parent
MARKER="[PERSON_POOL_MODEL_OBSERVATION] "
BACKEND="VME_pointwise_RVV_average_pool_reference_other_ops"
BASE_SHA="597dfe711e95ee9168be7c77b32a39c0ebc02a97444a6fe8fa5025210914593a"
PRODUCER_SHA="c510ebcc18dacbcbbb16d07b02a9b4aa14c14bd2756dd2e6251bc3f8fc70eb0d"
PROBE_BENCH_SHA="cf3f016464bb62a3b14d8edcc990f6181b0de5a084798b7aa34ddc6b566b1273"
FIRMWARE_SHA={
    "probe":"031cf12303fb5fe8d75a88d72f0aee2a3453c54d0ba70446f95f35cba3a009cb",
    "validate":"8137e2bf8777f5e0976a49887302724c64f27d491c886f14ec673d535eac0951",
    "fast":"81f596bd9eb0fa94ef3fcdfb0cb33719e5e00cad949207b7600b91f7481253f8"}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_module(name,path,digest):
    if sha(path)!=digest:raise ValueError("Unqualified/changed helper: "+str(path))
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def load_runtime(package):
    root=Path(package).resolve(strict=True)
    if sha(root/"probe_bench.py")!=PROBE_BENCH_SHA:raise ValueError("Unqualified probe bench")
    sys.path.insert(0,str(root))
    producer=load_module("_pool_qualified_model_producer",root/"server_probe.py",PRODUCER_SHA)
    base=producer.runtime();common=base.helpers();bundle=producer.load_bundle(root)
    if ({mode:item["sha256"] for mode,item in bundle.manifest["firmwares"].items()}!=FIRMWARE_SHA or
        bundle.manifest["rtl_sha256"]!="477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2"):
        raise ValueError("Not the measured Pool ELFs/original probed RTL")
    return producer,base,common,bundle


def selected_report(bundle,variant):
    # load_runtime has freshly re-audited ALL packaged ELFs against these files.
    report=json.loads((bundle.root/"firmware"/variant/"resources.json").read_text())
    if report["elf_sha256"]!=FIRMWARE_SHA[variant] or report["kernel_backend"]!=BACKEND:
        raise ValueError("Wrong selected ELF audit")
    return report


def checked_build(bundle,env,common):
    """Verify original producer identity, recipe and binary; never relabel it."""
    state=common.state_directory(bundle.root)
    record=json.loads((state/"current_build.json").read_text())
    model=Path(record["directory"]).resolve(strict=True)
    wanted=common.digest(dict(manifest=sha(bundle.root/"manifest.json"),environment=env,
        server=PRODUCER_SHA,bench=PROBE_BENCH_SHA,environment_helper=BASE_SHA,
        warnings=common.WARNINGS,visibility=common.VISIBILITY))
    if (model.parent!=(state/"builds").resolve() or record["identity"]!=wanted or
        record!=json.loads((model/"build-record.json").read_text()) or
        record["timing"]["exit_code"]!=0 or record["timing"]["timed_out"] is not False or
        record["model_files"]!=common.model_hashes(bundle,model) or
        json.loads((model/"environment.json").read_text())!=json.loads(json.dumps(env))):
        raise ValueError("Original model/package/environment/build record differs; nothing changed")
    recipe=json.loads((model/"compile-commands.json").read_text())
    if not isinstance(recipe,list) or len(recipe)!=2 or not isinstance(recipe[1],list):
        raise ValueError("Invalid original build recipe")
    make=recipe[1]
    if len(make)<3 or make[1]!="-j" or make[2] not in tuple(map(str,range(1,9))):
        raise ValueError("Unexpected original compile job count")
    expected=common.build_commands(bundle,env,model,int(make[2]),write_visibility=False)
    if recipe!=expected or (model/"visibility.vlt").read_text()!=common.VISIBILITY.format(top=bundle.manifest["hdl_top"]):
        raise ValueError("Original compile recipe/visibility changed")
    return record,model


def passed_timing(timing):
    if type(timing.get("exit_code")) is not int or timing["exit_code"]!=0 or timing.get("timed_out") is not False:
        raise ValueError("Prerequisite simulation failed/timed out")


def checked_probe(directory,producer,bundle,build,common):
    directory=Path(directory).resolve(strict=True)
    state=common.state_directory(bundle.root).resolve()
    if directory.parent!=(state/"runs").resolve():raise ValueError("Probe is not from this package's private state")
    result=json.loads((directory/"result.json").read_text())
    passed_timing(result["timing"])
    if (result["manifest_sha256"]!=sha(bundle.root/"manifest.json") or result["build"]!=build or
        result["raw_log_sha256"]!=sha(directory/"_test.log") or result["xml_sha256"]!=sha(directory/"results.xml")):
        raise ValueError("Probe evidence/package/build changed")
    row=result["observation"]
    checked=producer.checked_results((directory/"_test.log").read_text(),directory/"results.xml",bundle,row["requested_cycles"])
    if row!=checked:raise ValueError("Probe observation differs from raw evidence")
    return dict(directory=str(directory),result_sha256=sha(directory/"result.json"),observation=row)


def json_row(text,marker):
    # Strip terminal colour control sequences only, not arbitrary trailing data.
    text=re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]","",text)
    rows=[json.loads(line.split(marker,1)[1]) for line in text.splitlines() if marker in line]
    if len(rows)!=1:raise ValueError("Missing/duplicate full-model observation")
    return rows[0]


def checked_results(text,xml,bundle,variant,case,cycles):
    tree=ET.parse(xml).getroot();tests=list(tree.iter("testcase"))
    if len(tests)!=1 or tests[0].get("name")!="person_pool_model_test" or any(
        list(tree.iter(n)) for n in ("failure","error","skipped")):
        raise ValueError("Missing/failed/skipped full-model testcase")
    row=json_row(text,MARKER)
    required=dict(schema=1,variant=variant,case=case,scope="complete_original_model_single_image",
        requested_cycles=cycles,itcm_kib=256,dtcm_kib=512,fault=False,natural_halt=True,
        firmware_status=3,inference_complete=True,model_readback_equal=True,input_readback_equal=True,
        stack_low_canary_intact=True,elf_sha256=bundle.manifest["firmwares"][variant]["sha256"],
        model_sha256=bundle.manifest["model_sha256"],rtl_sha256=bundle.manifest["rtl_sha256"],
        input_sha256=sha(bundle.root/"inputs"/(case+".int8.bin")),kernel_backend=BACKEND,
        depthwise="official_default_registration_unchanged",validation_executes_reference=(variant=="validate"),
        performance_eligible=(variant=="fast"),scores_no_person_then_person=bundle.manifest["reference_scores_no_person_then_person"][case])
    if any(type(row.get(k)) is not type(v) or row.get(k)!=v for k,v in required.items()):
        raise ValueError("Wrong model identity, incomplete inference, scores, or safety checks: "+str(row))
    used,invoke,elapsed=(row.get(n) for n in ("arena_used_bytes","invoke_cycles","observation_elapsed_cycles"))
    if (type(used) is not int or not 0<used<=163840 or type(invoke) is not int or not 0<invoke<=cycles or
        type(elapsed) is not int or not invoke<=elapsed<=cycles+1):
        raise ValueError("Invalid arena/cycle measurement")
    counters=row.get("counters")
    expected=dict(pd_vme_conv_calls=14,pd_vme_fallback_calls=0,pd_vme_mismatches=0,
        pd_pool_calls=1,pd_pool_fallbacks=0,pd_pool_mismatches=0,pd_pool_vector_blocks=16)
    if variant=="validate":expected.update(pd_vme_validated_layers=14,pd_pool_validated=1,pd_vme_first_bad_index=0xffffffff)
    if not isinstance(counters,dict) or any(type(counters.get(n)) is not int or counters[n]!=v for n,v in expected.items()):
        raise ValueError("Optimized paths incomplete/fallback/mismatched; NOT PASS")
    if type(counters.get("pd_vme_commands")) is not int or counters["pd_vme_commands"]<=0:
        raise ValueError("No software VME commands recorded")
    # Speed ELF may retain unused validation counters, but must not execute them.
    if variant=="fast" and any(counters.get(n,0)!=0 for n in ("pd_vme_validated_layers","pd_pool_validated")):
        raise ValueError("Speed ELF unexpectedly executed reference validation")
    return row


def checked_validation(directory,bundle,case,build):
    directory=Path(directory).resolve(strict=True)
    expected=Path(str(bundle.root)+"_model_runtime").resolve()
    if directory.parent!=expected/"runs":raise ValueError("Validation is not from this package's model state")
    result=json.loads((directory/"result.json").read_text());passed_timing(result["timing"])
    if (result.get("producer_build")!=build or result["manifest_sha256"]!=sha(bundle.root/"manifest.json") or
        result["raw_log_sha256"]!=sha(directory/"_test.log") or result["xml_sha256"]!=sha(directory/"results.xml")):
        raise ValueError("Validation evidence changed")
    row=result["observation"]
    checked=checked_results((directory/"_test.log").read_text(),directory/"results.xml",bundle,"validate",case,row["requested_cycles"])
    if row!=checked:raise ValueError("Validation observation differs from raw evidence")
    return dict(directory=str(directory),result_sha256=sha(directory/"result.json"),observation=row)


def execute(bundle,env,base,run,model,args):
    argv=[sys.executable,"-B",str(Path(__file__).resolve()),"--package",str(bundle.root),"_test",
        "--variant",args.variant,"--case",args.case,"--cycles",str(args.cycles),
        "--directory",str(run),"--model-dir",str(model)]
    base.write_json(run/"_test-command.json",argv)
    child=base.child_environment(bundle,env)
    child.update(PERSON_POOL_MODEL_CHILD="1",PERSON_VARIANT=args.variant,PERSON_CASE=args.case,
        PERSON_CYCLES=str(args.cycles),PYTHONPATH=os.pathsep.join((str(HERE),str(bundle.root),str(bundle.root/"python"))))
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
    if code or timed_out:raise ValueError("Inference failed/incomplete; preserved log: "+str(log))
    return timing


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package",type=Path,required=True)
    p.add_argument("command",choices=("check","infer","_test"))
    p.add_argument("--variant",choices=("validate","fast"),default="validate")
    p.add_argument("--case",choices=("person","no_person"),default="person")
    p.add_argument("--cycles",type=int,default=400000000)
    p.add_argument("--timeout",type=int,default=172800)
    for n in ("probe-run","validation-run","directory","model-dir"):p.add_argument("--"+n,type=Path)
    a=p.parse_args()
    if not 1000<=a.cycles<=1000000000 or not 1<=a.timeout<=259200:p.error("Invalid cycle/time bounds")
    producer,base,common,bundle=load_runtime(a.package)
    env=base.environment(common)
    if a.command=="_test":
        if os.environ.get("PERSON_POOL_MODEL_CHILD")!="1" or a.directory is None or a.model_dir is None:
            raise ValueError("Internal phase needs parent launcher")
        from cocotb_tools.runner import get_runner
        get_runner("verilator").test(hdl_toplevel=bundle.manifest["hdl_top"],hdl_toplevel_lang="verilog",
            test_module="model_bench",testcase="person_pool_model_test",seed=137,build_dir=a.model_dir,
            test_dir=a.directory,waves=False,gui=False,results_xml=str(a.directory/"results.xml"))
        return
    if a.probe_run is None:p.error("check/infer requires --probe-run from this qualified Pool build")
    if a.variant=="fast" and a.validation_run is None:p.error("fast requires --validation-run for the same image")
    if HERE==bundle.root or HERE.is_relative_to(bundle.root):raise ValueError("Install adapter outside the immutable package")
    state=common.state_directory(bundle.root)
    # Hold the original producer lock, without modifying its pointer or model.
    with common.state_lock(state):
        build,model=checked_build(bundle,env,common)
        proof=checked_probe(a.probe_run,producer,bundle,build,common)
        validation=checked_validation(a.validation_run,bundle,a.case,build) if a.variant=="fast" else None
        print("[PERSON_POOL_MODEL_REUSED_READ_ONLY] "+str(model),flush=True)
        if a.command=="check":
            print("[PERSON_POOL_MODEL_READY] variant="+a.variant+" case="+a.case+" full_model_inference=NOT_RUN");return
        output=Path(str(bundle.root)+"_model_runtime");(output/"runs").mkdir(parents=True,exist_ok=True)
        run=Path(tempfile.mkdtemp(prefix=a.variant+"_"+a.case+".",dir=output/"runs"))
        adapter={n:sha(HERE/n) for n in ("model_runner.py","model_bench.py")}
        for name,value in (("environment.json",env),("producer-build-record.json",build),
            ("probe-prerequisite.json",proof),("validation-prerequisite.json",validation),("adapter.json",adapter)):
            base.write_json(run/name,value)
        print("[PERSON_POOL_MODEL_RUN_DIRECTORY] "+str(run),flush=True)
        timing=execute(bundle,env,base,run,model,a)
        row=checked_results((run/"_test.log").read_text(),run/"results.xml",bundle,a.variant,a.case,a.cycles)
        bundle.library.verify(bundle.root)
        final_build,final_model=checked_build(bundle,env,common)
        if final_build!=build or final_model!=model or adapter!={n:sha(HERE/n) for n in adapter}:
            raise ValueError("Producer model or adapter changed during inference")
        base.write_json(run/"result.json",dict(schema=1,observation=row,timing=timing,producer_build=build,
            probe=proof,validation=validation,adapter=adapter,manifest_sha256=sha(bundle.root/"manifest.json"),
            raw_log_sha256=sha(run/"_test.log"),xml_sha256=sha(run/"results.xml")))
        print(MARKER+json.dumps(row,sort_keys=True))
        print("[PERSON_POOL_MODEL_INFERENCE_PASS] variant="+a.variant+" performance_eligible="+str(a.variant=="fast").lower()+
            " wall_seconds="+str(round(timing["elapsed_seconds"],3))+" results="+str(run))


if __name__=="__main__":
    try:main()
    except Exception as error:
        print("[PERSON_POOL_MODEL_STOP] "+str(error),file=sys.stderr);sys.exit(1)
