"""Small firmware packet integrity and ELF-linked case data; no RTL assertions."""
import io
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from elftools.elf.elffile import ELFFile
if not (Path(__file__).resolve().parent/"portable_vme.py").is_file():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"google_person_vme"))
import portable_vme as common

sha=common.sha
ELF_SHA="b94e1da3b4f7f2693727395073e65f172344f15454bd01a7b7bb8c2832f259b2"
SHAPES=((2,16,8,16),(8,16,32,64),(24,9,128,256),(26,1,256,256),(28,1,256,2))
SCOPE="single_op_Invoke_includes_VME_pack_bias_correction_quantize_writeback_excludes_Prepare_and_checks"


def layout(data,cases):
    elf=ELFFile(io.BytesIO(data));table=elf.get_section_by_name(".symtab")
    symbols=[s for s in table.iter_symbols() if re.fullmatch(r"(?:_Z\d+)?kConvCases",s.name) and s["st_shndx"]!="SHN_UNDEF"]
    if len(symbols)!=1 or symbols[0]["st_size"]!=36*len(cases):raise ValueError("Unexpected RV32 ConvCase table")
    def read(address,size):
        for segment in elf.iter_segments():
            if segment["p_type"]=="PT_LOAD" and segment["p_paddr"]<=address<address+size<=segment["p_paddr"]+segment["p_filesz"]:
                offset=address-segment["p_paddr"];return segment.data()[offset:offset+size]
        raise ValueError("Case data not in file-backed ELF load segment")
    entries=read(int(symbols[0]["st_value"]),36*len(cases));result={}
    for i,case in enumerate(cases):
        model,input_data,model_bytes,input_bytes,op,m,k,n,_=struct.unpack_from("<9I",entries,36*i)
        if (op,m,k,n)!=(case["original_operator_index"],case["M"],case["K"],case["N"]) or input_bytes!=m*k:
            raise ValueError("ELF-selected case differs from measured source manifest")
        row={}
        for name,address,size,digest in (("model",model,model_bytes,case["derived_model_sha256"]),
                                       ("input",input_data,input_bytes,case["input_sha256"])):
            if address%16 or not 0x01000000<=address<address+size<=0x01080000:
                raise ValueError("Case fixtures are not aligned static DTCM")
            if hashlib.sha256(read(address,size)).hexdigest()!=digest:raise ValueError("ELF fixture bytes differ: "+name)
            row[name]=dict(address=address,bytes=size,sha256=digest)
        result[str(i)]=row
    return result


def verify(root):
    root=Path(root).resolve(strict=True);m=json.loads((root/"manifest.json").read_text())
    if (m.get("schema")!=1 or m.get("kind")!="person_conv_firmware_packet_v1" or
        m.get("elf_sha256")!=ELF_SHA or m.get("source_model_sha256")!=common.MODEL_SHA or
        m.get("upstream")!=common.UPSTREAM or m.get("itcm_kib")!=256 or m.get("dtcm_kib")!=512 or
        m.get("timing_scope")!=SCOPE or m.get("simulation")!="NOT_RUN" or len(m.get("cases",[]))!=5):
        raise ValueError("Wrong Conv packet identity")
    for i,(case,shape) in enumerate(zip(m["cases"],SHAPES)):
        if case["id"]!=i or (case["original_operator_index"],case["M"],case["K"],case["N"])!=shape:
            raise ValueError("Wrong Conv packet shape/index")
    for n in m["files"]:common.safe_name(n)
    if common.inventory(root)!=m["files"]:raise ValueError("Conv packet files missing/extra/changed")
    checks={}
    for line in (root/"SHA256SUMS").read_text().splitlines():
        digest,name=line.split("  ",1);common.safe_name(name)
        if name in checks:raise ValueError("Duplicate packet checksum")
        checks[name]=digest
    if checks!=dict(m["files"],**{"manifest.json":sha(root/"manifest.json")}):raise ValueError("Packet checksum index differs")
    if sha(root/"conv_program.elf")!=ELF_SHA:raise ValueError("Not the actually linked Conv ELF")
    return m
