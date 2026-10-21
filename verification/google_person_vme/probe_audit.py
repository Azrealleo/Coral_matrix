"""Short arithmetic probe ELF audit; no pretrained-model/inference claim."""
import io
from elftools.elf.elffile import ELFFile
import hashlib

PROBE_SYMBOLS = ("pd_probe_status", "pd_probe_cases", "pd_probe_checked", "pd_probe_mismatches",
                 "pd_probe_commands", "pd_probe_first_expected", "pd_probe_first_actual",
                 "pd_probe_first_case", "pd_probe_signature")


def inspect(data):
    elf=ELFFile(io.BytesIO(data))
    if elf.elfclass!=32 or not elf.little_endian or elf.header["e_machine"]!="EM_RISCV":
        raise ValueError("Probe must be a RISC-V little-endian ELF32")
    entry=int(elf.header["e_entry"])
    segments=[]
    for s in elf.iter_segments():
        if s["p_type"]!="PT_LOAD" or not s["p_memsz"]:
            continue
        start,size=int(s["p_paddr"]),int(s["p_memsz"])
        if (start!=int(s["p_vaddr"]) or s["p_filesz"]>size or not
                (0<=start<start+size<=256*1024 or 0x01000000<=start<start+size<=0x01080000)):
            raise ValueError("Probe exceeds 256/512KiB address map")
        segments.append(dict(address=start,bytes=size,file_bytes=int(s["p_filesz"]),flags=int(s["p_flags"])))
    if not 0<=entry<256*1024 or not any(s["flags"]&1 and s["address"]<=entry<s["address"]+s["bytes"] for s in segments):
        raise ValueError("Probe entry is not executable")
    wanted=set(PROBE_SYMBOLS)|{"__stack_start__","__stack_end__","__heap_start__","__heap_end__"}
    table=elf.get_section_by_name(".symtab")
    if table is None: raise ValueError("Probe symbol table missing")
    symbols={s.name:dict(address=int(s["st_value"]),bytes=int(s["st_size"]))
             for s in table.iter_symbols() if s.name in wanted and s["st_shndx"]!="SHN_UNDEF"}
    if set(symbols)!=wanted: raise ValueError("Probe symbols missing: "+str(wanted-symbols.keys()))
    address=lambda n:symbols[n]["address"]
    if not (0x01000000<=address("__heap_start__")<=address("__heap_end__")<=address("__stack_start__")
            <address("__stack_end__")==0x01080000) or address("__stack_end__")-address("__stack_start__")!=16384:
        raise ValueError("Probe stack/heap geometry mismatch")
    for n in PROBE_SYMBOLS:
        s=symbols[n]
        if (s["bytes"]!=4 or not 0x01000000<=s["address"]<s["address"]+4<=address("__heap_start__") or
                not any(p["address"]<=s["address"]<s["address"]+4<=p["address"]+p["bytes"] for p in segments)):
            raise ValueError("Probe diagnostic outside static DTCM: "+n)
    return dict(schema=1,scope="short_VME_arithmetic_not_model_inference",entry=entry,
                elf_sha256=hashlib.sha256(data).hexdigest(),segments=segments,symbols=symbols,
                NPU_RTL="NOT_RUN")
