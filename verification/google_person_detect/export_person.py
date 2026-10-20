"""Export new 256/512KiB RTL and the SAME measured ELF. No simulation here."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import sys
import tarfile

import check_host
import firmware_report
import portable
import prepare_person
from spec import ASSETS, DTCM_BASE, MODEL_NAME, MODEL_SHA256, UPSTREAM, checked_asset, sha

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "google_tcm_vcs"))
from package_lib import DEFINES, compilation_inputs, seal, zip_contents

PACKAGE = "tests/cocotb/person_detect_rtl_i256_d512"
MANIFEST = "person_detect_rtl_export_manifest.json"
TOP = portable.TOP
UPSTREAM_PY = ("coralnpu_test_utils/core_mini_axi_interface.py",
               "coralnpu_test_utils/backdoor.py",
               "coralnpu_test_utils/sim_backends/verilator_test_fixture.py",
               "coralnpu_test_utils/sim_backends/common_utils.py")


def build_text():
    return f'''# RTL export only. New capacity, NOT previously simulated RTL.
load("//rules:chisel.bzl", "chisel_cc_library")
load("//hdl/chisel/src/coralnpu:flags.bzl", "VME_CORE_MINI_AXI_COMMON_GEN_FLAGS", "VME_CORE_MINI_AXI_VOPTS")
chisel_cc_library(
    name = "rtl",
    chisel_lib = "//hdl/chisel/src/coralnpu:coralnpu",
    emit_class = "coralnpu.EmitCore",
    module_name = "{TOP}",
    verilog_file_path = "{TOP}.sv",
    extra_outs = ["V{TOP}_parameters.h", "{TOP}.zip"],
    gen_flags = ["--moduleName=VmeCoreMini", "--itcmSizeKBytes=256", "--dtcmSizeKBytes=512"] + VME_CORE_MINI_AXI_COMMON_GEN_FLAGS,
    vopts = VME_CORE_MINI_AXI_VOPTS,
)
'''


def evidence(root, assets, run):
    baseline = prepare_person.prepare(root, assets)
    if json.loads((run / "manifest.json").read_text()) != baseline:
        raise ValueError("Measured firmware run does not match installed baseline")
    if (run / "host-pass.log").read_text().strip() != "[PERSON_TFLM_NATIVE_HOST_TEST_PASS] NPU_RTL=NOT_RUN":
        raise ValueError("Native host test PASS evidence missing")
    host = check_host.checked_host_log((run / "host-test-command.log").read_text())
    recorded = (run / "host-reference.json.log").read_text().strip()
    marker = "[PERSON_TFLM_NATIVE_HOST_REFERENCE] "
    if not recorded.startswith(marker) or json.loads(recorded[len(marker):]) != host:
        raise ValueError("Recorded host reference changed")
    data = (run / "person_program.elf").read_bytes()
    report = firmware_report.inspect_elf(data)
    if json.loads((run / "resources.json").read_text()) != report:
        raise ValueError("Measured ELF or resource report changed")
    if report["candidate_itcm_kib_with_25pct_margin"] != 256:
        raise ValueError("This export requires the measured 256KiB ITCM candidate")
    if not 0 <= report["entry"] < 256 * 1024:
        raise ValueError("Entry does not fit selected ITCM")
    for segment in report["segments"]:
        start, size = segment["address"], segment["bytes"]
        if not (0 <= start < start + size <= 256 * 1024 or
                DTCM_BASE <= start < start + size <= DTCM_BASE + 512 * 1024):
            raise ValueError("Original ELF load segment exceeds chosen hardware")
    return host, report


def prepare(root, assets, run):
    evidence(root, assets, run)
    path = root / PACKAGE / "BUILD"
    content = build_text().encode()
    identity = dict(schema=1, upstream=UPSTREAM, itcm_kib=256, dtcm_kib=512,
                    hdl_top=TOP, baseline_manifest_sha256=portable.file_sha(root / prepare_person.MANIFEST),
                    files={PACKAGE + "/BUILD": sha(content)})
    marker = root / MANIFEST
    if marker.exists():
        if json.loads(marker.read_text()) != identity or path.read_bytes() != content:
            raise ValueError("Existing RTL export source differs; nothing overwritten")
    else:
        if path.parent.exists():
            raise ValueError("Unowned RTL package directory; nothing overwritten")
        path.parent.mkdir(parents=True)
        with path.open("xb") as stream:
            stream.write(content)
        with marker.open("x", encoding="utf-8") as stream:
            json.dump(identity, stream, indent=2)
            stream.write("\n")
    prepare_person.capacity.verify(root)
    print("[PERSON_RTL_EXPORT_SOURCE_VERIFIED] ITCM_KiB=256 DTCM_KiB=512 NPU_RTL=NOT_RUN")


def checked_header(text):
    values = dict(re.findall(r"^#define\s+KP_(\w+)\s+(\S+)", text, re.M))
    expected = dict(xlen="32", itcmSizeKBytes="256", dtcmSizeKBytes="512", axi2IdBits="6",
                    rvvVlen="128", fetchDataBits="128", lsuDataBits="128", enableFetchL0="false",
                    enableRvv="true", enableVme="true", enableFloat="true", enableZfbfmin="true",
                    enableVectorBf16="true", enableAxiInstructionFetch="true", enableVerification="false")
    if any(values.get(k) != v for k, v in expected.items()):
        raise ValueError("Generated hardware parameters differ from chosen configuration")
    return expected


def configured_outputs(execroot, listing):
    names = {TOP + ".sv", TOP + ".zip", "V" + TOP + "_parameters.h"}
    result = {}
    for line in listing.splitlines():
        if not line.strip():
            continue
        path = PurePosixPath(line.strip())
        if (path.is_absolute() or ".." in path.parts or "\\" in line or
                not path.parts or path.parts[0] != "bazel-out" or path.name not in names):
            raise ValueError("Unexpected configured RTL output")
        resolved = execroot.joinpath(*path.parts).resolve(strict=True)
        if not resolved.is_relative_to(execroot) or not resolved.is_file() or path.name in result:
            raise ValueError("Duplicate or escaped configured output")
        result[path.name] = resolved
    if set(result) != names:
        raise ValueError("Missing RTL/ZIP/parameter outputs")
    return result


def fixture_bytes(data):
    # Only the hash-checked official uncompressed 8-bit grayscale BMPs.
    if len(data) < 1078 or data[:2] != b"BM":
        raise ValueError("Unexpected BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    header, width, height, planes, bits, compression, length = struct.unpack_from("<IiiHHII", data, 14)
    if (header, width, height, planes, bits, compression, length) != (40, 96, 96, 1, 8, 0, 9216):
        raise ValueError("Unexpected official fixture geometry")
    # BMP's fourth palette byte is reserved and ignored by the official decoder.
    if any(data[54 + i * 4:57 + i * 4] != bytes([i, i, i]) for i in range(256)):
        raise ValueError("Unexpected grayscale palette")
    if offset != 1078 or len(data) != offset + 9216:
        raise ValueError("Truncated or extended fixture")
    rows = [data[offset + row * 96:offset + (row + 1) * 96] for row in range(96)]
    return b"".join(reversed(rows))  # BMP bottom-up; do NOT subtract 128.


def export(root, assets, run, job):
    prepare(root, assets, run)
    host, report = evidence(root, assets, run)
    roots = (job / "execution-root.txt").read_text().splitlines()
    if len(roots) != 1 or not Path(roots[0]).is_absolute():
        raise ValueError("Expected exactly one absolute execution root")
    inputs = configured_outputs(Path(roots[0]).resolve(strict=True), (job / "rtl-outputs.txt").read_text())
    before = {n: portable.file_sha(p) for n, p in inputs.items()}
    header = checked_header(inputs["V" + TOP + "_parameters.h"].read_text())
    contents = zip_contents(inputs[TOP + ".zip"])
    include_dirs = compilation_inputs(contents, TOP)
    output = job / "coral_person_i256_d512"
    archive = job / (output.name + ".tar.gz")
    checksum = job / (archive.name + ".sha256")
    if any(p.exists() for p in (output, archive, checksum)):
        raise ValueError("Existing output; nothing overwritten")
    output.mkdir()
    for name in ("rtl", "rtl_dependencies", "original", "firmware", "assets", "inputs",
                 "evidence", "dpi", "python"):
        (output / name).mkdir()
    for name, path in inputs.items():
        shutil.copy2(path, output / ("original" if name.endswith(".zip") else "rtl") / name)
    for name, data in contents.items():
        target = output / "rtl_dependencies" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    shutil.copy2(run / "person_program.elf", output / "firmware/person_program.elf")
    for name in ASSETS:
        data = checked_asset(assets, name)
        (output / "assets" / name).write_bytes(data)
        if name.endswith(".bmp"):
            (output / "inputs" / (Path(name).stem + ".int8.bin")).write_bytes(fixture_bytes(data))
    for name in UPSTREAM_PY:
        target = output / "python" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(prepare_person.capacity.git(root, "show", UPSTREAM + ":" + name))
    for name in ("sram_backdoor.cc", "sram_backdoor.h"):
        (output / "dpi" / name).write_bytes(prepare_person.capacity.git(root, "show", UPSTREAM + ":hdl/verilog/" + name))
    for name in ("manifest.json", "resources.json", "host-test-command.log", "host-reference.json.log",
                 "host-pass.log", "build.log"):
        shutil.copy2(run / name, output / "evidence" / name)
    for name in ("build.log", "build-command.txt", "rtl-outputs.txt", "execution-root.txt", "export_rtl.sh"):
        shutil.copy2(job / name, output / "evidence" / ("rtl-" + name))
    for name in (prepare_person.MANIFEST, MANIFEST, "tcm_capacity_manifest.json"):
        shutil.copy2(root / name, output / "evidence" / name)
    for name in ("portable.py", "spec.py", "firmware_report.py"):
        shutil.copy2(HERE / name, output / name)
    (output / "LICENSE").write_bytes(prepare_person.capacity.git(root, "show", UPSTREAM + ":LICENSE"))
    (output / "SOURCE-NOTICES.txt").write_text(
        "CoralNPU RTL: google-coral/coralnpu at " + UPSTREAM + " (Apache-2.0).\n"
        "Person Detection model and fixtures: TensorFlow Authors, tensorflow/tflite-micro at "
        + host["tflm_commit"] + " (Apache-2.0).\n"
        "The common Apache-2.0 license text is included as LICENSE.\n", encoding="utf-8")
    (output / "README.md").write_text(
        "# Person Detection RTL source export\n\n"
        "ITCM256KiB / DTCM512KiB, original firmware/model bytes unchanged.\n"
        "This is NOT an NPU inference PASS. A standalone model test runner is the next step; "
        "do not run the old TCM workset bench with this ELF.\n\n"
        "Read-only integrity check (outside this folder): `python -B portable.py .`\n"
        "Inputs are the original decoded BMP byte patterns (INT8); do not subtract128.\n"
        "Reference scores in manifest are [no_person, person], not host-log column order.\n"
        "Kernel backend is pinned TFLM INT8, not VME offload.\n", encoding="utf-8")
    if any(portable.file_sha(p) != before[n] for n, p in inputs.items()):
        raise ValueError("Generated input changed during export; retain but do not use partial output")
    evidence(root, assets, run)
    if portable.file_sha(output / "firmware/person_program.elf") != report["elf_sha256"]:
        raise ValueError("Copied ELF changed")
    seal(output, dict(schema=1, upstream=UPSTREAM, hdl_top=TOP, itcm_kib=256, dtcm_kib=512,
                      generated_utc=datetime.now(timezone.utc).isoformat(), generated_parameters=header,
                      defines=list(DEFINES), zip_include_dirs=include_dirs,
                      rtl_sha256=before[TOP + ".sv"], elf_sha256=report["elf_sha256"],
                      model_sha256=MODEL_SHA256, original_model_bytes_equal=True,
                      reference_scores_no_person_then_person={
                          "person": list(reversed(host["person_scores_person_then_no_person"])),
                          "no_person": list(reversed(host["no_person_scores_person_then_no_person"]))},
                      memory_map=dict(itcm=0, dtcm=DTCM_BASE, csr=0x02000000, external=0x20000000),
                      kernel_backend="pinned_TFLM_INT8_not_VME_offload",
                      validation="export_integrity_only_NOT_NPU_RTL_PASS", simulation="NOT_RUN"))
    portable.verify(output)
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(output, arcname=output.name)
    with checksum.open("x", encoding="utf-8") as stream:
        stream.write(portable.file_sha(archive) + "  " + archive.name + "\n")
    print("[PERSON_RTL_EXPORT_VERIFIED] same_measured_elf=true original_model=true NPU_RTL=NOT_RUN")
    print("[PERSON_RTL_PACKAGE_ARCHIVE] " + str(archive))
    print("[PERSON_RTL_PACKAGE_SHA256] " + portable.file_sha(archive))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "export"))
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--firmware-run", type=Path, required=True)
    parser.add_argument("--job", type=Path)
    args = parser.parse_args()
    common = [p.resolve(strict=True) for p in (args.upstream, args.assets, args.firmware_run)]
    if args.action == "prepare":
        prepare(*common)
    else:
        if args.job is None:
            parser.error("export requires --job")
        export(*common, args.job.resolve(strict=True))
