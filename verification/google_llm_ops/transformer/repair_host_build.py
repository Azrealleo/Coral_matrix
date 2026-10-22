"""Explicit one-version BUILD repair; refuse unknown edits, save old evidence."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import tx_prepare as prepare

LEGACY_GENERATOR_SHA="5fb56201aa51bd0b1020a32c8df386774247c6796e6ee2ca6d9c094ffcad4b4c"
NEW=b'cc_test(name="host_reference_test",srcs=["bench.cc","kernels.cc","fixtures.cc","kernels.h"],'
OLD=b'cc_test(name="host_reference_test",srcs=["bench.cc","kernels.cc","fixtures.cc"],hdrs=["kernels.h"],'


def replace_file(path,data):
    # Same-directory atomic replacement, only after full identity validation.
    fd,name=tempfile.mkstemp(prefix=".host_hdrs_repair.",dir=path.parent)
    with os.fdopen(fd,"wb") as stream:stream.write(data)
    os.replace(name,path)


def repair(root,files):
    root=Path(root).resolve(strict=True);marker=root/prepare.MANIFEST;build=root/prepare.PACKAGE/"BUILD"
    if root/prepare.PACKAGE!=(root/prepare.PACKAGE).resolve() or marker.is_symlink():
        raise ValueError("Refuse symlinked generated package/manifest")
    # Generate the exact current manifest in a private temporary directory,
    # NEVER install over the old directory before verifying every old byte.
    with tempfile.TemporaryDirectory(prefix="llm_tx_repair_plan.") as temporary:
        wanted=prepare.install(Path(temporary),files)
    if not marker.exists():
        prepare.install(root,files)
        print("[LLM_TX_HOST_BUILD_READY] fresh=true RTL=NOT_RUN");return
    current=json.loads(marker.read_text())
    if current==wanted:
        prepare.install(root,files)
        print("[LLM_TX_HOST_BUILD_READY] already_repaired=true RTL=NOT_RUN");return
    if files["BUILD"].count(NEW)!=1:raise ValueError("Repair only supports the exact known BUILD change")
    old_build=files["BUILD"].replace(NEW,OLD)
    legacy=copy.deepcopy(wanted);legacy["generator_sha256"]=LEGACY_GENERATOR_SHA
    legacy["files"][prepare.PACKAGE+"/BUILD"]=prepare.digest(old_build)
    if current!=legacy:raise ValueError("Unknown previous manifest; nothing overwritten")
    for name,digest in legacy["files"].items():
        path=root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError("Refuse source symlink/escape")
        data=path.read_bytes()
        if name==prepare.PACKAGE+"/BUILD":
            if data not in (old_build,files["BUILD"]):raise ValueError("User-edited BUILD; nothing overwritten")
        elif prepare.digest(data)!=digest:raise ValueError("User-edited source; nothing overwritten: "+name)
    backup=Path(tempfile.mkdtemp(prefix="llm_tx_host_hdrs_repair.",dir=root.parent))
    # Preserve the known original BUILD even when resuming an interrupted repair.
    (backup/"BUILD.before").write_bytes(old_build)
    (backup/"manifest.before.json").write_bytes(marker.read_bytes())
    report=dict(schema=1,reason="cc_test_header_belongs_in_srcs_not_hdrs",old_manifest=current,new_manifest=wanted,
        kernels_and_bench_unchanged=True,RTL="NOT_RUN")
    (backup/"repair.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print("[LLM_TX_HOST_BUILD_REPAIR_BACKUP] "+str(backup),flush=True)
    replace_file(build,files["BUILD"])
    replace_file(marker,(json.dumps(wanted,indent=2)+"\n").encode())
    prepare.install(root,files)
    print("[LLM_TX_HOST_BUILD_REPAIRED] only_BUILD_and_manifest=true kernels_unchanged=true RTL=NOT_RUN")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--upstream",type=Path,default=Path.home()/"coral_tcm_capacity_8e4_v1/source")
    a=p.parse_args();root=a.upstream.resolve(strict=True)
    # Independently recheck the old qualified address map and INT8 candidate.
    sys.path.insert(0,str(prepare.HERE.parent))
    import importlib.util
    spec=importlib.util.spec_from_file_location("_repair_original_linear",prepare.HERE.parent/"prepare.py")
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base);base.prepare(root)
    repair(root,prepare.expected(root))


if __name__=="__main__":
    try:main()
    except Exception as error:
        print("[LLM_TX_HOST_BUILD_REPAIR_STOP] "+str(error),file=sys.stderr);sys.exit(1)
