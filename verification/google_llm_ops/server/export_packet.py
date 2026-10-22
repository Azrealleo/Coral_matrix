"""Export actually linked ELFs and native evidence, without RTL or simulation."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tarfile
import packet

HERE=Path(__file__).resolve().parent
LINEAR=HERE.parent
TX=LINEAR/"transformer"


def export(root,job):
    sys.path.insert(0,str(LINEAR));sys.path.insert(0,str(TX))
    import tx_prepare
    tx_prepare.prepare(root)
    hroot=job/"coral_llm_ops_i256_d512_v1";hroot.mkdir(exist_ok=False)
    generated=json.loads((root/"llm_linear_v1_manifest.json").read_text())
    tx_generated=json.loads((root/tx_prepare.MANIFEST).read_text())
    manifest_by_family=dict(int8=generated,fp32=tx_generated)
    # Import isolated specs, not the Person model spec installed by old helpers.
    for name,source in (("linear",LINEAR),("transformer",TX)):
        (hroot/name).mkdir()
        names=("spec.py","audit.py","linear_rtl_bench.py") if name=="linear" else ("tx_spec.py","tx_audit.py","tx_bench.py")
        for filename in names:shutil.copyfile(source/filename,hroot/name/filename)
    audits=packet.helpers(hroot)
    firmware_shas={}
    rtl_identity=None
    for family,audit in (("int8",audits.linear_audit),("fp32",audits.tx_audit)):
        run=job/family;source_manifest=manifest_by_family[family]
        if json.loads((run/"manifest.json").read_text())!=source_manifest:raise ValueError("Actual build source differs")
        elf=(run/"probe_program.elf").read_bytes();report=audit.inspect(elf)
        if report!=json.loads((run/"resources.json").read_text()):raise ValueError("Actual ELF audit differs")
        packet.checked_host(audits,family,(run/"host.log").read_text())
        current=json.loads((run/"rtl-identity.json").read_text())
        current={n:current[n] for n in ("rtl_sha256","parameters")}
        if current["rtl_sha256"]!=packet.RTL_SHA:raise ValueError("VM RTL bytes differ from qualified server model; do not relabel")
        if rtl_identity is not None and rtl_identity!=current:raise ValueError("Builds used different RTL/parameters")
        rtl_identity=current
        output=hroot/"firmware"/family;output.mkdir(parents=True)
        for name in ("probe_program.elf","resources.json","host.log","build.log"):
            shutil.copyfile(run/name,output/name)
        (output/"source-manifest.json").write_text(json.dumps(source_manifest,indent=2)+"\n",encoding="utf-8")
        snapshot=hroot/"source"/family;snapshot.mkdir(parents=True)
        for name,digest in source_manifest["files"].items():
            packet.safe_name(name)
            if (snapshot/Path(name).name).exists():raise ValueError("Ambiguous source snapshot filename")
            if packet.sha(root/name)!=digest:raise ValueError("Installed source changed")
            shutil.copyfile(root/name,snapshot/Path(name).name)
        firmware_shas[family]=report["elf_sha256"]
    shutil.copyfile(job/"int8/parameters.h",hroot/"parameters.h")
    for name in ("packet.py","server_ops.py","server_bench.py"):
        shutil.copyfile(HERE/name,hroot/name)
    helper=LINEAR.parent/"google_person_pool/model_runner.py"
    if packet.sha(helper)!=packet.HELPER_SHA:raise ValueError("Qualified existing model checker changed")
    shutil.copyfile(helper,hroot/"qualified_model.py")
    shutil.copyfile(root/"LICENSE",hroot/"LICENSE")
    shutil.copyfile(HERE/"SERVER.md",hroot/"SERVER.md")
    (hroot/"NOTICES.txt").write_text(
        "Official CoralNPU matrix kernels, Google LLC, Apache-2.0, pinned revision "+packet.UPSTREAM+".\n"
        "Other FP32 operators are project baselines, not official Gemma kernels.\n"
        "No model weights, no new RTL; exported firmware is NOT an RTL PASS.\n",encoding="utf-8")
    packet.seal(hroot,dict(schema=1,kind="llm_operator_firmware_packet_v1",upstream=packet.UPSTREAM,
        itcm_kib=256,dtcm_kib=512,rtl_sha256=packet.RTL_SHA,hdl_top=packet.TOP,simulation="NOT_RUN",
        firmwares=firmware_shas,case_counts=dict(int8=4,fp32=17)))
    packet.load(hroot);tx_prepare.prepare(root)
    archive=job/(hroot.name+".tar.gz")
    with tarfile.open(archive,"x:gz") as stream:stream.add(hroot,arcname=hroot.name)
    digest=packet.sha(archive)
    with (job/(archive.name+".sha256")).open("x",encoding="utf-8") as stream:stream.write(digest+"  "+archive.name+"\n")
    print("[LLM_SERVER_PACKET_READY] RTL_included=false simulation=NOT_RUN")
    print("[LLM_SERVER_PACKET_ARCHIVE] "+str(archive))
    print("[LLM_SERVER_PACKET_SHA256] "+digest)
    print("[LLM_SERVER_PACKET_BYTES] "+str(archive.stat().st_size))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--upstream",type=Path,required=True);p.add_argument("--job",type=Path,required=True)
    a=p.parse_args();export(a.upstream.resolve(strict=True),a.job.resolve(strict=True))
