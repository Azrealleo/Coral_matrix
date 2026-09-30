#!/usr/bin/env python3
"""Validate all 21 official model-tile records and emit seven cycle rows."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.dont_write_bytecode = True

from vme_matrix_model_tile_vectors import full_tile, logical_hash, model_cases
from vme_matrix_stress_vectors import vector_hash


def summarize(records):
    cases = model_cases()
    assert len(cases) == 7 and len(records) == 21
    expected = {case[0]: case for case in cases}
    assert len(expected) == 7
    assert {(row["case"], row["repeat"]) for row in records} == {
        (case[0], repeat) for case in cases for repeat in range(3)}
    rows = []
    for name, a, b in cases:
        m, k = a.shape
        n = b.shape[1]
        full_a, full_b = full_tile(a, b)
        matching = [row for row in records if row["case"] == name]
        counts = []
        for row in matching:
            assert row["M"] == m and row["N"] == n and row["K"] == k
            assert row["K_hw"] == k and row["tk_per_instruction"] == 1
            assert row["checked_elements"] == 256
            assert row["useful_macs"] == m * n * k and row["physical_macs"] == 256 * k
            assert row["scope"] == "full_core_fixture_not_mxu_unit"
            assert row["logical_sha256"] == logical_hash(a, b)
            assert row["physical_vector_sha256"] == vector_hash(full_a, full_b)
            cycles = row["launch_wait_to_halt_cycles"]
            assert isinstance(cycles, int) and cycles > 0
            counts.append(cycles)
        assert len(set(counts)) == 1, "Differing repeat cycles for " + name
        rows.append(dict(case=name, M=m, N=n, K=k, K_hw=k,
                         useful_macs=m * n * k, physical_macs=256 * k,
                         logical_sha256=logical_hash(a, b),
                         launch_wait_to_halt_cycles=counts[0],
                         scope="full_core_fixture_not_mxu_unit"))
    fingerprints = "".join(row["logical_sha256"] for row in rows)
    return rows, hashlib.sha256(fingerprints.encode("ascii")).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test_log")
    args = parser.parse_args()
    log = Path(args.test_log).read_text(encoding="utf-8")
    assert "[GOOGLE_MODEL_TILE_CHECK] cases=7 repeats=3 passed" in log
    marker = "[GOOGLE_MODEL_TILE] "
    records = [json.loads(line.split(marker, 1)[1]) for line in log.splitlines()
               if marker in line]
    rows, digest = summarize(records)
    print("[GOOGLE_MODEL_TILE_MANIFEST] cases=7 repeats=3 logical_set_sha256=" + digest)
    for row in rows:
        print("[GOOGLE_MODEL_TILE_SUMMARY] " + json.dumps(row, sort_keys=True))
