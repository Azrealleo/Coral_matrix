#!/usr/bin/env python3
"""Configure a fresh Linux upstream clone. Never patch the team's SoC repo."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from capacity_spec import CAPACITIES, DTCM_BASE, CSR_BASE, PATCHES, TEAM, UPSTREAM
from capacity_spec import checked_parameters, geometry

HERE = Path(__file__).resolve().parent
MANIFEST = "tcm_capacity_manifest.json"


def git(root, *args, data=None):
    return subprocess.check_output(["git", "-C", str(root), *args], input=data)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def experiment_sources(core, linker):
    """Change generator address configuration only; preserve all core logic."""
    begin = core.index("  val memoryRegions =\n", core.index("object EmitCore"))
    end = core.index("  // The core module must be created", begin)
    old = core[begin:end]
    if "MemoryRegions.default" not in old or "MemoryRegions.highmem" not in old:
        raise ValueError("unexpected EmitCore memory configuration")
    replacement = f"""  // Single-core TCM capacity EXPERIMENT; not the Cheshire address map.
  val memoryRegions = Seq(
    new MemoryRegion(0x00000000, p.itcmSizeKBytes * 1024, MemoryRegionType.IMEM),
    new MemoryRegion(0x{DTCM_BASE:08x}, p.dtcmSizeKBytes * 1024, MemoryRegionType.DMEM),
    new MemoryRegion(0x{CSR_BASE:08x}, 0x1000, MemoryRegionType.Peripheral)
  )

