"""Immutable VME bundle verification. Integrity is NOT an RTL/inference PASS."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

TOP="VmeCoreMini_ITCM256KB_DTCM512KBAxi"
UPSTREAM="8e4df09b4ea7e065e02d14ce3ae033d40dfd973a"
MODEL_SHA="808cfdfc0cf3a6fa6f6fa26bfa379ea97c16d5db7334637766e39c3408502e9d"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(root):
    result={}
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink(): raise ValueError("Symlink in immutable bundle")
        if path.is_file():
            name=path.relative_to(root).as_posix()
            if name not in ("manifest.json","SHA256SUMS"): result[name]=sha(path)
    return result


def safe_name(name):
    p=PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
        raise ValueError("Unsafe package filename")


def verify(root):
    root=Path(root).resolve(strict=True)
    m=json.loads((root/"manifest.json").read_text())
    if (m.get("schema")!=1 or m.get("kind")!="person_vme_bundle_v1" or m.get("upstream")!=UPSTREAM or
            m.get("hdl_top")!=TOP or m.get("itcm_kib")!=256 or m.get("dtcm_kib")!=512 or
            m.get("model_sha256")!=MODEL_SHA or m.get("simulation")!="NOT_RUN" or
            m.get("probe_expected")!=dict(cases=8,checked=840,commands=233,signature=3016346044) or
            m.get("reference_scores_no_person_then_person")!={"person":[-113,113],"no_person":[57,-57]} or
            m.get("memory_map")!=dict(itcm=0,dtcm=0x01000000,csr=0x02000000,external=0x20000000)):
        raise ValueError("Wrong VME bundle identity")
    for name in m["files"]: safe_name(name)
    if inventory(root)!=m["files"]: raise ValueError("Package files missing/extra/changed; do not edit hashes")
    checks={}
    for line in (root/"SHA256SUMS").read_text().splitlines():
        digest,name=line.split("  ",1); safe_name(name)
        if name in checks: raise ValueError("Duplicate checksum")
        checks[name]=digest
    if checks!=dict(m["files"],**{"manifest.json":sha(root/"manifest.json")}):
        raise ValueError("Checksum index differs")
    if sha(root/"rtl"/(TOP+".sv"))!=m["rtl_sha256"] or sha(root/"assets/person_detect.tflite")!=MODEL_SHA:
        raise ValueError("RTL or model identity changed")
    if set(m["firmwares"])!={"probe","validate","fast"}: raise ValueError("Missing firmware variants")
    for variant,item in m["firmwares"].items():
        safe_name(item["file"])
        if item["file"]!="firmware/"+variant+"/person_program.elf" or sha(root/item["file"])!=item["sha256"]:
            raise ValueError("Firmware bytes changed: "+variant)
    for case in ("person","no_person"):
        p=root/"inputs"/(case+".int8.bin")
        if p.stat().st_size!=9216 or sha(p)!=m["input_sha256"][case]: raise ValueError("Input bytes changed")
    return m


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package",type=Path)
    value=verify(parser.parse_args().package)
    print("[PERSON_VME_BUNDLE_VERIFIED] RTL_and_model_unchanged=true NPU_RTL=NOT_RUN")
