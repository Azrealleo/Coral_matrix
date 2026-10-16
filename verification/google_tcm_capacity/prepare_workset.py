#!/usr/bin/env python3
"""Install separate fixed-order capacity-reuse tests, preserving both baselines."""
import argparse
import json
from pathlib import Path
import re

from capacity_spec import CAPACITIES, UPSTREAM
from prepare import digest, git
from prepare_control import checked_control_log, control_build, verify as verify_control
from workset_spec import (DELAYS, EXT_BYTES, K, REPEATS, ROUNDS, SCOPE, STRATEGIES,
                          SYMBOL_SIZES, TILE_CHOICES, check_elf_layout, plan, vectors)

HERE = Path(__file__).resolve().parent
PACKAGE = "tests/cocotb/tcm_workset"
MANIFEST = "tcm_workset_manifest.json"
TOOLS = ("workset_program.cc", "workset_spec.py", "workset_bench.py",
         "workset_axi_probe.py", "prepare_workset.py")


def workset_build(kib):
    text = control_build(kib)
    for old, new in (("tcm_control", "tcm_workset"), ("control_program", "workset_program"),
                     ("control_spec", "workset_spec"), ("control_bench", "workset_bench"),
                     ('name = "control",', 'name = "workset",')):
        text = text.replace(old, new)
    text = text.replace('"workset_spec.py"]', '"workset_spec.py", "workset_axi_probe.py"]')
    text = text.replace('"size": "large",', '"size": "enormous", "timeout": "eternal",')
    return text.replace("# Generated small-control experiment", "# Generated fixed-order workset experiment")


def expected_files(root):
    common = '''load("//rules:coralnpu_v2.bzl", "coralnpu_v2_binary")
package(default_visibility = ["//tests/cocotb/tcm_workset:__subpackages__"])
coralnpu_v2_binary(
    name = "workset_program", srcs = ["workset_program.cc"], hdrs = ["vme_test_utils.h"],
    copts = ["-O2"], itcm_size_kbytes = 8, dtcm_size_kbytes = 16,
    stack_size_bytes = 1024, enable_vmem = False,
)
'''
    files = {PACKAGE + "/BUILD": common.encode(),
             PACKAGE + "/workset_program.cc": (HERE / "workset_program.cc").read_bytes(),
             PACKAGE + "/vme_test_utils.h": git(root, "show", UPSTREAM + ":tests/cocotb/vme_test/vme_test_utils.h")}
    for kib in CAPACITIES:
        prefix = f"{PACKAGE}/d{kib}/"
        files[prefix + "BUILD"] = workset_build(kib).encode()
        for name in ("capacity_spec.py", "workset_spec.py", "workset_axi_probe.py", "workset_bench.py"):
            files[prefix + name] = (HERE / name).read_bytes()
    return files


def control_evidence(root):
    source_manifest = json.loads((root / "tcm_control_manifest.json").read_text())
    result, common_identity = {}, None
    for kib in CAPACITIES:
        chosen = None
        for run in sorted(root.parent.glob(f"control_d{kib}.*"), reverse=True):
            try:
                if json.loads((run / "manifest.json").read_text()) != source_manifest:
                    continue
                _, identity = checked_control_log((run / "test.log").read_text(), kib)
                chosen = dict(directory=str(run), test_log_sha256=digest((run / "test.log").read_bytes()))
                break
            except (OSError, ValueError, KeyError):
                continue
        if chosen is None:
            raise ValueError(f"missing matching small-control PASS for {kib}KiB")
        if common_identity is not None and common_identity != identity:
            raise ValueError("small-control ELF/layout mismatch across capacities")
        common_identity = identity
        result[str(kib)] = chosen
    return result


def prepare(root):
    verify_control(root)
    if (root / MANIFEST).exists():
        return verify(root)
    evidence = control_evidence(root)
    files = expected_files(root)
    if any((root / name).exists() for name in files):
        raise ValueError("existing workset files without manifest; nothing overwritten")
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = dict(schema=1, upstream=UPSTREAM, scope=SCOPE,
                    control_manifest_sha256=digest((root / "tcm_control_manifest.json").read_bytes()),
                    control_pass_evidence=evidence, files={n: digest(b) for n, b in files.items()},
                    tools={n: digest((HERE / n).read_bytes()) for n in TOOLS})
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return verify(root)


