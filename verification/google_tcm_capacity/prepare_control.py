#!/usr/bin/env python3
"""Add separate small-control packages; never alter stage1 source/manifest."""
import argparse
import json
from pathlib import Path
import re

from capacity_spec import CAPACITIES, DTCM_BASE, UPSTREAM
from control_spec import REPEATS, SCOPE, SYMBOL_SIZES, cases, check_layout, vector_hash
from prepare import build_text, checked_log as capacity_log, digest, git, verify as verify_capacity
from capacity_spec import checked_parameters

HERE = Path(__file__).resolve().parent
PACKAGE = "tests/cocotb/tcm_control"
MANIFEST = "tcm_control_manifest.json"
TOOLS = ("control_program.cc", "control_spec.py", "control_bench.py", "prepare_control.py")


def control_build(kib):
    # Reuse the exact stage1 hardware generator configuration, in a separate
    # package so none of its validated files/manifests need to be rewritten.
    text = build_text(kib)
    text = text.replace('name = "capacity",', 'name = "control",')
    text = text.replace('testcases = ["tcm_capacity_test"]', 'testcases = ["tcm_control_test"]')
    text = text.replace('test_module": ["capacity_bench.py"]', 'test_module": ["control_bench.py"]')
    text = text.replace('srcs = ["capacity_spec.py"]', 'srcs = ["capacity_spec.py", "control_spec.py"]')
    text = text.replace(f'"extra_env": ["TCM_DTCM_KIB={kib}"]',
                        f'"extra_env": ["TCM_DTCM_KIB={kib}", "COCOTB_USE_FRONTDOOR=1"]')
    text = text.replace('"deps": [":support",',
                        f'"data": ["//{PACKAGE}:control_program.elf"],\n'
                        '        "deps": ["@bazel_tools//tools/python/runfiles", ":support",')
    return text.replace("# Generated capacity-only experiment", "# Generated small-control experiment")


def expected_files(root):
    files = {PACKAGE + "/BUILD": b'''load("//rules:coralnpu_v2.bzl", "coralnpu_v2_binary")
package(default_visibility = ["//tests/cocotb/tcm_control:__subpackages__"])
# Deliberately identical ELF, stack and linker extent at every RTL capacity.
coralnpu_v2_binary(
    name = "control_program",
    srcs = ["control_program.cc"],
    hdrs = ["vme_test_utils.h"],
    copts = ["-O2"],
    itcm_size_kbytes = 8,
    dtcm_size_kbytes = 32,
    enable_vmem = False,
)
''', PACKAGE + "/control_program.cc": (HERE / "control_program.cc").read_bytes(),
             PACKAGE + "/vme_test_utils.h": git(root, "show", UPSTREAM + ":tests/cocotb/vme_test/vme_test_utils.h")}
    for kib in CAPACITIES:
        prefix = f"{PACKAGE}/d{kib}/"
        files[prefix + "BUILD"] = control_build(kib).encode()
        for name in ("capacity_spec.py", "control_spec.py", "control_bench.py"):
            files[prefix + name] = (HERE / name).read_bytes()
    return files


def stage1_evidence(root, kib):
    """Require actual complete RTL test log + parameters from this source."""
    manifest = json.loads((root / "tcm_capacity_manifest.json").read_text())
    for run in sorted(root.parent.glob(f"run_d{kib}.*"), reverse=True):
        try:
            if json.loads((run / "manifest.json").read_text()) != manifest:
                continue
            capacity_log((run / "test.log").read_text(), kib)
            checked_parameters((run / "parameters.h").read_text(), kib)
            return dict(directory=str(run), test_log_sha256=digest((run / "test.log").read_bytes()))
        except (OSError, ValueError, KeyError):
            continue
    raise ValueError(f"no matching stage1 RTL PASS evidence for DTCM {kib}KiB; old results preserved")


def prepare(root):
    verify_capacity(root)
    if (root / MANIFEST).exists():
        return verify(root)
    evidence = {str(k): stage1_evidence(root, k) for k in CAPACITIES}
    files = expected_files(root)
    if any((root / name).exists() for name in files):
        raise ValueError("existing control package without manifest; nothing overwritten")
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = dict(schema=1, upstream=UPSTREAM, scope=SCOPE,
                    stage1_manifest_sha256=digest((root / "tcm_capacity_manifest.json").read_bytes()),
                    stage1_pass_evidence=evidence,
                    files={name: digest(data) for name, data in files.items()},
                    tools={name: digest((HERE / name).read_bytes()) for name in TOOLS})
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return verify(root)


