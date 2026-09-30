#!/usr/bin/env python3
"""Validate and pair same-logical-tile full-core launch-to-halt RTL runs."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.path.insert(0, str(ROOT / "coralnpu-Yangg152/tests/mxu"))
sys.dont_write_bytecode = True

from mxu_fullcore_tile_vectors import full_tile, logical_hash, model_cases, reference
from vme_matrix_model_tile_vectors import full_tile as official_full_tile
from summarize_google_model_tile import summarize as summarize_google


def parse_rows(log, marker):
    return [json.loads(line.split(marker, 1)[1]) for line in log.splitlines()
            if marker in line]


def summarize_fork(records):
    cases = model_cases()
    assert len(cases) == 7 and len(records) == 21
    assert {(r["case"], r["repeat"]) for r in records} == {
        (case[0], i) for case in cases for i in range(3)}
    result = []
    for name, a, b in cases:
        m, k = a.shape
        n = b.shape[1]
        k_hw = ((k + 15) // 16) * 16
        fa, fb = full_tile(a, b, k_hw)
        physical_hash = hashlib.sha256(
            fa.tobytes() + fb.tobytes() + reference(fa, fb).tobytes()).hexdigest()
        rows = [r for r in records if r["case"] == name]
        cycles = []
        for row in rows:
            assert (row["M"], row["N"], row["K"], row["K_hw"]) == (m, n, k, k_hw)
            assert row["checked_elements"] == 256
            assert (row["useful_macs"], row["physical_macs"]) == (m * n * k, 256 * k_hw)
            assert row["logical_sha256"] == logical_hash(a, b)
            assert row["physical_vector_sha256"] == physical_hash
            assert row["scope"] == "fork_full_core_fixture_not_standalone_unit"
            count = row["launch_wait_to_halt_cycles"]
            assert isinstance(count, int) and count > 0
            cycles.append(count)
        assert len(set(cycles)) == 1, name + ": nondeterministic cycles"
        result.append(dict(case=name, M=m, N=n, K=k, K_hw=k_hw,
                           useful_macs=m * n * k, logical_sha256=logical_hash(a, b),
                           launch_wait_to_halt_cycles=cycles[0]))
    digest = hashlib.sha256("".join(r["logical_sha256"] for r in result)
                            .encode("ascii")).hexdigest()
    return result, digest


def summarize_official_tk4(records):
    cases = model_cases()
    assert len(cases) == 7 and len(records) == 21
    assert {(r["case"], r["repeat"]) for r in records} == {
        (case[0], i) for case in cases for i in range(3)}
    result = []
    for name, a, b in cases:
        m, k = a.shape
        n = b.shape[1]
        k_hw = ((k + 3) // 4) * 4
        fa, fb = official_full_tile(a, b, k_hw)
        physical_hash = hashlib.sha256(
            fa.tobytes() + fb.tobytes() + reference(fa, fb).tobytes()).hexdigest()
        counts = []
        for row in (r for r in records if r["case"] == name):
            assert (row["M"], row["N"], row["K"], row["K_hw"]) == (m, n, k, k_hw)
            assert row["tk_per_instruction"] == 4 and row["checked_elements"] == 256
            assert (row["useful_macs"], row["physical_macs"]) == (m * n * k, 256 * k_hw)
            assert row["logical_sha256"] == logical_hash(a, b)
            assert row["physical_vector_sha256"] == physical_hash
            assert row["scope"] == "official_tk4_full_core_fixture_not_array_only"
            cycles = row["launch_wait_to_halt_cycles"]
            assert isinstance(cycles, int) and cycles > 0
            counts.append(cycles)
        assert len(set(counts)) == 1, name + ": nondeterministic Tk4 cycles"
        result.append(dict(case=name, M=m, N=n, K=k, K_hw=k_hw,
                           useful_macs=m * n * k, logical_sha256=logical_hash(a, b),
                           launch_wait_to_halt_cycles=counts[0]))
    digest = hashlib.sha256("".join(r["logical_sha256"] for r in result)
                            .encode("ascii")).hexdigest()
    return result, digest


def compare(google_records, fork_records):
    google, google_digest = summarize_google(google_records)
    fork, fork_digest = summarize_fork(fork_records)
    assert google_digest == fork_digest
    combined = []
    for g, f in zip(google, fork):
        assert (g["case"], g["M"], g["N"], g["K"], g["useful_macs"], g["logical_sha256"]) == (
            f["case"], f["M"], f["N"], f["K"], f["useful_macs"], f["logical_sha256"])
        gc = g["launch_wait_to_halt_cycles"]
        fc = f["launch_wait_to_halt_cycles"]
        combined.append(dict(case=g["case"], M=g["M"], N=g["N"], K=g["K"],
                             useful_macs=g["useful_macs"],
                             google_k_hw=g["K_hw"], fork_k_hw=f["K_hw"],
                             google_fullcore_cycles=gc, fork_fullcore_cycles=fc,
                             google_cycles_over_fork_cycles=round(gc / fc, 6),
                             scope="same_fixture_endpoint_different_cores_and_drivers_not_silicon_speedup"))
    return combined, google_digest


def compare_three(google_tk1_records, google_tk4_records, fork_records):
    tk1, digest1 = summarize_google(google_tk1_records)
    tk4, digest4 = summarize_official_tk4(google_tk4_records)
    fork, digest_fork = summarize_fork(fork_records)
    assert digest1 == digest4 == digest_fork
    result = []
    for a, b, c in zip(tk1, tk4, fork):
        key = ("case", "M", "N", "K", "useful_macs", "logical_sha256")
        assert tuple(a[k] for k in key) == tuple(b[k] for k in key) == tuple(c[k] for k in key)
        t1 = a["launch_wait_to_halt_cycles"]
        t4 = b["launch_wait_to_halt_cycles"]
        f = c["launch_wait_to_halt_cycles"]
        result.append(dict(case=a["case"], M=a["M"], N=a["N"], K=a["K"],
                           useful_macs=a["useful_macs"],
                           google_tk1_k_hw=a["K_hw"], google_tk4_k_hw=b["K_hw"],
                           fork_k_hw=c["K_hw"],
                           google_tk1_fullcore_cycles=t1,
                           google_tk4_fullcore_cycles=t4,
                           fork_fullcore_cycles=f,
                           google_tk4_over_fork_cycle_ratio=round(t4 / f, 6),
                           scope="same_launch_halt_endpoint_different_cores_and_drivers_not_silicon_speedup"))
    return result, digest1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("google_tk1_test_log")
    parser.add_argument("google_tk4_test_log")
    parser.add_argument("fork_test_log")
    args = parser.parse_args()
    google_log = Path(args.google_tk1_test_log).read_text(encoding="utf-8")
    google_tk4_log = Path(args.google_tk4_test_log).read_text(encoding="utf-8")
    fork_log = Path(args.fork_test_log).read_text(encoding="utf-8")
    assert "[GOOGLE_MODEL_TILE_CHECK] cases=7 repeats=3 passed" in google_log
    assert "[GOOGLE_TK4_TILE_CHECK] cases=7 repeats=3 passed" in google_tk4_log
    assert "[YANGG_FULLCORE_TILE_CHECK] cases=7 repeats=3 passed" in fork_log
    rows, digest = compare_three(
        parse_rows(google_log, "[GOOGLE_MODEL_TILE] "),
        parse_rows(google_tk4_log, "[GOOGLE_TK4_TILE] "),
        parse_rows(fork_log, "[YANGG_FULLCORE_TILE] "))
    print("[FULLCORE_PAIR_MANIFEST] cases=7 repeats=3 logical_set_sha256=" + digest)
    for row in rows:
        print("[FULLCORE_PAIR] " + json.dumps(row, sort_keys=True))
