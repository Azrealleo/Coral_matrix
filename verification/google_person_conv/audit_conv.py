"""Audit the single-Conv benchmark, not complete-model inference or RTL PASS."""
import argparse
import io
import json
from pathlib import Path
import re
import sys
from elftools.elf.elffile import ELFFile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"google_person_vme"))
import probe_audit

EXTRA={n:4 for n in ("pd_conv_case","pd_conv_empty_cycles","pd_conv_m","pd_conv_k","pd_conv_n",
    "pd_conv_op","pd_conv_arena_ref","pd_conv_arena_vme","pd_vme_conv_calls","pd_vme_fallback_calls",
    "pd_vme_commands","pd_vme_mismatches","pd_vme_validated_layers")}
EXTRA.update(pd_conv_ref_cycles=16,pd_conv_vme_cycles=16)


def inspect(data):
    report=probe_audit.inspect(data);elf=ELFFile(io.BytesIO(data));table=elf.get_section_by_name(".symtab")
    found={s.name:dict(address=int(s["st_value"]),bytes=int(s["st_size"]))
        for s in table.iter_symbols() if s.name in EXTRA and s["st_shndx"]!="SHN_UNDEF"}
    if found.keys()!=EXTRA.keys():raise ValueError("Missing single-Conv diagnostic symbols")
    for name,item in found.items():
        start,size=item["address"],item["bytes"]
        if (size!=EXTRA[name] or start%4 or not 0x01000000<=start<start+size<=report["symbols"]["__heap_start__"]["address"] or
            not any(s["address"]<=start<start+size<=s["address"]+s["bytes"] for s in report["segments"])):
            raise ValueError("Bad single-Conv diagnostic geometry: "+name)
    case=found["pd_conv_case"];preloaded=False
    for segment in elf.iter_segments():
        if segment["p_type"]=="PT_LOAD" and segment["p_paddr"]<=case["address"]<case["address"]+4<=segment["p_paddr"]+segment["p_filesz"]:
            offset=case["address"]-segment["p_paddr"]
            preloaded=segment.data()[offset:offset+4]==bytes.fromhex("feffffff")
    if not preloaded:raise ValueError("Host case selector must survive CRT BSS clearing")
    report["symbols"].update(found)
    static_end=report["symbols"]["__heap_start__"]["address"]
    report.update(scope="single_conv_spatial_fragment_not_complete_model",itcm_kib=256,dtcm_kib=512,
        itcm_occupied_extent_bytes=max(s["address"]+s["bytes"] for s in report["segments"] if s["address"]<0x01000000),
        dtcm_static_extent_bytes=static_end-0x01000000,
        heap_remaining_bytes=report["symbols"]["__heap_end__"]["address"]-static_end,
        samples=4,steady_repeats=3,reference_validation_inside_vme_timing=False)
    return report


def checked_host(text,cases):
    final="[PERSON_CONV_HOST_PASS] cases=5 complete_model=NOT_RUN hardware=NOT_RUN"
    if text.splitlines().count(final)!=1 or re.search(r"\bFAILED\b|^FAIL[: ]",text,re.M):raise ValueError("Incomplete/failed native Conv test")
    rows=re.findall(r"^\[PERSON_CONV_HOST_CASE\] id=(\d+) name=(\S+) checked=(\d+) signature=(\d+) ref_and_emulated_vme_equal=true$",text,re.M)
    if len(rows)!=len(cases):raise ValueError("Missing/duplicate native Conv case evidence")
    result={}
    for actual,case in zip(rows,cases):
        i,name,checked,signature=actual
        if int(i)!=case["id"] or name!=case["name"] or int(checked)!=4*case["M"]*case["N"]:
            raise ValueError("Wrong native Conv shape or checked count")
        result[name]=dict(checked_elements=int(checked),signature=int(signature))
    return result


if __name__=="__main__":
    import export_bundle
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("execution-root-file","outputs-file","run","upstream"):p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args();roots=a.execution_root_file.read_text().splitlines()
    if len(roots)!=1 or not Path(roots[0]).is_absolute():raise ValueError("Expected one execution root")
    data=export_bundle.configured_probe(roots[0],a.outputs_file.read_text()).read_bytes()
    report=inspect(data)
    manifest=json.loads((a.run/"manifest.json").read_text())
    if manifest!=json.loads((a.upstream/"person_conv_bench_v1_manifest.json").read_text()):raise ValueError("Run source identity differs")
    host=checked_host((a.run/"host-test.log").read_text(),manifest["cases"])
    for n,b in (("conv_program.elf",data),("resources.json",(json.dumps(report,indent=2)+"\n").encode()),
                ("host-signatures.json",(json.dumps(host,indent=2)+"\n").encode())):
        with (a.run/n).open("xb") as stream:stream.write(b)
    print("[PERSON_CONV_ELF_AUDIT] "+json.dumps({n:report[n] for n in
        ("elf_sha256","itcm_occupied_extent_bytes","dtcm_static_extent_bytes","heap_remaining_bytes","NPU_RTL")}))
