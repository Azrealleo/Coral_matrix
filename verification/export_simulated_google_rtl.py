#!/usr/bin/env python3
"""Export existing Google VME simulation outputs without invoking Bazel.

Uses only the Python standard library. Original generated files are copied
byte-for-byte. Existing passing test logs are collected, not replayed.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import zipfile


TOP = "VmeCoreMiniAxi"
OUTPUT_NAMES = (TOP + ".sv", TOP + ".zip", "V" + TOP + "_parameters.h")
TARGET = "//hdl/chisel/src/coralnpu:vme_core_mini_axi_cc_library_verilog"
MODEL = "//tests/cocotb:vme_core_mini_axi_model"
DEFAULT_LOG = (
    "bazel-testlogs/tests/cocotb/vme_test/"
    "vme_matrix_shared_weight_batch_vme_matrix_shared_weight_batch_test/test.log"
)
EXPECTED_PARAMETERS = {
    "itcmSizeKBytes": "8", "dtcmSizeKBytes": "32", "rvvVlen": "128",
    "axi2IdBits": "6", "fetchDataBits": "128", "lsuDataBits": "128",
    "enableRvv": "true", "enableVme": "true", "enableFloat": "true",
    "enableZfbfmin": "true", "enableVectorBf16": "true",
    "enableAxiInstructionFetch": "true", "enableVerification": "false",
}
EXPECTED_DEFINES = {"USE_GENERIC", "VLEN_128", "TB_SUPPORT", "ZVE32F_ON", "ZVT_ON"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_path(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or ".." in path.parts
            or "\\" in name or ":" in name or '"' in name):
        raise ValueError("Unsafe package path: " + name)
    return path


def checked_parameters(text):
    actual = dict(re.findall(r"^#define\s+KP_(\w+)\s+(\S+)", text, re.M))
    for key, expected in EXPECTED_PARAMETERS.items():
        if actual.get(key) != expected:
            raise ValueError("Parameter {}={} (expected {}). Do not use prod outputs."
                             .format(key, actual.get(key), expected))
    return {key: actual[key] for key in EXPECTED_PARAMETERS}


def passing_log(text):
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    summaries = re.findall(r"TESTS=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)", text)
    if not summaries or any(int(failed) or not int(passed)
                            for _, passed, failed in summaries):
        raise ValueError("No passing cocotb summary, or a failing summary exists in test.log")
    total, passed, failed = map(int, summaries[-1])
    return {"tests": total, "pass": passed, "fail": failed}


def unpack_zip(archive, output):
    """Reject traversal, symlink entries, and Windows case collisions."""
    seen = set()
    with zipfile.ZipFile(archive) as stream:
        for item in stream.infolist():
            path = relative_path(item.filename)
            if item.is_dir():
                continue
            key = item.filename.casefold()
            if key in seen or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Duplicate/colliding or symlink ZIP member: " + item.filename)
            seen.add(key)
            destination = output.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(stream.read(item))


def compilation_inputs(rtl):
    includes, defines = [], []
    for raw in (rtl / "filelist.f").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", "#", "+incdir+")):
            continue
        if line.startswith("+define+"):
            defines.extend(line[len("+define+"):].split("+"))
            continue
        if line.startswith("+"):
            raise ValueError("Unexpected upstream filelist option: " + line)
        path = relative_path(line)
        if not rtl.joinpath(*path.parts).is_file():
            raise ValueError("Missing filelist source: " + line)
        if path.suffix.lower() not in (".sv", ".v", ".svh", ".h"):
            raise ValueError("Unexpected source type: " + line)
        if "rtl/" + line in includes:
            raise ValueError("Duplicate upstream source: " + line)
        includes.append("rtl/" + line)
    if set(defines) != EXPECTED_DEFINES:
        raise ValueError("Unexpected upstream macro configuration: " + repr(defines))
    if "rtl/Sram.v" not in includes or "rtl/" + TOP + ".sv" not in includes:
        raise ValueError("Missing original Sram or VmeCoreMiniAxi module")
    directories = {".", "rtl"}
    for name in includes:
        if Path(name).suffix.lower() in (".svh", ".h"):
            directories.add(str(PurePosixPath(name).parent))
    return includes, ["SYNTHESIS"] + defines, sorted(directories)


def json_file(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_checksums(root):
    lines = [sha256(path) + "  " + path.relative_to(root).as_posix()
             for path in sorted(root.rglob("*")) if path.is_file() and path.name != "SHA256SUMS"]
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify(root):
    root = Path(root).resolve()
    listed = set()
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        path = relative_path(name)
        if name in listed or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid checksum entry: " + name)
        destination = root.joinpath(*path.parts)
        destination.resolve().relative_to(root)
        if destination.is_symlink() or sha256(destination) != digest:
            raise ValueError("Checksum mismatch or symbolic link: " + name)
        listed.add(name)
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*")
              if path.is_file() and path.name != "SHA256SUMS"}
    if listed != actual:
        raise ValueError("Unlisted or missing package files: " + repr(actual ^ listed))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest["top"] != TOP or manifest["rtl_target"] != TARGET:
        raise ValueError("Wrong top or RTL target")
    checked_parameters((root / "original" / OUTPUT_NAMES[2]).read_text(encoding="utf-8"))
    for name in OUTPUT_NAMES:
        if sha256(root / "original" / name) != manifest["original_sha256"][name]:
            raise ValueError("Original generated file was changed: " + name)
    with zipfile.ZipFile(root / "original" / (TOP + ".zip")) as stream:
        expected_rtl = set()
        for item in stream.infolist():
            if item.is_dir():
                continue
            path = relative_path(item.filename)
            expected_rtl.add(item.filename)
            if (root / "rtl").joinpath(*path.parts).read_bytes() != stream.read(item):
                raise ValueError("Extracted RTL differs from original ZIP: " + item.filename)
        actual_rtl = {path.relative_to(root / "rtl").as_posix()
                      for path in (root / "rtl").rglob("*") if path.is_file()}
        if expected_rtl != actual_rtl:
            raise ValueError("Extracted RTL file set differs from original ZIP")
    includes, defines, directories = compilation_inputs(root / "rtl")
    wrapper = (root / "compile_units/all.sv").read_text(encoding="utf-8")
    if re.findall(r'^`include "([^"]+)"$', wrapper, re.M) != includes:
        raise ValueError("Compilation wrapper changed the upstream order")
    expected_filelist = (["+define+" + "+".join(defines)]
                         + ["+incdir+" + name for name in directories]
                         + ["compile_units/all.sv"])
    if (root / "filelist_synth.f").read_text(encoding="utf-8").splitlines() != expected_filelist:
        raise ValueError("Synthesis filelist does not match original ZIP")
    for entry in manifest["existing_test_logs"]:
        summary = passing_log(root.joinpath(*relative_path(entry["packaged_path"]).parts)
                              .read_text(encoding="utf-8", errors="replace"))
        if summary != entry["summary"]:
            raise ValueError("Collected test summary mismatch")
    if not manifest["existing_test_logs"]:
        raise ValueError("No existing passing test log collected")
    return {"top": TOP, "checked_files": len(listed), "original_rtl_unchanged": True,
            "enableAxiInstructionFetch": True, "existing_passing_logs": len(manifest["existing_test_logs"])}


def export(args):
    repo = Path(args.repo).resolve()
    generated = repo / "bazel-bin/hdl/chisel/src/coralnpu"
    before = {}
    for name in OUTPUT_NAMES:
        if not (generated / name).is_file():
            raise ValueError("Existing simulation output missing: {}. No build was attempted."
                             .format(generated / name))
        before[name] = sha256(generated / name)
    parameters = checked_parameters((generated / OUTPUT_NAMES[2]).read_text(encoding="utf-8"))
    model_build = (repo / "tests/cocotb/BUILD").read_text(encoding="utf-8")
    block = re.search(r'verilator_cocotb_model\(\s*name\s*=\s*"vme_core_mini_axi_model",(.*?)\n\)',
                      model_build, re.S)
    if not block or not re.search(r'verilog_source\s*=\s*"//hdl/chisel/src/coralnpu:VmeCoreMiniAxi.sv"', block[1]):
        raise ValueError("Existing simulation model no longer refers to the expected RTL target")
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain",
                                    "--untracked-files=no", "--", "."], text=True).strip()
    if dirty:
        raise ValueError("Tracked core checkout changes exist; export stopped without changing them:\n" + dirty)
    logs = []
    for value in args.test_log or [DEFAULT_LOG]:
        path = Path(value)
        path = path if path.is_absolute() else repo / path
        if not path.is_file():
            raise ValueError("Existing test.log missing: {}. Use --test-log for a previous passing VME log."
                             .format(path))
        logs.append((path, passing_log(path.read_text(encoding="utf-8", errors="replace")), sha256(path)))
    output = Path(args.output).resolve() if args.output else (
        Path.home() / ("coralnpu_sim_rtl_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    archive = output.with_name(output.name + ".tar.gz")
    if output.exists() or archive.exists():
        raise ValueError("Output already exists; nothing overwritten: " + str(output))
    output.mkdir(parents=True)
    for name in ["original", "rtl", "evidence", "compile_units"]:
        (output / name).mkdir()
    for name in OUTPUT_NAMES:
        shutil.copy2(generated / name, output / "original" / name)
        if sha256(output / "original" / name) != before[name]:
            raise ValueError("Generated output changed during copying: " + name)
    unpack_zip(output / "original" / (TOP + ".zip"), output / "rtl")
    includes, defines, directories = compilation_inputs(output / "rtl")
    (output / "compile_units/all.sv").write_text(
        "// Include-only wrapper. Original generated RTL is unchanged.\n"
        + "\n".join('`include "' + name + '"' for name in includes) + "\n", encoding="utf-8")
    (output / "filelist_synth.f").write_text(
        "\n".join(["+define+" + "+".join(defines)]
                  + ["+incdir+" + name for name in directories] + ["compile_units/all.sv"]) + "\n",
        encoding="utf-8")
    tcl = "set handoff_top {" + TOP + "}\n"
    for key, values in [("defines", defines), ("include_dirs", directories), ("sources", ["compile_units/all.sv"])]:
        if any("{" in value or "}" in value for value in values):
            raise ValueError("Unsupported Tcl path")
        tcl += "set handoff_" + key + " [list " + " ".join("{" + value + "}" for value in values) + "]\n"
    (output / "dc_sources.tcl").write_text(tcl, encoding="utf-8")
    evidence = []
    for index, (path, summary, digest) in enumerate(logs):
        name = "evidence/test_{:02d}.log".format(index)
        shutil.copy2(path, output / name)
        if sha256(output / name) != digest:
            raise ValueError("Test log changed during export")
        evidence.append({"original_path": str(path), "packaged_path": name,
                         "sha256": digest, "summary": summary})
    shutil.copy2(repo / "tests/cocotb/BUILD", output / "evidence/tests_cocotb_BUILD.txt")
    shutil.copy2(repo / "hdl/chisel/src/coralnpu/BUILD", output / "evidence/rtl_generation_BUILD.txt")
    shutil.copy2(repo / "LICENSE", output / "LICENSE")
    shutil.copy2(Path(__file__).with_name("HANDOFF-simulated-rtl.md"), output / "HANDOFF.md")
    shutil.copy2(Path(__file__), output / "verify_export.py")
    for name in OUTPUT_NAMES:
        if sha256(generated / name) != before[name]:
            raise ValueError("Active build changed generated outputs; stop it and export again")
    json_file(output / "manifest.json", {
        "format_version": 1, "top": TOP, "rtl_target": TARGET, "simulation_model": MODEL,
        "export_mode": "copy_existing_simulation_outputs_without_rebuild",
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "checkout_revision_at_export": revision,
        "revision_note": "Current checkout revision, not proof of the original generation-time revision.",
        "generated_parameters": parameters, "original_sha256": before,
        "existing_test_logs": evidence, "functional_tests_rerun": False,
        "ram": {"itcm_bytes": 8192, "dtcm_bytes": 32768, "blocks": 5,
                "block_depth": 512, "width_bits": 128, "ports": "1RW", "byte_mask_bits": 16},
        "synthesis_defines": defines, "include_dirs": directories,
        "dc_synthesis": "not_run", "gate_level_simulation": "not_run",
    })
    write_checksums(output)
    result = verify(output)
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(output, arcname=output.name)
    print("[SIM_RTL_EXPORT_VERIFIED] " + json.dumps(result, sort_keys=True))
    print("[SIM_RTL_EXPORT_DIRECTORY] " + str(output))
    print("[SIM_RTL_EXPORT_ARCHIVE] {} sha256={}".format(archive, sha256(archive)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="Existing coralnpu-google checkout, not the parent monorepo")
    parser.add_argument("--output", help="New output directory (default: unique timestamp in home directory)")
    parser.add_argument("--test-log", action="append", help="Existing passing VME test.log; repeat to collect more")
    parser.add_argument("--verify", type=Path, help="Verify a previously exported package, without exporting")
    args = parser.parse_args()
    if not args.verify and not args.repo:
        parser.error("--repo is required when exporting")
    try:
        if args.verify:
            print("[SIM_RTL_EXPORT_VERIFIED] " + json.dumps(verify(args.verify), sort_keys=True))
        else:
            export(args)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        parser.exit(1, "[SIM_RTL_EXPORT_ERROR] {}\n".format(error))


if __name__ == "__main__":
    main()
