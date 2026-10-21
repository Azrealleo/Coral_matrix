"""Export only the measured small firmware/tools, NOT another RTL package."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tarfile

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"google_person_vme"))
import portable_vme
import prepare_conv
import audit_conv
import conv_contract


def export(root,assets,run,job):
    identity=prepare_conv.prepare(root,assets)
    if json.loads((run/"manifest.json").read_text())!=identity:raise ValueError("Measured Conv source differs")
    data=(run/"conv_program.elf").read_bytes();report=audit_conv.inspect(data)
    if report!=json.loads((run/"resources.json").read_text()) or report["elf_sha256"]!=conv_contract.ELF_SHA:
        raise ValueError("Measured Conv ELF/report changed")
    host=audit_conv.checked_host((run/"host-test.log").read_text(),identity["cases"])
    if host!=json.loads((run/"host-signatures.json").read_text()):raise ValueError("Native output signatures changed")
    linked=conv_contract.layout(data,identity["cases"])
    packet=job/"coral_person_conv_v1";packet.mkdir(exist_ok=False)
    for n in ("conv_program.elf","resources.json","host-signatures.json","host-test.log","build.log"):
        shutil.copy2(run/n,packet/n)
    (packet/"source").mkdir()
    for n,digest in identity["files"].items():
        if portable_vme.sha(root/n)!=digest:raise ValueError("Candidate source changed")
        shutil.copy2(root/n,packet/"source"/Path(n).name)
    shutil.copy2(root/"LICENSE",packet/"LICENSE")
    (packet/"NOTICES.txt").write_text(
        "TensorFlow Authors pretrained Person model constants, Apache-2.0.\n"
        "These are one-Conv diagnostic derivatives, not the complete original model.\n"
        "VME schedule adapted from cheshire-coral-soc fa4b83e43bb0b1d58b18eb5f4c31d98ee4054123, Apache-2.0.\n",
        encoding="utf-8")
    (packet/"candidate-manifest.json").write_text(json.dumps(identity,indent=2)+"\n",encoding="utf-8")
    (packet/"layout.json").write_text(json.dumps(linked,indent=2)+"\n",encoding="utf-8")
    for n in ("conv_contract.py","audit_conv.py","server_conv.py","conv_rtl_bench.py"):
        shutil.copy2(HERE/n,packet/n)
    for n in ("portable_vme.py","probe_audit.py"):shutil.copy2(HERE.parent/"google_person_vme"/n,packet/n)
    helper=HERE.parent/"google_person_pool/model_runner.py"
    if portable_vme.sha(helper)!="3d6753e12b348d8816ca377156233f9ce0b544c773ece8b4376e54b1b78d8d7e":
        raise ValueError("Qualified build checker changed")
    shutil.copy2(helper,packet/"qualified_model.py")
    (packet/"README.md").write_text(
        "# Small single-Conv firmware packet\n\nNo RTL included; NOT simulation PASS.\n"
        "Use server_conv.py with the existing qualified Pool RTL package/model.\n"
        "Default run selects case0 only. No complete model inference is launched.\n"
        "Outputs and runtime records must remain outside this immutable directory.\n",encoding="utf-8")
    manifest=dict(schema=1,kind="person_conv_firmware_packet_v1",elf_sha256=report["elf_sha256"],
        upstream=identity["upstream"],source_model_sha256=identity["source_model_sha256"],
        itcm_kib=256,dtcm_kib=512,cases=identity["cases"],timing_scope=identity["scope"],simulation="NOT_RUN",
        files=portable_vme.inventory(packet))
    (packet/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    checks=dict(manifest["files"],**{"manifest.json":portable_vme.sha(packet/"manifest.json")})
    (packet/"SHA256SUMS").write_text(''.join(h+"  "+n+"\n" for n,h in sorted(checks.items())),encoding="utf-8")
    conv_contract.verify(packet);prepare_conv.prepare(root,assets)
    archive=job/(packet.name+".tar.gz")
    with tarfile.open(archive,"x:gz") as stream:stream.add(packet,arcname=packet.name)
    digest=portable_vme.sha(archive)
    (job/(archive.name+".sha256")).write_text(digest+"  "+archive.name+"\n",encoding="utf-8")
    print("[PERSON_CONV_PACKET_EXPORTED] RTL_included=false firmware_unchanged=true NPU_RTL=NOT_RUN")
    print("[PERSON_CONV_PACKET_ARCHIVE] "+str(archive))
    print("[PERSON_CONV_PACKET_SHA256] "+digest)
    print("[PERSON_CONV_PACKET_BYTES] "+str(archive.stat().st_size))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("upstream","assets","run","job"):p.add_argument("--"+n,type=Path,required=True)
    a=p.parse_args();export(*(getattr(a,n).resolve(strict=True) for n in ("upstream","assets","run","job")))
