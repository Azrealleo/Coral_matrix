"""Audit new candidate ELF and operator symbols; not an RTL PASS."""
import argparse
import io
import json
from pathlib import Path, PurePosixPath
import sys
from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "google_person_detect"))
import firmware_report
from spec import DTCM_BASE

COMMON_COUNTERS = frozenset({"pd_vme_conv_calls", "pd_vme_fallback_calls",
                             "pd_vme_commands", "pd_vme_mismatches"})
VALIDATION_COUNTERS = frozenset({"pd_vme_validated_layers", "pd_vme_first_bad_index"})


def diagnostic_symbols(table, mode, static_end):
    if mode not in ("validate", "fast"):
        raise ValueError("Unknown candidate mode")
    if table is None:
        raise ValueError("Missing candidate symbol table")
    known = COMMON_COUNTERS | VALIDATION_COUNTERS
    # With PD_VME_VALIDATE=0 there are no references to the validation-only
    # variables. --gc-sections may legitimately discard those two definitions.
    # Keep all four counters used by the fast main() acceptance gate mandatory.
    required = known if mode == "validate" else COMMON_COUNTERS
    found = {}
    for symbol in table.iter_symbols():
        if symbol.name not in known or symbol["st_shndx"] == "SHN_UNDEF":
            continue
        value = dict(address=int(symbol["st_value"]), bytes=int(symbol["st_size"]))
        if symbol.name in found and found[symbol.name] != value:
            raise ValueError("Conflicting VME diagnostic symbol: " + symbol.name)
        found[symbol.name] = value
    missing = sorted(required - found.keys())
    invalid = sorted(name for name, value in found.items() if value["bytes"] != 4 or not
                     DTCM_BASE <= value["address"] < value["address"]+4 <= static_end)
    if missing or invalid:
        raise ValueError("VME diagnostic symbols: mode=" + mode +
                         " missing=" + str(missing) + " invalid=" + str(invalid))
    return found


def inspect(data, mode):
    if mode not in ("validate", "fast"):
        raise ValueError("Unknown candidate mode")
    report = firmware_report.inspect_elf(data)
    if any(s["address"] < DTCM_BASE and s["address"] + s["bytes"] > 256*1024
           for s in report["segments"]):
        raise ValueError("Candidate does not fit the existing 256KiB ITCM")
    table = ELFFile(io.BytesIO(data)).get_section_by_name(".symtab")
    found = diagnostic_symbols(table, mode, report["symbols"]["__heap_start__"]["address"])
    report.update(kernel_backend="VME_pointwise_INT8_reference_other_ops", candidate_mode=mode,
                  validation_executes_reference=(mode == "validate"), vme_symbols=found,
                  validation_symbols_not_linked=sorted(VALIDATION_COUNTERS - found.keys()),
                  NPU_RTL="NOT_RUN", itcm_selected_kib=256)
    return report


def configured_elf(root, listing, mode):
    root = Path(root).resolve(strict=True)
    paths = set()
    for line in listing.splitlines():
        if not line.strip():
            continue
        relative = PurePosixPath(line.strip())
        if (relative.is_absolute() or ".." in relative.parts or "\\" in line or
                not relative.parts or relative.parts[0] != "bazel-out" or
                relative.name != "person_vme_"+mode+".elf"):
            raise ValueError("Unexpected configured candidate output")
        path = root.joinpath(*relative.parts).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Configured output escaped execution root")
        paths.add(path)
    if len(paths) != 1:
        raise ValueError("Expected exactly one configured candidate ELF")
    return paths.pop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("validate", "fast"), required=True)
    parser.add_argument("--execution-root-file", type=Path, required=True)
    parser.add_argument("--outputs-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    roots = args.execution_root_file.read_text().splitlines()
    if len(roots) != 1 or not Path(roots[0]).is_absolute():
        raise ValueError("Expected one absolute execution root")
    data = configured_elf(roots[0], args.outputs_file.read_text(), args.mode).read_bytes()
    report = inspect(data, args.mode)
    args.output.mkdir(exist_ok=False)
    with (args.output / "person_program.elf").open("xb") as stream:
        stream.write(data)
    with (args.output / "resources.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("[PERSON_VME_ELF_AUDIT] " + json.dumps({k: report[k] for k in
          ("candidate_mode", "elf_sha256", "itcm_occupied_extent_bytes", "dtcm_static_extent_bytes",
           "heap_remaining_bytes", "kernel_backend", "NPU_RTL")}))
