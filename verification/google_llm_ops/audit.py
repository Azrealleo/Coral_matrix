"""ELF/resource and native-reference audit. Never an RTL PASS by itself."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
from elftools.elf.elffile import ELFFile

from spec import CASES, SAMPLES, SCOPE, TOP, vectors

SIZES = {"llm_"+n: 4 for n in ("case", "status", "checked", "mismatches", "signature",
    "m", "k", "n", "rvv_calls", "guard_ok", "empty_cycles")}
SIZES.update(llm_scalar_cycles=16, llm_rvv_cycles=16, llm_x=1024, llm_w=4096,
             llm_scalar_out=4128, llm_rvv_out=4128)
LINKER = ("__stack_start__", "__stack_end__", "__heap_start__", "__heap_end__")


def inspect(data):
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 32 or not elf.little_endian or elf.header["e_machine"] != "EM_RISCV":
        raise ValueError("Requires RISC-V ELF32 little endian")
    segments = []
    for s in elf.iter_segments():
        if s["p_type"] != "PT_LOAD" or not s["p_memsz"]:
            continue
        start, size = int(s["p_paddr"]), int(s["p_memsz"])
        if (start != s["p_vaddr"] or s["p_filesz"] > size or not
            (0 <= start < start+size <= 256*1024 or
             0x01000000 <= start < start+size <= 0x01080000)):
            raise ValueError("ELF exceeds ITCM256/DTCM512 experimental map")
        segments.append(dict(address=start, bytes=size, file_bytes=int(s["p_filesz"]), flags=int(s["p_flags"])))
    entry = int(elf.header["e_entry"])
    if not any(p["flags"]&1 and p["address"] <= entry < p["address"]+p["bytes"] <= 256*1024 for p in segments):
        raise ValueError("Entry not in executable ITCM")
    table = elf.get_section_by_name(".symtab")
    if table is None:
        raise ValueError("Missing symbol table")
    wanted = set(SIZES) | set(LINKER)
    symbols = {s.name: dict(address=int(s["st_value"]), bytes=int(s["st_size"]))
               for s in table.iter_symbols() if s.name in wanted and s["st_shndx"] != "SHN_UNDEF"}
    if symbols.keys() != wanted:
        raise ValueError("Missing benchmark/linker symbols")
    addr = lambda name: symbols[name]["address"]
    if not (0x01000000 <= addr("__heap_start__") <= addr("__heap_end__") <=
            addr("__stack_start__") == 0x0107c000 and addr("__stack_end__") == 0x01080000):
        raise ValueError("Unexpected heap/16KiB stack geometry")
    for name, size in SIZES.items():
        start = addr(name)
        if (symbols[name]["bytes"] != size or start%4 or
            not 0x01000000 <= start < start+size <= addr("__heap_start__") or
            not any(p["address"] <= start < start+size <= p["address"]+p["bytes"] for p in segments)):
            raise ValueError("Invalid static symbol geometry: " + name)
    selector = addr("llm_case")
    if not any(s["p_type"] == "PT_LOAD" and s["p_paddr"] <= selector < selector+4 <= s["p_paddr"]+s["p_filesz"] and
               s.data()[selector-s["p_paddr"]:selector-s["p_paddr"]+4] == b"\xfe\xff\xff\xff"
               for s in elf.iter_segments()):
        raise ValueError("Selector must survive CRT BSS initialization")
    return dict(schema=1, scope=SCOPE, entry=entry, symbols=symbols, segments=segments,
        elf_sha256=hashlib.sha256(data).hexdigest(), itcm_kib=256, dtcm_kib=512,
        itcm_occupied_extent_bytes=max(p["address"]+p["bytes"] for p in segments if p["address"] < 0x01000000),
        dtcm_static_extent_bytes=addr("__heap_start__")-0x01000000,
        heap_remaining_bytes=addr("__heap_end__")-addr("__heap_start__"), NPU_RTL="NOT_RUN")


def checked_host(text):
    rows = re.findall(r"^\[LLM_LINEAR_HOST_REFERENCE\] case=(\d+) checked=(\d+) signature=(\d+) RVV=NOT_RUN$", text, re.M)
    if len(rows) != len(CASES) or re.search(r"\bFAILED\b|^FAIL[: ]", text, re.M):
        raise ValueError("Incomplete or failed host reference")
    for index, (case_id, checked, signature) in enumerate(rows):
        _, m, _, n = CASES[index]
        if (int(case_id), int(checked), int(signature)) != (index, SAMPLES*m*n, vectors(index)["signature"]):
            raise ValueError("Native/Python independent reference mismatch")


def checked_header(text):
    values = dict(re.findall(r"^#define\s+KP_(\w+)\s+(\S+)", text, re.M))
    expected = dict(xlen="32", itcmSizeKBytes="256", dtcmSizeKBytes="512", axi2IdBits="6",
        rvvVlen="128", fetchDataBits="128", lsuDataBits="128", enableFetchL0="false",
        enableRvv="true", enableVme="true", enableFloat="true", enableZfbfmin="true",
        enableVectorBf16="true", enableAxiInstructionFetch="true", enableVerification="false")
    if any(values.get(k) != v for k, v in expected.items()):
        raise ValueError("Generated RTL parameters differ from selected configuration")
    return expected


def configured(execroot, listing, basename):
    root = Path(execroot).resolve(strict=True)
    paths = set()
    for line in listing.splitlines():
        if not line.strip():
            continue
        path = Path(line.strip())
        if path.is_absolute() or ".." in path.parts or path.parts[0] != "bazel-out":
            raise ValueError("Unexpected configured output")
        resolved = (root/path).resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError("Configured output escaped execroot")
        if path.name == basename:
            paths.add(resolved)
    if len(paths) != 1:
        raise ValueError("Missing/ambiguous configured output: " + basename)
    return paths.pop()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    a = p.parse_args(); run = a.run
    roots = (run/"execution-root.txt").read_text().splitlines()
    if len(roots) != 1:
        raise ValueError("Expected one execution root")
    checked_host((run/"host.log").read_text())
    elf_path = configured(roots[0], (run/"elf-outputs.txt").read_text(), "probe_program.elf")
    rtl_listing = (run/"rtl-outputs.txt").read_text()
    header = configured(roots[0], rtl_listing, "V"+TOP+"_parameters.h")
    rtl = configured(roots[0], rtl_listing, TOP+".sv")
    parameters = checked_header(header.read_text())
    data = elf_path.read_bytes(); report = inspect(data)
    for name, content in (("probe_program.elf", data), ("parameters.h", header.read_bytes()),
        ("resources.json", (json.dumps(report, indent=2)+"\n").encode()),
        ("rtl-identity.json", (json.dumps(dict(top=TOP, parameters=parameters,
            rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest()), indent=2)+"\n").encode())):
        with (run/name).open("xb") as stream:
            stream.write(content)
    print("[LLM_LINEAR_ELF_AUDIT] "+json.dumps({k: report[k] for k in
        ("elf_sha256", "itcm_occupied_extent_bytes", "dtcm_static_extent_bytes", "heap_remaining_bytes", "NPU_RTL")}))