"""
    for old_origin in ('dtcm_origin_default = "0x00010000"',
                       'dtcm_origin_highmem = "0x00100000"'):
        if linker.count(old_origin) != 1:
            raise ValueError("unexpected linker origin")
        linker = linker.replace(old_origin,
                                old_origin.split("=")[0] + f'= "0x{DTCM_BASE:08x}"')
    return core[:begin] + replacement + core[end:], linker


def build_text(kib):
    g = geometry(kib)
    top = g["hdl_top"]
    return f'''# Generated capacity-only experiment, upstream {UPSTREAM}.
load("//rules:chisel.bzl", "chisel_cc_library")
load("//rules:coco_tb.bzl", "cocotb_test_suite", "verilator_cocotb_model")
load("//hdl/chisel/src/coralnpu:flags.bzl", "VME_CORE_MINI_AXI_COMMON_GEN_FLAGS", "VME_CORE_MINI_AXI_VOPTS")
load("//tests/cocotb:build_defs.bzl", "VERILATOR_BUILD_ARGS")
load("@rules_python//python:defs.bzl", "py_library")

chisel_cc_library(
    name = "rtl",
    chisel_lib = "//hdl/chisel/src/coralnpu:coralnpu",
    emit_class = "coralnpu.EmitCore",
    module_name = "{top}",
    verilog_file_path = "{top}.sv",
    extra_outs = ["V{top}_parameters.h", "{top}.zip"],
    gen_flags = ["--moduleName=VmeCoreMini", "--itcmSizeKBytes=8", "--dtcmSizeKBytes={kib}"] + VME_CORE_MINI_AXI_COMMON_GEN_FLAGS,
    vopts = VME_CORE_MINI_AXI_VOPTS,
)
verilator_cocotb_model(
    name = "model",
    hdl_toplevel = "{top}",
    cflags = VERILATOR_BUILD_ARGS + ["-DZVT_ON", "-DZVTBF16FMM_ON"],
    verilog_source = ":{top}.sv",
    trace = False,
    deps = ["//hdl/verilog:sram_backdoor"],
)
py_library(name = "support", srcs = ["capacity_spec.py"])
cocotb_test_suite(
    name = "capacity",
    simulators = ["verilator"],
    testcases = ["tcm_capacity_test"],
    verilator_model = ":model",
    tests_kwargs = {{
        "hdl_toplevel": "{top}",
        "test_module": ["capacity_bench.py"],
        "waves": False,
        "seed": "137",
        "size": "large",
        "extra_env": ["TCM_DTCM_KIB={kib}"],
        "deps": [":support", "//coralnpu_test_utils:core_mini_axi_sim_interface", "//coralnpu_test_utils/sim_backends:verilator_test_fixture"],
    }},
)
'''


def verify(root):
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if git(root, "rev-parse", "HEAD").decode().strip() != UPSTREAM:
        raise ValueError("upstream revision changed")
    if digest(git(root, "diff", "--binary")) != manifest["tracked_diff_sha256"]:
        raise ValueError("tracked experiment source changed")
    for path, expected in manifest["files"].items():
        if digest((root / path).read_bytes()) != expected:
            raise ValueError("experiment file changed: " + path)
    for name in ("capacity_spec.py", "capacity_bench.py", "prepare.py"):
        if digest((HERE / name).read_bytes()) != manifest["tool_sha256"][name]:
            raise ValueError("tool changed; use a fresh experiment directory")
    if (root / ".bazelrc.user").exists():
        raise ValueError("unexpected hidden user Bazel config")
    return manifest


def prepare(root, team):
    if git(root, "rev-parse", "HEAD").decode().strip() != UPSTREAM:
        raise ValueError("requires exact upstream " + UPSTREAM)
    if git(root, "status", "--porcelain").strip():
        raise ValueError("requires a NEW clean upstream clone; nothing changed")
    if (root / MANIFEST).exists() or (root / ".bazelrc.user").exists():
        raise ValueError("refusing existing experiment/hidden Bazel config")
    core_path = "hdl/chisel/src/coralnpu/Core.scala"
    linker_path = "rules/linker.bzl"
    core = (root / core_path).read_text(encoding="utf-8")
    linker = (root / linker_path).read_text(encoding="utf-8")
    new_core, new_linker = experiment_sources(core, linker)
    # Resolve patches from the pinned team commit, not its floating HEAD.
    patches = []
    for path, sha in PATCHES.items():
        data = git(team, "show", TEAM + ":" + path)
        if digest(data) != sha:
            raise ValueError("team patch hash mismatch: " + path)
        git(root, "apply", "--check", "-", data=data)
        patches.append(data)
    generated = {}
    for kib in CAPACITIES:
        package = geometry(kib)["package"]
        generated[package + "/BUILD"] = build_text(kib).encode()
        for name in ("capacity_spec.py", "capacity_bench.py"):
            generated[package + "/" + name] = (HERE / name).read_bytes()
    if any((root / path).exists() for path in generated):
        raise ValueError("refusing existing generated files")
    for data in patches:
        git(root, "apply", "-", data=data)
    # Mechanical, checked rewrites only in this explicitly supplied clone.
    (root / core_path).write_text(new_core, encoding="utf-8", newline="\n")
    (root / linker_path).write_text(new_linker, encoding="utf-8", newline="\n")
    for path, data in generated.items():
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    tracked = (core_path, linker_path,
               "hdl/chisel/src/coralnpu/CoreAxiCSR.scala",
               "third_party/cvfpu/0009-Rebalance-fpnew-fma-pipeline-stages.patch")
    manifest = dict(schema=1, upstream=UPSTREAM, team=TEAM,
                    scope="single_core_capacity_geometry_not_performance",
                    capacities=[geometry(k) for k in CAPACITIES], patches=PATCHES,
                    tracked_diff_sha256=digest(git(root, "diff", "--binary")),
                    files={p: digest((root / p).read_bytes())
                           for p in (*tracked, *generated)},
                    tool_sha256={n: digest((HERE / n).read_bytes())
                                 for n in ("capacity_spec.py", "capacity_bench.py", "prepare.py")})
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify(root)
    return manifest


def checked_log(text, kib):
    marker = "[GOOGLE_TCM_CAPACITY] "
    rows = [json.loads(line.split(marker, 1)[1]) for line in text.splitlines() if marker in line]
    summaries = re.findall(r"TESTS=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)\s+SKIP=(\d+)", text)
    if len(rows) != 1 or not summaries or summaries[-1] != ("1", "1", "0", "0"):
        raise ValueError("missing/failed cocotb result")
    g = geometry(kib)
    for key, value in g.items():
        if rows[0].get(key) != value:
            raise ValueError("wrong geometry: " + key)
    if (rows[0].get("checked_words") != 3 * g["dtcm_banks"] + 2 or
            rows[0].get("checked_bytes") != 16 * (3 * g["dtcm_banks"] + 2) or
            rows[0].get("byte_mask_cases") != 2 or
            rows[0].get("scope") != "frontdoor_geometry_not_performance" or
            rows[0].get("status") != "PASS" or type(rows[0].get("schema")) is not int or
            rows[0].get("schema") != 1 or
            "[GOOGLE_TCM_CAPACITY_CHECK] passed" not in text):
        raise ValueError("incomplete RAM checks")
    return rows[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--upstream", required=True, type=Path)
        if name == "prepare":
            p.add_argument("--team-git", required=True, type=Path)
    p = sub.add_parser("header")
    p.add_argument("--file", required=True, type=Path)
    p.add_argument("--kib", required=True, type=int, choices=CAPACITIES)
    p = sub.add_parser("log")
    p.add_argument("--file", required=True, type=Path)
    p.add_argument("--kib", required=True, type=int, choices=CAPACITIES)
    args = parser.parse_args()
    if args.command in ("prepare", "verify"):
        root = args.upstream.resolve()
        result = prepare(root, args.team_git.resolve()) if args.command == "prepare" else verify(root)
        print("[TCM_EXPERIMENT_VERIFIED] upstream=" + result["upstream"])
    elif args.command == "header":
        result = checked_parameters(args.file.read_text(encoding="utf-8"), args.kib)
        print("[TCM_GENERATED_PARAMETERS] " + json.dumps(result, sort_keys=True))
    else:
        text = args.file.read_text(encoding="utf-8")
        print("[TCM_CAPACITY_SUMMARY] " + json.dumps(checked_log(text, args.kib), sort_keys=True))


if __name__ == "__main__":
    main()
