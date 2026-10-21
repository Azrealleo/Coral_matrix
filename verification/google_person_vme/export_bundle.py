"""Export copied exact baseline RTL plus probe/validate/fast ELFs, separately."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile

HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
import audit as candidate_audit
import prepare as candidate
import probe_audit
import portable_vme

PROBE_PACKAGE="tests/cocotb/person_vme_probe_v1"
PROBE_MANIFEST="person_vme_probe_v1_manifest.json"
BASE_RUNNER_SHA="597dfe711e95ee9168be7c77b32a39c0ebc02a97444a6fe8fa5025210914593a"
COMMON_SHA="9031f22eadbfc75d308f2bcd67bde9b943b06822ccbbe8da702b821112273855"


def module_at(name,path,digest):
    if portable_vme.sha(path)!=digest: raise ValueError("Changed pinned helper: "+str(path))
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def checked_host(text):
    expected={"person":"-113,113","no_person":"57,-57"}
    for case,scores in expected.items():
        line="[PERSON_VME_HOST_MODEL_CASE] case="+case+" layers=14 byte_exact=true scores="+scores
        if text.splitlines().count(line)!=1: raise ValueError("Host layer evidence missing/duplicate: "+case)
    rows=re.findall(r"^\[PERSON_VME_HOST_MODEL_PASS\] cases=2 compared_layers=28 arena_used=(\d+) hardware=NOT_RUN$",text,re.M)
    if len(rows)!=1 or not 0<int(rows[0])<=163840 or re.search(r"\bFAILED\b|^FAIL[: ]",text,re.M):
        raise ValueError("Incomplete/failed native host evidence")
    return dict(cases=2,compared_layers=28,arena_used_bytes=int(rows[0]),hardware="NOT_RUN")


def evidence(root,assets,run,baseline):
    identity=candidate.prepare(root,assets)
    if json.loads((run/"manifest.json").read_text())!=identity: raise ValueError("Candidate run identity changed")
    host=checked_host((run/"host-test.log").read_text())
    reports={}
    for mode in ("validate","fast"):
        data=(run/mode/"person_program.elf").read_bytes()
        reports[mode]=candidate_audit.inspect(data,mode)
        if json.loads((run/mode/"resources.json").read_text())!=reports[mode]:
            raise ValueError("Candidate ELF/resource report changed: "+mode)
    producer=module_at("_vme_default_package_checker",HERE.parent/"google_person_detect/person_runner.py",BASE_RUNNER_SHA)
    base=producer.load_bundle(baseline)
    if base.manifest["reference_scores_no_person_then_person"]!={"person":[-113,113],"no_person":[57,-57]}:
        raise ValueError("Original reference scores differ")
    return identity,host,reports,base


def probe_files():
    build='''load("//rules:coralnpu_v2.bzl", "coralnpu_v2_binary")
package(default_visibility = ["//visibility:public"])
coralnpu_v2_binary(
    name = "probe_program",
    srcs = ["hardware_probe.cc"],
    hdrs = ["pointwise_core.h", "vme_tile.h"],
    copts = ["-O2", "-fno-tree-vectorize", "-fno-tree-slp-vectorize", "-fno-lto"],
    itcm_size_kbytes = 256,
    dtcm_size_kbytes = 512,
    stack_size_bytes = 16384,
    enable_vmem = False,
)
'''
    return {PROBE_PACKAGE+"/BUILD":build.encode(),**{PROBE_PACKAGE+"/"+n:(HERE/n).read_bytes()
            for n in ("hardware_probe.cc","pointwise_core.h","vme_tile.h")}}


def prepare_probe(root,identity):
    files=probe_files()
    m=dict(schema=1,parent_manifest_sha256=portable_vme.sha(root/candidate.MANIFEST),
           files={n:candidate.sha(b) for n,b in files.items()})
    for n in ("pointwise_core.h","vme_tile.h"):
        if candidate.sha((HERE/n).read_bytes())!=identity["files"][candidate.PACKAGE+"/"+n]:
            raise ValueError("Probe kernel differs from measured candidate")
    marker=root/PROBE_MANIFEST
    if marker.exists():
        if json.loads(marker.read_text())!=m or any((root/n).read_bytes()!=b for n,b in files.items()):
            raise ValueError("Existing probe differs; nothing overwritten")
    else:
        if (root/PROBE_PACKAGE).exists(): raise ValueError("Unowned probe directory")
        (root/PROBE_PACKAGE).mkdir(parents=True)
        for n,b in files.items():
            with (root/n).open("xb") as stream: stream.write(b)
        with marker.open("x",encoding="utf-8") as stream: json.dump(m,stream,indent=2)


def configured_probe(execroot,listing):
    root=Path(execroot).resolve(strict=True); paths=set()
    for line in listing.splitlines():
        if not line.strip(): continue
        p=PurePosixPath(line.strip())
        if p.is_absolute() or ".." in p.parts or "\\" in line or not p.parts or p.parts[0]!="bazel-out" or p.name!="probe_program.elf":
            raise ValueError("Unexpected configured probe output")
        value=root.joinpath(*p.parts).resolve(strict=True)
        if not value.is_relative_to(root) or not value.is_file(): raise ValueError("Probe escaped execution root")
        paths.add(value)
    if len(paths)!=1: raise ValueError("Expected one probe ELF")
    return paths.pop()


def export(root,assets,run,baseline,job):
    identity,host,reports,base=evidence(root,assets,run,baseline)
    prepare_probe(root,identity)
    roots=(job/"execution-root.txt").read_text().splitlines()
    if len(roots)!=1 or not Path(roots[0]).is_absolute(): raise ValueError("Expected one execution root")
    probe=configured_probe(roots[0],(job/"probe-outputs.txt").read_text()).read_bytes()
    reports["probe"]=probe_audit.inspect(probe)
    output=job/"coral_person_vme_i256_d512_v1"
    output.mkdir(exist_ok=False)
    # Copy only immutable inputs, not runtime directories or the baseline ELF.
    copied_dirs=("rtl","rtl_dependencies","original","dpi","python","assets","inputs")
    for name in copied_dirs:
        shutil.copytree(base.root/name,output/name,symlinks=False)
    for name in ("LICENSE","SOURCE-NOTICES.txt","spec.py","firmware_report.py"):
        shutil.copy2(base.root/name,output/name)
    for name,digest in base.manifest["files"].items():
        if (name.split("/",1)[0] in copied_dirs or
                name in ("LICENSE","SOURCE-NOTICES.txt","spec.py","firmware_report.py")):
            if portable_vme.sha(output/name)!=digest:
                raise ValueError("Copied original input bytes changed: "+name)
    (output/"VME-NOTICES.txt").write_text(
        "Pointwise packing/scheduling adapted from cheshire-coral-soc at "+candidate.TEAM+"\n"
        "sw/models/h4-resnet8/npu.cc; Apache-2.0.\n"
        "VME encodings from the pinned official vme_test_utils.h; Apache-2.0.\n"
        "The pretrained original model is not the team's untrained diagnostic graph.\n",encoding="utf-8")
    for name in ("portable_vme.py","probe_audit.py","server_probe.py","probe_bench.py"):
        shutil.copy2(HERE/name,output/name)
    shutil.copy2(HERE/"audit.py",output/"vme_audit.py")
    runner=HERE.parent/"google_person_detect/person_runner.py"
    common=HERE.parent/"google_tcm_verilator/verilator_workset.py"
    if portable_vme.sha(runner)!=BASE_RUNNER_SHA or portable_vme.sha(common)!=COMMON_SHA:
        raise ValueError("Generic runtime helper changed")
    shutil.copy2(runner,output/"_baseline_runner.py")
    shutil.copy2(common,output/"verilator_common.py")
    firmwares={}
    for mode in ("probe","validate","fast"):
        data=probe if mode=="probe" else (run/mode/"person_program.elf").read_bytes()
        directory=output/"firmware"/mode; directory.mkdir(parents=True)
        (directory/"person_program.elf").write_bytes(data)
        (directory/"resources.json").write_text(json.dumps(reports[mode],indent=2)+"\n",encoding="utf-8")
        firmwares[mode]=dict(file="firmware/"+mode+"/person_program.elf",sha256=reports[mode]["elf_sha256"])
    (output/"evidence").mkdir()
    for n in ("manifest.json","host-test.log","validate-build.log","fast-build.log"):
        shutil.copy2(run/n,output/"evidence"/("candidate-"+n))
    for n in (candidate.MANIFEST,PROBE_MANIFEST): shutil.copy2(root/n,output/"evidence"/n)
    shutil.copy2(base.root/"manifest.json",output/"evidence/baseline-manifest.json")
    for n in ("probe-build.log","probe-outputs.txt","execution-root.txt"):
        shutil.copy2(job/n,output/"evidence"/n)
    (output/"source").mkdir()
    for n in identity["files"]:
        shutil.copy2(root/n,output/"source"/Path(n).name)
    shutil.copy2(HERE/"hardware_probe.cc",output/"source/hardware_probe.cc")
    (output/"README.md").write_text(
        "# Independent VME candidate bundle\n\nOriginal RTL/model unchanged. No RTL PASS asserted.\n"
        "probe: short signed/zero-point/tail arithmetic only, NOT model inference.\n"
        "validate/fast: measured original model ELFs, full-model server runner pending.\n"
        "Do not replace firmware in the original default package.\n"
        "Outputs must be outside this immutable directory.\n",encoding="utf-8")
    manifest={k:base.manifest[k] for k in ("upstream","hdl_top","itcm_kib","dtcm_kib","defines",
        "zip_include_dirs","rtl_sha256","model_sha256","memory_map","reference_scores_no_person_then_person")}
    manifest.update(schema=1,kind="person_vme_bundle_v1",firmwares=firmwares,simulation="NOT_RUN",
        created_utc=datetime.now(timezone.utc).isoformat(),host_layer_reference=host,
        input_sha256={c:portable_vme.sha(output/"inputs"/(c+".int8.bin")) for c in ("person","no_person")},
        baseline_manifest_sha256=portable_vme.sha(base.root/"manifest.json"),
        probe_expected=dict(cases=8,checked=840,commands=233,signature=3016346044),
        files=portable_vme.inventory(output))
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    checks=dict(manifest["files"],**{"manifest.json":portable_vme.sha(output/"manifest.json")})
    (output/"SHA256SUMS").write_text(''.join(h+"  "+n+"\n" for n,h in sorted(checks.items())),encoding="utf-8")
    portable_vme.verify(output)
    base.library.verify(base.root)
    evidence(root,assets,run,baseline)
    archive=job/(output.name+".tar.gz")
    with tarfile.open(archive,"x:gz") as stream: stream.add(output,arcname=output.name)
    digest=portable_vme.sha(archive)
    (job/(archive.name+".sha256")).write_text(digest+"  "+archive.name+"\n",encoding="utf-8")
    print("[PERSON_VME_BUNDLE_EXPORTED] RTL_bytes_equal=true original_model=true NPU_RTL=NOT_RUN")
    print("[PERSON_VME_BUNDLE_ARCHIVE] "+str(archive))
    print("[PERSON_VME_BUNDLE_SHA256] "+digest)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("prepare","export"))
    for n in ("upstream","assets","firmware-run","baseline-package"):
        parser.add_argument("--"+n,type=Path,required=True)
    parser.add_argument("--job",type=Path)
    a=parser.parse_args()
    values=[p.resolve(strict=True) for p in (a.upstream,a.assets,a.firmware_run,a.baseline_package)]
    if a.action=="prepare":
        identity,_,_,_=evidence(*values); prepare_probe(values[0],identity)
        print("[PERSON_VME_PROBE_SOURCE_VERIFIED] existing_candidate_unchanged=true NPU_RTL=NOT_RUN")
    else:
        if a.job is None: parser.error("export requires --job")
        export(*values,a.job.resolve(strict=True))