def verify(root):
    verify_control(root)
    manifest = json.loads((root / MANIFEST).read_text())
    if (manifest["schema"] != 1 or manifest["upstream"] != UPSTREAM or manifest["scope"] != SCOPE or
            manifest["control_manifest_sha256"] != digest((root / "tcm_control_manifest.json").read_bytes())):
        raise ValueError("workset/base identity mismatch")
    files = expected_files(root)
    if manifest["files"] != {n: digest(b) for n, b in files.items()}:
        raise ValueError("workset generator changed; old results preserved")
    for name, sha in manifest["files"].items():
        if digest((root / name).read_bytes()) != sha:
            raise ValueError("workset file changed: " + name)
    for name in TOOLS:
        if manifest["tools"].get(name) != digest((HERE / name).read_bytes()):
            raise ValueError("workset tool changed: " + name)
    return manifest


def checked_log(text, kib, tiles, delay):
    marker = "[GOOGLE_TCM_WORKSET] "
    rows = [json.loads(line.split(marker, 1)[1]) for line in text.splitlines() if marker in line]
    finish = f"[GOOGLE_TCM_WORKSET_CHECK] tiles={tiles} strategies=2 repeats={REPEATS} passed"
    summaries = re.findall(r"TESTS=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)\s+SKIP=(\d+)", text)
    if (len(rows) != REPEATS * 2 or text.count(finish) != 1 or not summaries or
            summaries[-1] != ("1", "1", "0", "0")):
        raise ValueError("missing/failed/duplicate workset results")
    vector_sha = vectors(tiles)[3]
    result, identity = [], None
    for strategy in STRATEGIES:
        config = plan(kib, tiles, strategy)
        selected = [r for r in rows if r.get("strategy") == strategy]
        if len(selected) != REPEATS or sorted(r.get("repeat", -1) for r in selected) != list(range(REPEATS)):
            raise ValueError("incorrect repetitions")
        signature = None
        for row in selected:
            required = dict(config, status="PASS", itcm_kib=8, read_delay_cycles=delay,
                            scope=SCOPE, vector_sha256=vector_sha, external_memory_bytes=EXT_BYTES,
                            elf_loading="frontdoor", input_schedule="round_outer_weight_tile_inner_outputs_external",
                            timing="cold_start_copies_compute_output_included_host_init_excluded")
            if type(row.get("schema")) is not int or row["schema"] != 1 or any(row.get(k) != v for k, v in required.items()):
                raise ValueError("wrong workset identity/plan")
            if not re.fullmatch("[0-9a-f]{64}", row.get("elf_sha256", "")):
                raise ValueError("missing ELF hash")
            check_elf_layout(row["elf_entry"], row["elf_load_segments"], row["symbols"], SYMBOL_SIZES)
            current = (row["elf_sha256"], row["elf_entry"], row["elf_load_segments"], row["symbols"])
            if identity is not None and current != identity:
                raise ValueError("ELF/layout changed")
            identity = current
            counters, axi, rounds, wait = row["csr_counters"], row["axi"], row["round_cycles"], row["wait_for_halt_cycles"]
            numeric = [wait, *counters.values(), *axi.values(), *rounds]
            if any(type(v) is not int or v < 0 for v in numeric) or wait <= 0:
                raise ValueError("invalid numeric counter")
            for prefix, key in (("input", "input_read_bytes"), ("weight", "weight_read_bytes"),
                                ("output", "output_write_bytes")):
                if counters["ws_" + prefix + "_bytes"] != config[key] or axi[key] != config[key]:
                    raise ValueError("software/AXI bytes disagree with plan")
            if (axi["output_requested_bytes"] != config["output_write_bytes"] or
                    axi["read_completed_bytes"] != config["input_read_bytes"] + config["weight_read_bytes"] or
                    axi["read_requests"] != axi["read_completed_transactions"] or
                    axi["write_requests"] != axi["write_completed_transactions"]):
                raise ValueError("incomplete AXI responses")
            phase = sum(counters["ws_" + p + "_cycles"] for p in ("input", "weight", "compute", "output"))
            if (len(rounds) != ROUNDS or min(rounds) <= 0 or
                    not 0 < phase <= counters["ws_total_cycles"] <= wait or sum(rounds) > counters["ws_total_cycles"]):
                raise ValueError("invalid timing windows")
            current_signature = (wait, counters, axi, rounds)
            if signature is not None and current_signature != signature:
                raise ValueError("nonrepeatable timing/traffic")
            signature = current_signature
        result.append(dict(config, repeats=REPEATS, read_delay_cycles=delay,
                           wait_for_halt_cycles=signature[0], csr_counters=signature[1],
                           axi=signature[2], round_cycles=signature[3],
                           elf_sha256=identity[0], vector_sha256=vector_sha, scope=SCOPE))
    return result, identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "verify"):
        p = sub.add_parser(command)
        p.add_argument("--upstream", required=True, type=Path)
    p = sub.add_parser("log")
    p.add_argument("--file", required=True, type=Path)
    p.add_argument("--kib", required=True, type=int, choices=CAPACITIES)
    p.add_argument("--tiles", required=True, type=int, choices=TILE_CHOICES)
    p.add_argument("--delay", required=True, type=int, choices=DELAYS)
    p = sub.add_parser("compare")
    p.add_argument("--logs", required=True, type=Path, nargs="+")
    args = parser.parse_args()
    if args.command in ("prepare", "verify"):
        manifest = prepare(args.upstream.resolve()) if args.command == "prepare" else verify(args.upstream.resolve())
        print("[TCM_WORKSET_VERIFIED] upstream=" + manifest["upstream"])
    elif args.command == "log":
        rows, _ = checked_log(args.file.read_text(), args.kib, args.tiles, args.delay)
        for row in rows:
            print("[TCM_WORKSET_SUMMARY] " + json.dumps(row, sort_keys=True))
        print("[TCM_WORKSET_PAIR] " + json.dumps(dict(
            dtcm_kib=args.kib, tiles=args.tiles, read_delay_cycles=args.delay,
            stream_cycles=rows[0]["wait_for_halt_cycles"],
            prefix_cache_cycles=rows[1]["wait_for_halt_cycles"],
            stream_over_prefix_cycle_ratio=round(rows[0]["wait_for_halt_cycles"] / rows[1]["wait_for_halt_cycles"], 6),
            weight_read_bytes_saved=rows[0]["weight_read_bytes"] - rows[1]["weight_read_bytes"], scope=SCOPE), sort_keys=True))
    else:
        identity, parameters, seen, paired = None, None, set(), []
        for path in args.logs:
            text = path.read_text()
            marker = "[GOOGLE_TCM_WORKSET] "
            first = next(json.loads(line.split(marker, 1)[1]) for line in text.splitlines() if marker in line)
            kib, tiles, delay = first["dtcm_kib"], first["tiles"], first["read_delay_cycles"]
            if kib in seen or kib not in CAPACITIES or tiles not in TILE_CHOICES or delay not in DELAYS:
                raise ValueError("duplicate/invalid comparison configuration")
            if parameters is not None and parameters != (tiles, delay):
                raise ValueError("different workload or memory-delay assumption")
            checked, current = checked_log(text, kib, tiles, delay)
            if identity is not None and identity != current:
                raise ValueError("different ELF/layout: not a paired comparison")
            identity, parameters = current, (tiles, delay)
            seen.add(kib)
            paired.append(checked)
        if len(seen) < 2:
            raise ValueError("comparison needs at least two capacities")
        paired.sort(key=lambda rows: rows[0]["dtcm_kib"])
        base = paired[0][1]
        for stream, cache in paired:
            print("[TCM_WORKSET_COMPARE] " + json.dumps(dict(
                dtcm_kib=cache["dtcm_kib"], tiles=cache["tiles"], read_delay_cycles=cache["read_delay_cycles"],
                stream_cycles=stream["wait_for_halt_cycles"], prefix_cache_cycles=cache["wait_for_halt_cycles"],
                prefix_cache_weight_read_bytes=cache["weight_read_bytes"],
                first_capacity=base["dtcm_kib"],
                first_over_current_prefix_cycle_ratio=round(base["wait_for_halt_cycles"]/cache["wait_for_halt_cycles"], 6),
                scope=SCOPE), sort_keys=True))


if __name__ == "__main__":
    main()
