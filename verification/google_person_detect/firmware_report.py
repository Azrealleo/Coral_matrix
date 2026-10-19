"""Audit ELF resources. A linked ELF is NOT an NPU execution or RTL PASS."""
import argparse
import io
import json
from pathlib import Path, PurePosixPath

from elftools.elf.elffile import ELFFile

from spec import ARENA_BYTES, DTCM_BASE, DTCM_KIB, INPUT_BYTES, ITCM_LINK_KIB
from spec import MODEL_BYTES, MODEL_SHA256, STACK_BYTES, sha


def recommend_itcm(used):
    if not 0 < used <= ITCM_LINK_KIB * 1024:
        raise ValueError("ITCM occupied extent outside the link ceiling")
    capacity = 8
    while capacity * 1024 * 4 < used * 5 and capacity < ITCM_LINK_KIB:
        capacity *= 2
    return capacity if capacity * 1024 * 4 >= used * 5 else None


def resolve(execroot, listing):
    root = Path(execroot).resolve(strict=True)
    candidates = set()
    for row in listing.splitlines():
        if not row.strip():
            continue
        relative = PurePosixPath(row.strip())
        if (relative.is_absolute() or ".." in relative.parts or not relative.parts
                or relative.parts[0] != "bazel-out" or relative.name != "person_program.elf"):
            raise ValueError("Unexpected configured output path")
        path = root.joinpath(*relative.parts).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Configured output escapes the execution root")
        candidates.add(path)
    if len(candidates) != 1:
        raise ValueError("Expected exactly one configured person_program.elf")
    return candidates.pop()


