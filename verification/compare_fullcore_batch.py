#!/usr/bin/env python3
"""Pair same-logical shared-weight batches run in one full-core launch."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.path.insert(0, str(ROOT / "coralnpu-Yangg152/tests/mxu"))
sys.dont_write_bytecode = True

from mxu_fullcore_tile_vectors import shared_weight_batch_cases as fork_cases  # noqa: E402
from vme_matrix_model_tile_vectors import shared_weight_batch_cases as google_cases  # noqa: E402


def parse_rows(log, marker):
    return [json.loads(line.split(marker, 1)[1]) for line in log.splitlines()
            if marker in line]


def validate(records, cases, side):
    assert len(cases) == 9 and len(records) == 27
    assert {(r["case"], r["repeat"]) for r in records} == {
        (name, repeat) for name, _, _ in cases for repeat in range(3)}
    summary = []
    for name, a, b in cases:
        tiles, m, k = a.shape
        assert m == 16 and b.shape == (k, 16)
        expected = (a.astype(np.int64) @ b.astype(np.int64)).astype("<i4")
        digest = hashlib.sha256(
            a.tobytes() + b.tobytes() + expected.tobytes()).hexdigest()
        values = []
        for r in (row for row in records if row["case"] == name):
            assert (r["K"], r["tiles"], r["checked_elements"], r["useful_macs"]) == (
                k, tiles, tiles * 256, tiles * 256 * k)
            assert r["logical_sha256"] == digest
            scopes = {
                "google": "official_tk4_full_core_shared_weight_batch",
                "fork": "fork_full_core_shared_weight_batch",
                "fork_reload": "fork_full_core_shared_weight_batch_reload",
            }
            schedules = {
                "google": "B_reloaded_from_memory_per_tile",
                "fork": "B_loaded_once_into_MXU_SRAM",
                "fork_reload": "B_reloaded_into_MXU_SRAM_per_tile",
            }
            assert r["scope"] == scopes[side]
            assert r["weight_load_schedule"] == schedules[side]
            if side != "google":
                assert r["program_schema"] == 2, "rerun fork with updated batch ELF"
            count = r["launch_wait_to_halt_cycles"]
            assert type(count) is int and count > 0
            values.append(count)
        assert len(values) == 3 and len(set(values)) == 1, name + ": unstable cycles"
        summary.append(dict(case=name, K=k, tiles=tiles, logical_sha256=digest,
                            useful_macs=tiles * 256 * k,
                            launch_wait_to_halt_cycles=values[0]))
    set_hash = hashlib.sha256("".join(row["logical_sha256"] for row in summary)
                              .encode("ascii")).hexdigest()
    return summary, set_hash


def compare(google_records, fork_records):
    google, ghash = validate(google_records, google_cases(), "google")
    fork, fhash = validate(fork_records, fork_cases(), "fork")
    assert ghash == fhash, "batch vectors differ"
    rows = []
    for g, f in zip(google, fork):
        key = ("case", "K", "tiles", "logical_sha256", "useful_macs")
        assert tuple(g[k] for k in key) == tuple(f[k] for k in key)
        gc = g["launch_wait_to_halt_cycles"]
        fc = f["launch_wait_to_halt_cycles"]
        rows.append(dict(case=g["case"], K=g["K"], tiles=g["tiles"],
                         useful_macs=g["useful_macs"],
                         google_tk4_fullcore_cycles=gc, fork_fullcore_cycles=fc,
                         google_cycles_per_tile=round(gc / g["tiles"], 3),
                         fork_cycles_per_tile=round(fc / f["tiles"], 3),
                         google_tk4_over_fork_cycle_ratio=round(gc / fc, 6),
                         scope="one_launch_same_outputs_different_weight_reuse_and_cores"))
    return rows, ghash


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("official_log")
    parser.add_argument("fork_log")
    args = parser.parse_args()
    official_log = Path(args.official_log).read_text(encoding="utf-8")
    fork_log = Path(args.fork_log).read_text(encoding="utf-8")
    assert "[GOOGLE_BATCH_CHECK] cases=9 repeats=3 passed" in official_log
    assert "[YANGG_BATCH_CHECK] cases=9 repeats=3 passed" in fork_log
    rows, digest = compare(parse_rows(official_log, "[GOOGLE_BATCH] "),
                           parse_rows(fork_log, "[YANGG_BATCH] "))
    print("[FULLCORE_BATCH_MANIFEST] cases=9 repeats=3 logical_set_sha256=" + digest)
    for row in rows:
        print("[FULLCORE_BATCH_PAIR] " + json.dumps(row, sort_keys=True))
