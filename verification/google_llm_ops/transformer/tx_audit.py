"""Strict 256/512KiB FP32 suite audit; native/reference is not an RTL result."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
from elftools.elf.elffile import ELFFile
from tx_spec import CASES, SCOPE

SIZES={"tx_"+n:4 for n in ("case","status","kind","checked","mismatches","calls","guard_ok","first_bad","empty")}
SIZES.update(tx_scalar_cycles=16,tx_rvv_cycles=16,tx_x=4096,tx_w=4096,tx_v=4096,tx_scalar_out=4128,tx_rvv_out=4128)
LINKER=("__stack_start__","__stack_end__","__heap_start__","__heap_end__")


def checked_header(text):
    values=dict(re.findall(r"^#define\s+KP_(\w+)\s+(\S+)",text,re.M))
    expected=dict(xlen="32",itcmSizeKBytes="256",dtcmSizeKBytes="512",axi2IdBits="6",
        rvvVlen="128",fetchDataBits="128",lsuDataBits="128",enableFetchL0="false",
        enableRvv="true",enableVme="true",enableFloat="true",enableZfbfmin="true",
        enableVectorBf16="true",enableAxiInstructionFetch="true",enableVerification="false")
    if any(values.get(k)!=v for k,v in expected.items()):raise ValueError("Wrong generated RTL configuration")
    return expected


def inspect(data):
    elf=ELFFile(io.BytesIO(data))
    if elf.elfclass!=32 or not elf.little_endian or elf.header["e_machine"]!="EM_RISCV":
        raise ValueError("Requires little-endian RISC-V ELF32")
    segments=[]
    for p in elf.iter_segments():
        if p["p_type"]!="PT_LOAD" or not p["p_memsz"]:continue
        start,size=int(p["p_paddr"]),int(p["p_memsz"])
        if (p["p_vaddr"]!=start or p["p_filesz"]>size or not
            (0<=start<start+size<=262144 or 0x01000000<=start<start+size<=0x01080000)):
            raise ValueError("ELF exceeds actual 256/512KiB map")
        segments.append(dict(address=start,bytes=size,file_bytes=int(p["p_filesz"]),flags=int(p["p_flags"])))
    entry=int(elf.header["e_entry"])
    if not any(p["flags"]&1 and p["address"]<=entry<p["address"]+p["bytes"]<=262144 for p in segments):
        raise ValueError("Entry not executable in ITCM")
    table=elf.get_section_by_name(".symtab")
    if table is None:raise ValueError("Missing ELF symbols")
    wanted=set(SIZES)|set(LINKER)
    symbols={s.name:dict(address=int(s["st_value"]),bytes=int(s["st_size"])) for s in table.iter_symbols()
             if s.name in wanted and s["st_shndx"]!="SHN_UNDEF"}
    if symbols.keys()!=wanted:raise ValueError("Missing diagnostic/linker symbols")
    at=lambda n:symbols[n]["address"]
    if not (0x01000000<=at("__heap_start__")<=at("__heap_end__")<=at("__stack_start__")==0x0107c000 and
            at("__stack_end__")==0x01080000):raise ValueError("Wrong heap/stack geometry")
    for name,size in SIZES.items():
        start=at(name)
        if (symbols[name]["bytes"]!=size or start%4 or not 0x01000000<=start<start+size<=at("__heap_start__") or
            not any(p["address"]<=start<start+size<=p["address"]+p["bytes"] for p in segments)):
            raise ValueError("Bad symbol geometry: "+name)
    selector=at("tx_case")
    if not any(p["p_type"]=="PT_LOAD" and p["p_paddr"]<=selector<selector+4<=p["p_paddr"]+p["p_filesz"] and
        p.data()[selector-p["p_paddr"]:selector-p["p_paddr"]+4]==b"\xfe\xff\xff\xff" for p in elf.iter_segments()):
        raise ValueError("Case selector must survive CRT initialization")
    return dict(schema=1,scope=SCOPE,entry=entry,symbols=symbols,segments=segments,
        elf_sha256=hashlib.sha256(data).hexdigest(),itcm_kib=256,dtcm_kib=512,
        itcm_occupied_extent_bytes=max(p["address"]+p["bytes"] for p in segments if p["address"]<0x01000000),
        dtcm_static_extent_bytes=at("__heap_start__")-0x01000000,
        heap_remaining_bytes=at("__heap_end__")-at("__heap_start__"),NPU_RTL="NOT_RUN")


def checked_host(text):
    rows=re.findall(r"^\[TX_HOST_REFERENCE\] id=(\d+) name=(\S+) checked=(\d+) errors=0 RVV=NOT_RUN$",text,re.M)
    if len(rows)!=len(CASES) or re.search(r"\bFAILED\b|^FAIL[: ]",text,re.M):raise ValueError("Incomplete native reference")
    from tx_spec import fixture
    for i,(number,name,count) in enumerate(rows):
        if (int(number),name,int(count))!=(i,CASES[i][0],4*len(fixture(i)["y"])):
            raise ValueError("Wrong native reference case/shape")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--run",type=Path,required=True)
    a=p.parse_args();run=a.run
    # Import only the unchanged parent output/path/parameter checker.
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from audit import configured
    from spec import TOP
    checked_host((run/"host.log").read_text())
    roots=(run/"execution-root.txt").read_text().splitlines()
    if len(roots)!=1:raise ValueError("Expected one execroot")
    data=configured(roots[0],(run/"elf-outputs.txt").read_text(),"probe_program.elf").read_bytes()
    listing=(run/"rtl-outputs.txt").read_text()
    rtl=configured(roots[0],listing,TOP+".sv");header=configured(roots[0],listing,"V"+TOP+"_parameters.h")
    parameters=checked_header(header.read_text());report=inspect(data)
    for name,raw in (("probe_program.elf",data),("resources.json",(json.dumps(report,indent=2)+"\n").encode()),
        ("rtl-identity.json",(json.dumps(dict(rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest(),parameters=parameters),indent=2)+"\n").encode())):
        with (run/name).open("xb") as stream:stream.write(raw)
    print("[LLM_TX_ELF_AUDIT] "+json.dumps({n:report[n] for n in
        ("elf_sha256","itcm_occupied_extent_bytes","dtcm_static_extent_bytes","heap_remaining_bytes","NPU_RTL")}))
