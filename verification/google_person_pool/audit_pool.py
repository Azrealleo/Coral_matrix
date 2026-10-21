"""Resource/symbol audit for the new pool candidate; NOT an RTL PASS."""
import argparse
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import sys
from elftools.elf.elffile import ELFFile

HERE=Path(__file__).resolve().parent
vme_path=HERE/"vme_audit.py"
if not vme_path.is_file():vme_path=HERE.parent/"google_person_vme/audit.py"
spec=importlib.util.spec_from_file_location("_pool_vme_elf_audit",vme_path)
vme=importlib.util.module_from_spec(spec);spec.loader.exec_module(vme)


def inspect(data,mode):
    report=vme.inspect(data,mode)
    known={"pd_pool_calls","pd_pool_fallbacks","pd_pool_vector_blocks","pd_pool_mismatches","pd_pool_validated"}
    required=known if mode=="validate" else known-{"pd_pool_validated"}
    table=ELFFile(io.BytesIO(data)).get_section_by_name(".symtab")
    found={s.name:dict(address=int(s["st_value"]),bytes=int(s["st_size"])) for s in table.iter_symbols()
           if s.name in known and s["st_shndx"]!="SHN_UNDEF"}
    missing=required-found.keys()
    invalid=[n for n,s in found.items() if s["bytes"]!=4 or not
             0x01000000<=s["address"]<s["address"]+4<=report["symbols"]["__heap_start__"]["address"]]
    if missing or invalid:raise ValueError("Pool diagnostic missing="+str(sorted(missing))+" invalid="+str(invalid))
    report.update(kernel_backend="VME_pointwise_RVV_average_pool_reference_other_ops",pool_symbols=found,
        depthwise="official_default_registration_unchanged",pool_validation=(mode=="validate"))
    return report


def configured(root,listing,mode):
    root=Path(root).resolve(strict=True);values=set()
    for line in listing.splitlines():
        if not line.strip():continue
        p=PurePosixPath(line.strip())
        if (p.is_absolute() or ".." in p.parts or "\\" in line or not p.parts or p.parts[0]!="bazel-out" or
                p.name!="person_vme_pool_"+mode+".elf"):raise ValueError("Unexpected configured pool ELF")
        actual=root.joinpath(*p.parts).resolve(strict=True)
        if not actual.is_relative_to(root) or not actual.is_file():raise ValueError("ELF escaped execroot")
        values.add(actual)
    if len(values)!=1:raise ValueError("Expected one configured pool ELF")
    return values.pop()


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode",choices=("validate","fast"),required=True)
    for n in ("execution-root-file","outputs-file","output"):p.add_argument("--"+n,type=Path,required=True)
    a=p.parse_args();roots=a.execution_root_file.read_text().splitlines()
    if len(roots)!=1 or not Path(roots[0]).is_absolute():raise ValueError("Expected one execution root")
    data=configured(roots[0],a.outputs_file.read_text(),a.mode).read_bytes();report=inspect(data,a.mode)
    a.output.mkdir(exist_ok=False)
    with (a.output/"person_program.elf").open("xb") as stream:stream.write(data)
    with (a.output/"resources.json").open("x",encoding="utf-8") as stream:json.dump(report,stream,indent=2)
    print("[PERSON_POOL_ELF_AUDIT] "+json.dumps({k:report[k] for k in
        ("candidate_mode","elf_sha256","itcm_occupied_extent_bytes","dtcm_static_extent_bytes",
         "heap_remaining_bytes","kernel_backend","depthwise","NPU_RTL")}))