def verify(root):
    verify_capacity(root)
    manifest = json.loads((root / MANIFEST).read_text())
    if (manifest["schema"] != 1 or manifest["scope"] != SCOPE or manifest["upstream"] != UPSTREAM or
            manifest["stage1_manifest_sha256"] != digest((root / "tcm_capacity_manifest.json").read_bytes())):
        raise ValueError("control / base manifest mismatch")
    files = expected_files(root)
    if manifest["files"] != {name: digest(data) for name, data in files.items()}:
        raise ValueError("control tools / generated identity changed; do not overwrite old results")
    for name, sha in manifest["files"].items():
        if digest((root / name).read_bytes()) != sha:
            raise ValueError("control file changed: " + name)
    for name in TOOLS:
        if manifest["tools"].get(name) != digest((HERE / name).read_bytes()):
            raise ValueError("control tool changed: " + name)
    return manifest


def checked_control_log(text, kib):
    marker = "[GOOGLE_TCM_CONTROL] "
    rows = [json.loads(line.split(marker, 1)[1]) for line in text.splitlines() if marker in line]
    expected = cases()
    cocotb = re.findall(r"TESTS=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)\s+SKIP=(\d+)", text)
    check = f"[GOOGLE_TCM_CONTROL_CHECK] cases={len(expected)} repeats={REPEATS} passed"
    if (len(rows) != len(expected) * REPEATS or not cocotb or cocotb[-1] != ("1", "1", "0", "0")
            or text.count(check) != 1):
        raise ValueError("missing, duplicate or failed control results")
    identity = None
    summaries = []
    for name, a, b in expected:
        selected = [row for row in rows if row.get("case") == name]
        if len(selected) != REPEATS or sorted(row.get("repeat", -1) for row in selected) != list(range(REPEATS)):
            raise ValueError("wrong repetitions: " + name)
        counts = []
        for row in selected:
            k = a.shape[1]
            required = dict(status="PASS", dtcm_kib=kib, itcm_kib=8, K=k, M=16, N=16,
                            checked_elements=256, useful_macs=256*k,
                            active_matrix_bytes=32*k+1024, reserved_buffer_bytes=9344,
                            vector_sha256=vector_hash(a, b), scope=SCOPE,
                            input_schedule="host_frontdoor_preloaded_low_dtcm32k",
                            elf_loading="frontdoor", itcm_tail="full_8k_nop_before_elf")
            if type(row.get("schema")) is not int or row["schema"] != 1 or any(row.get(key) != v for key, v in required.items()):
                raise ValueError("wrong control identity: " + name)
            if not re.fullmatch("[0-9a-f]{64}", row.get("elf_sha256", "")):
                raise ValueError("missing ELF hash")
            check_layout(row["elf_load_segments"], row["elf_entry"], row["symbols"], SYMBOL_SIZES, DTCM_BASE)
            ident = (row["elf_sha256"], row["symbols"], row["elf_load_segments"], row["elf_entry"])
            if identity is not None and ident != identity:
                raise ValueError("ELF/layout changed between runs")
            identity = ident
            count = row.get("wait_for_halt_cycles")
            if type(count) is not int or count <= 0:
                raise ValueError("invalid cycle count")
            counts.append(count)
        if len(set(counts)) != 1:
            raise ValueError("nonrepeatable cycle count: " + name)
        summaries.append(dict(required, case=name, repeats=REPEATS, wait_for_halt_cycles=counts[0],
                              elf_sha256=identity[0]))
    return summaries, identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "verify"):
        p = sub.add_parser(command)
        p.add_argument("--upstream", required=True, type=Path)
    p = sub.add_parser("log")
    p.add_argument("--file", required=True, type=Path)
    p.add_argument("--kib", required=True, type=int, choices=CAPACITIES)
    p = sub.add_parser("compare")
    p.add_argument("--logs", required=True, type=Path, nargs="+")
    args = parser.parse_args()
    if args.command in ("prepare", "verify"):
        manifest = prepare(args.upstream.resolve()) if args.command == "prepare" else verify(args.upstream.resolve())
        print("[TCM_CONTROL_VERIFIED] upstream=" + manifest["upstream"])
    elif args.command == "log":
        rows, _ = checked_control_log(args.file.read_text(), args.kib)
        for row in rows:
            print("[TCM_CONTROL_SUMMARY] " + json.dumps(row, sort_keys=True))
    else:
        rows, identity, seen = [], None, set()
        for path in args.logs:
            text = path.read_text()
            marker = "[GOOGLE_TCM_CONTROL] "
            first = next(json.loads(line.split(marker, 1)[1]) for line in text.splitlines() if marker in line)
            kib = first["dtcm_kib"]
            if kib not in CAPACITIES or kib in seen:
                raise ValueError("duplicate/invalid comparison capacity")
            checked, current = checked_control_log(text, kib)
            if identity is not None and identity != current:
                raise ValueError("different ELF/layout: not a paired comparison")
            seen.add(kib)
            identity = current
            rows.extend(checked)
        if len(seen) < 2:
            raise ValueError("comparison needs at least two capacities")
        for row in rows:
            print("[TCM_CONTROL_COMPARE] " + json.dumps(row, sort_keys=True))


if __name__ == "__main__":
    main()
