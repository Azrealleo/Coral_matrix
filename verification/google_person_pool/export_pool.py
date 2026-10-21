"""Seal independent Pool probe and measured combined-model ELFs, not simulate."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
VME=HERE.parent/"google_person_vme"
sys.path.insert(0,str(VME))
import export_bundle as previous
import portable_vme
import portable_pool
import prepare_pool as candidate
import audit_pool
import pool_probe_audit
PROBE_PACKAGE="tests/cocotb/person_pool_probe_v1"
PROBE_MANIFEST="person_pool_probe_v1_manifest.json"


def checked_host(text):
    lines=text.splitlines()
    for case,scores in (("person","-113,113"),("no_person","57,-57")):
        expected="[PERSON_POOL_HOST_MODEL_CASE] case="+case+" conv_layers=14 pool_layers=1 byte_exact=true scores="+scores
        if lines.count(expected)!=1:raise ValueError("Missing/duplicate native layer check: "+case)
    rows=re.findall(r"^\[PERSON_POOL_HOST_MODEL_PASS\] cases=2 compared_layers=30 arena_used=(\d+) hardware=NOT_RUN$",text,re.M)
    core=re.findall(r"^\[PERSON_POOL_CORE_HOST_PASS\] cases=2160 checked=1291923 rounding_counts=49 RVV=NOT_RUN$",text,re.M)
    if len(rows)!=1 or not 0<int(rows[0])<=163840 or len(core)!=1 or re.search(r"\bFAILED\b|^FAIL[: ]",text,re.M):
        raise ValueError("Incomplete/failed native Pool evidence")
    return dict(cases=2,compared_layers=30,arena_used_bytes=int(rows[0]),hardware="NOT_RUN",core_marker=core[0])


def evidence(root,assets,run,parent):
    identity=candidate.prepare(root,assets)
    if json.loads((run/"manifest.json").read_text())!=identity:raise ValueError("Measured Pool candidate identity differs")
    host=checked_host((run/"host-test.log").read_text())
    reports={}
    for mode in ("validate","fast"):
        reports[mode]=audit_pool.inspect((run/mode/"person_program.elf").read_bytes(),mode)
        if reports[mode]!=json.loads((run/mode/"resources.json").read_text()):raise ValueError("Changed ELF/report: "+mode)
    m=portable_vme.verify(parent)
    if m["rtl_sha256"]!="477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2":
        raise ValueError("Not the previously probed original RTL")
    for n,digest in (("_baseline_runner.py",previous.BASE_RUNNER_SHA),("verilator_common.py",previous.COMMON_SHA)):
        if portable_vme.sha(parent/n)!=digest:raise ValueError("Unqualified runtime helper")
    for n in ("pointwise_core.h","vme_tile.h","conv_vme.cc","conv_vme.h"):
        if (parent/"source"/n).read_bytes()!=(root/candidate.PACKAGE/n).read_bytes():
            raise ValueError("VME kernel changed: "+n)
    return identity,host,reports,m


def probe_files():
    build=previous.probe_files()[previous.PROBE_PACKAGE+"/BUILD"].decode()
    build=replace_once(build,'"pointwise_core.h", "vme_tile.h"','"pool_core.h", "pool_rvv.h"')
    return {PROBE_PACKAGE+"/BUILD":build.encode(),**{PROBE_PACKAGE+"/"+n:(HERE/n).read_bytes()
        for n in ("hardware_probe.cc","pool_core.h","pool_rvv.h")}}


def prepare_probe(root,identity):
    files=probe_files()
    for n in ("pool_core.h","pool_rvv.h"):
        if portable_vme.sha(HERE/n)!=identity["files"][candidate.PACKAGE+"/"+n]:
            raise ValueError("Probe differs from measured Pool kernel")
    m=dict(schema=1,files={n:candidate.parent.sha(b) for n,b in files.items()},
        parent_manifest_sha256=portable_vme.sha(root/candidate.MANIFEST))
    marker=root/PROBE_MANIFEST
    if marker.exists():
        if json.loads(marker.read_text())!=m or any((root/n).read_bytes()!=b for n,b in files.items()):
            raise ValueError("Existing Pool probe differs; nothing overwritten")
    else:
        if (root/PROBE_PACKAGE).exists():raise ValueError("Unowned Pool probe directory")
        (root/PROBE_PACKAGE).mkdir(parents=True)
        for n,b in files.items():
            with (root/n).open("xb") as stream:stream.write(b)
        with marker.open("x",encoding="utf-8") as stream:json.dump(m,stream,indent=2)


def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError("Qualified runtime anchor changed: "+old)
    return text.replace(old,new)


def runtime_files():
    # A NEW packaged launcher/bench, never patch the successful old package.
    server=(VME/"server_probe.py").read_text()
    bench=(VME/"probe_bench.py").read_text()
    if (hashlib.sha256(server.encode()).hexdigest()!="223685a529d1eaa9b1c865608e23b48e3be0f3b3378cab52b76fb97c45bb654a" or
        hashlib.sha256(bench.encode()).hexdigest()!="0e8c2af9ca93b85e93354645e6978d0de790fe3183369019d0214a11039b3841"):
        raise ValueError("Previously qualified probe runtime template changed")
    server=replace_once(server,"import portable_vme","import portable_pool as portable_vme")
    server=replace_once(server,"import probe_audit","import pool_probe_audit as probe_audit")
    server=replace_once(server,'source=HERE/"audit.py"','source=HERE/"audit_pool.py"')
    server=server.replace('HERE/"vme_audit.py"','HERE/"audit_pool.py"').replace('root/"vme_audit.py"','root/"audit_pool.py"')
    server=replace_once(server,"cases=8,checked=840,mismatches=0,commands=233,signature=3016346044",
                        "cases=8,checked=659,mismatches=0,commands=62,signature=642806987")
    for old,new in (("PERSON_VME","PERSON_POOL"),("person_vme_probe_test","person_pool_probe_test"),
                    ("short_VME_arithmetic_not_model_inference",portable_pool.SCOPE)):
        server=server.replace(old,new);bench=bench.replace(old,new)
    server=server.replace("Standalone short VME RTL probe.","Standalone short RVV Pool RTL probe.")
    bench=bench.replace("Short real VME check","Short real RVV AveragePool check")
    return {"server_probe.py":server.encode(),"probe_bench.py":bench.encode()}


def export(root,assets,run,parent,job):
    identity,host,reports,prior=evidence(root,assets,run,parent)
    prepare_probe(root,identity)
    roots=(job/"execution-root.txt").read_text().splitlines()
    if len(roots)!=1 or not Path(roots[0]).is_absolute():raise ValueError("Expected one execution root")
    probe=previous.configured_probe(roots[0],(job/"probe-outputs.txt").read_text()).read_bytes()
    reports["probe"]=pool_probe_audit.inspect(probe)
    output=job/"coral_person_vme_pool_i256_d512_v1";output.mkdir(exist_ok=False)
    dirs=("rtl","rtl_dependencies","original","dpi","python","assets","inputs")
    for n in dirs:shutil.copytree(parent/n,output/n,symlinks=False)
    for n in ("LICENSE","SOURCE-NOTICES.txt","VME-NOTICES.txt","spec.py","firmware_report.py",
              "_baseline_runner.py","verilator_common.py","vme_audit.py","probe_audit.py","portable_vme.py"):
        shutil.copy2(parent/n,output/n)
    # Every copied input must still match the sealed predecessor inventory.
    for n,digest in portable_vme.inventory(output).items():
        if prior["files"].get(n)!=digest:raise ValueError("Copied original bytes differ: "+n)
    for n in ("portable_pool.py","pool_probe_audit.py","audit_pool.py"):
        shutil.copy2(HERE/n,output/n)
    for n,data in runtime_files().items():(output/n).write_bytes(data)
    firmwares={}
    for mode in ("probe","validate","fast"):
        data=probe if mode=="probe" else (run/mode/"person_program.elf").read_bytes()
        d=output/"firmware"/mode;d.mkdir(parents=True)
        (d/"person_program.elf").write_bytes(data)
        (d/"resources.json").write_text(json.dumps(reports[mode],indent=2)+"\n",encoding="utf-8")
        firmwares[mode]=dict(file="firmware/"+mode+"/person_program.elf",sha256=reports[mode]["elf_sha256"])
    (output/"source").mkdir();(output/"evidence").mkdir()
    for n in identity["files"]:shutil.copy2(root/n,output/"source"/Path(n).name)
    shutil.copy2(HERE/"hardware_probe.cc",output/"source/hardware_probe.cc")
    for n in ("manifest.json","host-test.log","validate-build.log","fast-build.log"):
        shutil.copy2(run/n,output/"evidence"/("pool-"+n))
    for n in (candidate.MANIFEST,PROBE_MANIFEST):shutil.copy2(root/n,output/"evidence"/n)
    for n in ("probe-build.log","probe-outputs.txt","execution-root.txt"):shutil.copy2(job/n,output/"evidence"/n)
    shutil.copy2(parent/"manifest.json",output/"evidence/parent-vme-manifest.json")
    (output/"README.md").write_text(
        "# VME + RVV AveragePool independent candidate\n\n"
        "Original RTL/model/Depthwise registration unchanged. Export is NOT RTL PASS.\n"
        "probe tests only RVV Pool arithmetic: 8 cases / 659 elements / 62 vector-loop blocks.\n"
        "The commands field counts vector-loop blocks, NOT retired instructions.\n"
        "validate/fast are the measured combined-model ELFs, NOT yet RTL verified.\n"
        "This short-probe launcher does NOT run full inference. Never swap ELFs into old packages.\n"
        "All runtime outputs belong outside this immutable directory.\n",encoding="utf-8")
    m={k:prior[k] for k in ("upstream","hdl_top","itcm_kib","dtcm_kib","defines","zip_include_dirs",
        "rtl_sha256","model_sha256","memory_map","reference_scores_no_person_then_person","input_sha256")}
    m.update(schema=1,kind="person_vme_pool_bundle_v1",simulation="NOT_RUN",firmwares=firmwares,
        depthwise="official_default_registration_unchanged",host_layer_reference=host,
        parent_manifest_sha256=portable_vme.sha(parent/"manifest.json"),
        created_utc=datetime.now(timezone.utc).isoformat(),probe_expected=portable_pool.EXPECTED,
        probe_scope=portable_pool.SCOPE,files=portable_vme.inventory(output))
    (output/"manifest.json").write_text(json.dumps(m,indent=2)+"\n",encoding="utf-8")
    checks=dict(m["files"],**{"manifest.json":portable_vme.sha(output/"manifest.json")})
    (output/"SHA256SUMS").write_text(''.join(h+"  "+n+"\n" for n,h in sorted(checks.items())),encoding="utf-8")
    portable_pool.verify(output);evidence(root,assets,run,parent)
    archive=job/(output.name+".tar.gz")
    with tarfile.open(archive,"x:gz") as stream:stream.add(output,arcname=output.name)
    digest=portable_vme.sha(archive)
    (job/(archive.name+".sha256")).write_text(digest+"  "+archive.name+"\n",encoding="utf-8")
    print("[PERSON_POOL_BUNDLE_EXPORTED] original_RTL_model=true depthwise_unchanged=true NPU_RTL=NOT_RUN")
    print("[PERSON_POOL_BUNDLE_ARCHIVE] "+str(archive))
    print("[PERSON_POOL_BUNDLE_SHA256] "+digest)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("prepare","export"))
    for n in ("upstream","assets","firmware-run","parent-package"):p.add_argument("--"+n,type=Path,required=True)
    p.add_argument("--job",type=Path)
    a=p.parse_args();values=[n.resolve(strict=True) for n in (a.upstream,a.assets,a.firmware_run,a.parent_package)]
    if a.action=="prepare":
        identity,_,_,_=evidence(*values);prepare_probe(values[0],identity)
        print("[PERSON_POOL_PROBE_SOURCE_VERIFIED] measured_ELFs_unchanged=true NPU_RTL=NOT_RUN")
    else:
        if a.job is None:p.error("export requires --job")
        export(*values,a.job.resolve(strict=True))
