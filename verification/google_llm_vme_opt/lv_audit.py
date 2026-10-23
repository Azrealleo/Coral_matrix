"""ELF/resource, parameter and native audits; NOT an RTL pass."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
from elftools.elf.elffile import ELFFile
import lv_spec as spec

SIZES={"lv_"+n:4 for n in ("case","status","checked","mismatches","signature","guard_ok","m","k","n",
    "rvv_calls","complete_calls","reuse_calls","prepack_calls","empty_cycles","prepack_cycles","complete_commands","reuse_commands")}
SIZES.update(lv_rvv_cycles=16,lv_complete_cycles=16,lv_reuse_cycles=16,lv_x=1024,lv_w=4096,
    lv_rvv_out=4128,lv_complete_out=4128,lv_reuse_out=4128,lv_complete_weights=4384,lv_reuse_weights=4384,lv_workspace=2080)
SIZES.update({"lv_"+n:4 for n in ("opt_complete_commands","opt_reuse_commands","opt_complete_calls",
    "opt_reuse_calls","opt_prepack_calls","opt_prepack_cycles","probe_cases","probe_checked","probe_signature",
    "probe_mismatches","probe_fail_case","probe_commands","probe_current_case","probe_step",
    "probe_first_element","probe_first_actual","probe_first_expected")})
SIZES.update(lv_opt_complete_cycles=16,lv_opt_reuse_cycles=16,lv_opt_complete_tiles=8,lv_opt_reuse_tiles=8,
    lv_probe_tiles=8,lv_opt_complete_out=4128,lv_opt_reuse_out=4128,
    lv_opt_complete_weights=4384,lv_opt_reuse_weights=4384,lv_opt_workspace=2080)
LINKER=("__stack_start__","__stack_end__","__heap_start__","__heap_end__")


def words(raw):
    """Walk real RV32+C instruction boundaries; never scan unaligned bytes."""
    result=[];offset=0
    while offset<len(raw):
        if offset+2>len(raw):raise ValueError('Truncated instruction halfword')
        half=int.from_bytes(raw[offset:offset+2],'little')
        if half&3!=3:offset+=2;continue
        if half&31==31 or offset+4>len(raw):raise ValueError('Unexpected long/truncated RV32 instruction')
        result.append(int.from_bytes(raw[offset:offset+4],'little'));offset+=4
    return result


def operations(code):
    found=set()
    for word in code:
        opcode=word&127;f3=(word>>12)&7;f6=(word>>26)&63;f7=word>>25
        if word==0xf28800f7:found.add('signed_A_unsigned_B_matrix')
        if word==0x5e456057:found.add('vector_to_tile_row')
        if word==0x43f56257:found.add('tile_row_to_vector')
        if opcode==0x07 and ((word>>26)&3)==2 and f3==0:found.add('vlse8')
        if opcode==0x27 and ((word>>26)&3)==2 and f3==6:found.add('vsse32')
        if opcode==0x27 and ((word>>26)&3)==0 and f3==0:found.add('vse8')
        if opcode==0x27 and ((word>>26)&3)==0 and f3==6:found.add('vse32')
        if opcode==0x57 and f3==4 and f6==11:found.add('vxor_vx')
        if opcode==0x57 and f3==6 and f6==49:found.add('signed_widen_add_vx')
        if opcode==0x57 and f3==7:
            if f7==0x41:found.add('msetmtype')
            elif f7==0x42:found.add('mset_dimension')
            else:found.add('ordinary_vset_clears_mtype')
    return found


def instruction_audit(elf):
    expected={
        'PrepareOptimizedWeights':{'vse8','vse32','signed_widen_add_vx'},
        'PackOptimizedInput':{'vlse8','vxor_vx','vse8'},
        'FastTileToRowMajor':{'vsse32','signed_A_unsigned_B_matrix','vector_to_tile_row',
            'tile_row_to_vector','msetmtype','mset_dimension'},
    }
    report={}
    for component,required in expected.items():
        functions=[];found=set()
        for symbol in elf.get_section_by_name('.symtab').iter_symbols():
            if component not in symbol.name or symbol['st_info']['type']!='STT_FUNC' or not symbol['st_size'] or not isinstance(symbol['st_shndx'],int):continue
            section=elf.get_section(symbol['st_shndx']);start=int(symbol['st_value'])-int(section['sh_addr'])
            size=int(symbol['st_size']);data=section.data()
            if not section['sh_flags']&4 or start<0 or start+size>len(data):raise ValueError('Invalid target function code: '+component)
            raw=data[start:start+size];ops=operations(words(raw));found.update(ops)
            if component=='FastTileToRowMajor' and 'ordinary_vset_clears_mtype' in ops:
                raise ValueError('Ordinary VSET would clear mtype inside direct tile path')
            functions.append(dict(symbol=symbol.name,address=int(symbol['st_value']),bytes=size,code_sha256=hashlib.sha256(raw).hexdigest()))
        if not functions or not required.issubset(found):raise ValueError('Actual target instructions missing: '+component+' '+str(sorted(required-found)))
        report[component]=dict(functions=functions,verified_operations=sorted(required))
    return dict(scope='static_real_ELF_instruction_presence_not_execution',components=report,
        direct_tile_ordinary_vset=False)


def inspect(data):
    elf=ELFFile(io.BytesIO(data))
    if elf.elfclass!=32 or not elf.little_endian or elf.header["e_machine"]!="EM_RISCV":raise ValueError("Requires RV32 little-endian ELF")
    segments=[]
    for p in elf.iter_segments():
        if p["p_type"]!="PT_LOAD" or not p["p_memsz"]:continue
        start,size=int(p["p_paddr"]),int(p["p_memsz"])
        if p["p_vaddr"]!=start or p["p_filesz"]>size or not (0<=start<start+size<=262144 or 0x01000000<=start<start+size<=0x01080000):
            raise ValueError("ELF outside ITCM256/DTCM512")
        segments.append(dict(address=start,bytes=size,file_bytes=int(p["p_filesz"]),flags=int(p["p_flags"])))
    entry=int(elf.header["e_entry"])
    if not any(p["flags"]&1 and p["address"]<=entry<p["address"]+p["bytes"]<=262144 for p in segments):raise ValueError("Bad ITCM entry")
    table=elf.get_section_by_name(".symtab")
    if table is None:raise ValueError("Missing ELF symbols")
    names=set(SIZES)|set(LINKER)
    symbols={s.name:dict(address=int(s["st_value"]),bytes=int(s["st_size"])) for s in table.iter_symbols() if s.name in names and s["st_shndx"]!="SHN_UNDEF"}
    if symbols.keys()!=names:raise ValueError("Missing benchmark/linker symbols")
    at=lambda n:symbols[n]["address"]
    if not 0x01000000<=at("__heap_start__")<=at("__heap_end__")<=at("__stack_start__")==0x0107c000 or at("__stack_end__")!=0x01080000:
        raise ValueError("Wrong heap/16KiB stack")
    for name,size in SIZES.items():
        start=at(name)
        if symbols[name]["bytes"]!=size or start%4 or not 0x01000000<=start<start+size<=at("__heap_start__") or not any(p["address"]<=start<start+size<=p["address"]+p["bytes"] for p in segments):
            raise ValueError("Wrong symbol geometry: "+name)
    selector=at("lv_case")
    if not any(p["p_type"]=="PT_LOAD" and p["p_paddr"]<=selector<selector+4<=p["p_paddr"]+p["p_filesz"] and
        p.data()[selector-p["p_paddr"]:selector-p["p_paddr"]+4]==b"\xfe\xff\xff\xff" for p in elf.iter_segments()):
        raise ValueError("Case selector must survive CRT initialization")
    # Static workspaces/output buffers must not overlap, even in a malformed ELF.
    intervals=sorted((symbols[n]["address"],symbols[n]["address"]+size,n) for n,size in SIZES.items())
    if any(a[1]>b[0] for a,b in zip(intervals,intervals[1:])):raise ValueError("Overlapping diagnostics/buffers")
    return dict(schema=1,scope=spec.SCOPE,entry=entry,symbols=symbols,segments=segments,
        elf_sha256=hashlib.sha256(data).hexdigest(),itcm_kib=256,dtcm_kib=512,
        itcm_occupied_extent_bytes=max(p["address"]+p["bytes"] for p in segments if p["address"]<0x01000000),
        dtcm_static_extent_bytes=at("__heap_start__")-0x01000000,heap_remaining_bytes=at("__heap_end__")-at("__heap_start__"),
        instruction_audit=instruction_audit(elf),NPU_RTL="NOT_RUN")


def checked_header(text):
    values=dict(re.findall(r"^#define\s+KP_(\w+)\s+(\S+)",text,re.M))
    expected=dict(xlen="32",itcmSizeKBytes="256",dtcmSizeKBytes="512",axi2IdBits="6",rvvVlen="128",
        fetchDataBits="128",lsuDataBits="128",enableFetchL0="false",enableRvv="true",enableVme="true",
        enableFloat="true",enableZfbfmin="true",enableVectorBf16="true",enableAxiInstructionFetch="true",enableVerification="false")
    if any(values.get(k)!=v for k,v in expected.items()):raise ValueError("Wrong generated hardware parameters")
    return expected


def configured(root,listing,name):
    root=Path(root).resolve(strict=True);result=set()
    for line in listing.splitlines():
        if not line.strip():continue
        p=Path(line.strip())
        if p.is_absolute() or ".." in p.parts or p.parts[0]!="bazel-out":raise ValueError("Unsafe configured output")
        actual=(root/p).resolve(strict=True)
        if not actual.is_relative_to(root):raise ValueError("Configured output escaped execroot")
        if p.name==name:result.add(actual)
    if len(result)!=1:raise ValueError("Missing/ambiguous configured output: "+name)
    return result.pop()


def audit(run):
    spec.checked_host((run/"host.log").read_text())
    roots=(run/"execution-root.txt").read_text().splitlines()
    if len(roots)!=1:raise ValueError("Expected one execution root")
    data=configured(roots[0],(run/"elf-outputs.txt").read_text(),"probe_program.elf").read_bytes()
    listing=(run/"rtl-outputs.txt").read_text();rtl=configured(roots[0],listing,spec.TOP+".sv")
    header=configured(roots[0],listing,"V"+spec.TOP+"_parameters.h");parameters=checked_header(header.read_text())
    if spec.sha(rtl)!=spec.RTL_SHA:raise ValueError("RTL differs from existing qualified server model; do not relabel")
    report=inspect(data)
    for name,raw in (("probe_program.elf",data),("parameters.h",header.read_bytes()),
        ("resources.json",(json.dumps(report,indent=2)+"\n").encode()),
        ("rtl-identity.json",(json.dumps(dict(rtl_sha256=spec.RTL_SHA,parameters=parameters),indent=2)+"\n").encode())):
        with (run/name).open("xb") as stream:stream.write(raw)
    print("[LLM_VME_OPT_ELF_AUDIT] "+json.dumps({k:report[k] for k in ("elf_sha256","itcm_occupied_extent_bytes","dtcm_static_extent_bytes","heap_remaining_bytes","NPU_RTL")}))
    print('[LLM_VME_OPT_TARGET_INSTRUCTIONS_VERIFIED] real_ELF=true execution=NOT_RUN direct_tile_ordinary_vset=false')


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--run",type=Path,required=True)
    audit(p.parse_args().run.resolve(strict=True))