def inspect_elf(data):
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 32 or not elf.little_endian or elf.header["e_machine"] != "EM_RISCV":
        raise ValueError("Expected little-endian RISC-V ELF32")
    entry = int(elf.header["e_entry"])
    if not 0 <= entry < ITCM_LINK_KIB * 1024:
        raise ValueError("Entry outside ITCM")
    segments = []
    for segment in elf.iter_segments():
        if segment["p_type"] != "PT_LOAD" or not segment["p_memsz"]:
            continue
        address, memory = int(segment["p_paddr"]), int(segment["p_memsz"])
        if address != segment["p_vaddr"] or segment["p_filesz"] > memory:
            raise ValueError("Unexpected load geometry")
        if not (0 <= address < address + memory <= ITCM_LINK_KIB * 1024 or
                DTCM_BASE <= address < address + memory <= DTCM_BASE + DTCM_KIB * 1024):
            raise ValueError("ELF load exceeds ITCM/DTCM limits")
        segments.append(dict(address=address, bytes=memory, file_bytes=int(segment["p_filesz"]),
                             flags=int(segment["p_flags"])))
    itcm = [s for s in segments if s["address"] < DTCM_BASE]
    if not itcm or not any(s["flags"] & 1 for s in itcm):
        raise ValueError("Missing executable ITCM segment")
    wanted = {"pd_model", "pd_input", "pd_output", "pd_tensor_arena", "pd_status",
              "pd_arena_used", "pd_invoke_cycles", "__heap_start__", "__heap_end__",
              "__stack_start__", "__stack_end__", "__stack_size"}
    symbols = {}
    symtab = elf.get_section_by_name(".symtab")
    if symtab is None:
        raise ValueError("Unstripped symbol table required for resource audit")
    for symbol in symtab.iter_symbols():
        if symbol.name in wanted and symbol["st_shndx"] != "SHN_UNDEF":
            value = dict(address=int(symbol["st_value"]), bytes=int(symbol["st_size"]))
            if symbol.name in symbols and symbols[symbol.name] != value:
                raise ValueError("Conflicting required symbol")
            symbols[symbol.name] = value
    if set(symbols) != wanted:
        raise ValueError("Missing firmware audit symbols: " + str(wanted - set(symbols)))

    def value(name):
        return symbols[name]["address"]

    def symbol_data(name, size):
        item = symbols[name]
        if item["bytes"] != size:
            raise ValueError("Symbol size mismatch: " + name)
        address = item["address"]
        if not DTCM_BASE <= address < address + size <= DTCM_BASE + DTCM_KIB * 1024:
            raise ValueError("Required data is not in DTCM: " + name)
        for segment in elf.iter_segments():
            if (segment["p_type"] == "PT_LOAD" and segment["p_paddr"] <= address
                    and address + size <= segment["p_paddr"] + segment["p_filesz"]):
                offset = address - segment["p_paddr"]
                return segment.data()[offset:offset + size]
        raise ValueError("Host-preloaded data would be CRT-zeroed BSS: " + name)

    if sha(symbol_data("pd_model", MODEL_BYTES)) != MODEL_SHA256:
        raise ValueError("Linked model bytes changed")
    symbol_data("pd_input", INPUT_BYTES)
    symbol_data("pd_output", 2)
    arena = symbols["pd_tensor_arena"]
    if arena["bytes"] != ARENA_BYTES or not DTCM_BASE <= arena["address"] < arena["address"] + ARENA_BYTES <= value("__heap_start__"):
        raise ValueError("Arena reservation outside static DTCM")
    if not (DTCM_BASE <= value("__heap_start__") <= value("__heap_end__") <= value("__stack_start__")
            < value("__stack_end__") == DTCM_BASE + DTCM_KIB * 1024):
        raise ValueError("Heap/stack geometry mismatch")
    if value("__stack_size") != STACK_BYTES or value("__stack_end__") - value("__stack_start__") != STACK_BYTES:
        raise ValueError("Unexpected stack reservation")
    for name, item in symbols.items():
        if name.startswith("pd_") and item["address"] + item["bytes"] > value("__heap_start__"):
            raise ValueError("Firmware static state overlaps heap/stack")
    occupied = max(s["address"] + s["bytes"] for s in itcm)
    return dict(schema=1, status="LINK_RESOURCE_AUDIT_PASS_NOT_INFERENCE",
                scope="ELF_only_not_runtime_arena_stack_or_RTL_validation", elf_sha256=sha(data),
                entry=entry, itcm_link_ceiling_kib=ITCM_LINK_KIB,
                itcm_occupied_extent_bytes=occupied, minimum_bank_aligned_itcm_kib=((occupied + 8191) // 8192) * 8,
                candidate_itcm_kib_with_25pct_margin=recommend_itcm(occupied),
                itcm_candidate_is_not_RTL_validated=True, dtcm_kib=DTCM_KIB,
                dtcm_static_extent_bytes=value("__heap_start__") - DTCM_BASE,
                heap_remaining_bytes=value("__heap_end__") - value("__heap_start__"),
                stack_reserved_bytes=STACK_BYTES, arena_reserved_bytes=ARENA_BYTES,
                arena_actual_used_bytes="NOT_RUN", actual_stack_high_water="NOT_RUN",
                model_sha256=MODEL_SHA256, original_model_bytes_equal=True,
                kernel_backend="pinned_TFLM_INT8_not_VME_offload", segments=segments, symbols=symbols)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-root-file", required=True, type=Path)
    parser.add_argument("--outputs-file", required=True, type=Path)
    parser.add_argument("--copy-to", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    roots = [r.strip() for r in args.execution_root_file.read_text().splitlines() if r.strip()]
    if len(roots) != 1 or not Path(roots[0]).is_absolute():
        raise ValueError("Expected one absolute execution root")
    if args.copy_to.exists() or args.report.exists():
        raise ValueError("Refusing to overwrite previous ELF/report")
    selected = resolve(roots[0], args.outputs_file.read_text())
    data = selected.read_bytes()
    report = inspect_elf(data)
    with args.copy_to.open("xb") as stream:
        stream.write(data)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("[PERSON_FIRMWARE_RESOURCE_REPORT] " + json.dumps({k: report[k] for k in
          ("status", "itcm_occupied_extent_bytes", "candidate_itcm_kib_with_25pct_margin",
           "dtcm_static_extent_bytes", "heap_remaining_bytes", "arena_reserved_bytes", "stack_reserved_bytes",
           "original_model_bytes_equal", "kernel_backend")}))


if __name__ == "__main__":
    main()
