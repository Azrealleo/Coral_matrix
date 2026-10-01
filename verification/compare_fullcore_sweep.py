#!/usr/bin/env python3
"""Validate and pair official Tk4 and fork full-core RTL speed sweeps."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.path.insert(0, str(ROOT / "coralnpu-Yangg152/tests/mxu"))
sys.dont_write_bytecode = True

from mxu_fullcore_tile_vectors import (  # noqa: E402
    full_tile as fork_full_tile, logical_hash, reference,
    speed_sweep_cases as fork_cases,
)
from vme_matrix_model_tile_vectors import (  # noqa: E402
    full_tile as official_full_tile,
    speed_sweep_cases as official_cases,
)


def parse_rows(log, marker):
    return [json.loads(line.split(marker, 1)[1]) for line in log.splitlines()
            if marker in line]


def _validate(records, cases, side):
    expected = {(name, repeat) for name, _, _ in cases for repeat in range(3)}
    assert len(cases) == 22 and len(records) == len(expected)
    assert {(row["case"], row["repeat"]) for row in records} == expected
    result = []
    for name, a, b in cases:
        m, k = a.shape
        n = b.shape[1]
        step = 4 if side == "official" else 16
        k_hw = ((k + step - 1) // step) * step
        tile = official_full_tile if side == "official" else fork_full_tile
        fa, fb = tile(a, b, k_hw)
        physical_hash = hashlib.sha256(
            fa.tobytes() + fb.tobytes() + reference(fa, fb).tobytes()).hexdigest()
        cycles = []
        for row in (item for item in records if item["case"] == name):
            assert (row["M"], row["N"], row["K"], row["K_hw"]) == (m, n, k, k_hw)
            assert row["checked_elements"] == 256
            assert (row["useful_macs"], row["physical_macs"]) == (m * n * k, 256 * k_hw)
            assert row["logical_sha256"] == logical_hash(a, b)
            assert row["physical_vector_sha256"] == physical_hash
            assert row["scope"] == ("official_tk4_full_core_speed_sweep" if side == "official"
                                    else "fork_full_core_speed_sweep")
            if side == "official":
                assert row["tk_per_instruction"] == 4
            count = row["launch_wait_to_halt_cycles"]
            assert type(count) is int and count > 0
            cycles.append(count)
        assert len(cycles) == 3 and len(set(cycles)) == 1, name + ": unstable cycles"
        result.append(dict(case=name, M=m, N=n, K=k, K_hw=k_hw,
                           useful_macs=m * n * k,
                           logical_sha256=logical_hash(a, b),
                           launch_wait_to_halt_cycles=cycles[0]))
    digest = hashlib.sha256("".join(row["logical_sha256"] for row in result)
                            .encode("ascii")).hexdigest()
    return result, digest


def compare(official_records, fork_records):
    official, official_digest = _validate(official_records, official_cases(), "official")
    fork, fork_digest = _validate(fork_records, fork_cases(), "fork")
    assert official_digest == fork_digest, "logical vectors differ"
    rows = []
    for g, f in zip(official, fork):
        key = ("case", "M", "N", "K", "useful_macs", "logical_sha256")
        assert tuple(g[k] for k in key) == tuple(f[k] for k in key)
        gc = g["launch_wait_to_halt_cycles"]
        fc = f["launch_wait_to_halt_cycles"]
        rows.append(dict(case=g["case"], M=g["M"], N=g["N"], K=g["K"],
                         useful_macs=g["useful_macs"],
                         google_tk4_k_hw=g["K_hw"], fork_k_hw=f["K_hw"],
                         google_tk4_fullcore_cycles=gc, fork_fullcore_cycles=fc,
                         google_tk4_over_fork_cycle_ratio=round(gc / fc, 6),
                         scope="same_launch_halt_endpoint_different_cores_and_drivers_not_silicon_speedup"))
    return rows, official_digest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("official_tk4_test_log")
    parser.add_argument("fork_test_log")
    args = parser.parse_args()
    official_log = Path(args.official_tk4_test_log).read_text(encoding="utf-8")
    fork_log = Path(args.fork_test_log).read_text(encoding="utf-8")
    assert "[GOOGLE_TK4_SWEEP_CHECK] cases=22 repeats=3 passed" in official_log
    assert "[YANGG_FULLCORE_SWEEP_CHECK] cases=22 repeats=3 passed" in fork_log
    rows, digest = compare(
        parse_rows(official_log, "[GOOGLE_TK4_SWEEP] "),
        parse_rows(fork_log, "[YANGG_FULLCORE_SWEEP] "))
    print("[FULLCORE_SWEEP_MANIFEST] cases=22 repeats=3 logical_set_sha256=" + digest)
    for row in rows:
        print("[FULLCORE_SWEEP_PAIR] " + json.dumps(row, sort_keys=True))
