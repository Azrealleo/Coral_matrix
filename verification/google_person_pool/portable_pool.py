"""Verify a new immutable VME+RVV Pool bundle; integrity is not an RTL PASS."""
import json
from pathlib import Path
import portable_vme as common

sha=common.sha
inventory=common.inventory
EXPECTED=dict(cases=8,checked=659,commands=62,signature=642806987)
SCOPE="short_RVV_average_pool_not_model_inference"


def verify(root):
    root=Path(root).resolve(strict=True)
    m=json.loads((root/"manifest.json").read_text())
    required=dict(schema=1,kind="person_vme_pool_bundle_v1",upstream=common.UPSTREAM,
        hdl_top=common.TOP,itcm_kib=256,dtcm_kib=512,model_sha256=common.MODEL_SHA,
        simulation="NOT_RUN",probe_expected=EXPECTED,probe_scope=SCOPE,
        depthwise="official_default_registration_unchanged",
        reference_scores_no_person_then_person={"person":[-113,113],"no_person":[57,-57]},
        memory_map=dict(itcm=0,dtcm=0x01000000,csr=0x02000000,external=0x20000000))
    if any(type(m.get(k)) is not type(v) or m.get(k)!=v for k,v in required.items()):
        raise ValueError("Wrong VME+RVV Pool bundle identity")
    for n in m["files"]:common.safe_name(n)
    if inventory(root)!=m["files"]:raise ValueError("Missing/extra/changed package files; never edit hashes")
    checks={}
    for line in (root/"SHA256SUMS").read_text().splitlines():
        digest,name=line.split("  ",1);common.safe_name(name)
        if name in checks:raise ValueError("Duplicate checksum")
        checks[name]=digest
    if checks!=dict(m["files"],**{"manifest.json":sha(root/"manifest.json")}):
        raise ValueError("Checksum index differs")
    if sha(root/"rtl"/(common.TOP+".sv"))!=m["rtl_sha256"] or sha(root/"assets/person_detect.tflite")!=common.MODEL_SHA:
        raise ValueError("Original RTL/model changed")
    if set(m["firmwares"])!={"probe","validate","fast"}:raise ValueError("Missing firmware modes")
    for mode,item in m["firmwares"].items():
        if item["file"]!="firmware/"+mode+"/person_program.elf" or sha(root/item["file"])!=item["sha256"]:
            raise ValueError("Firmware identity changed: "+mode)
    for case in ("person","no_person"):
        p=root/"inputs"/(case+".int8.bin")
        if p.stat().st_size!=9216 or sha(p)!=m["input_sha256"][case]:raise ValueError("Input bytes changed")
    return m
