#!/usr/bin/env python3
"""Require all 21 official boundary cases and exact shared fingerprints."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.dont_write_bytecode = True
from vme_matrix_boundary_vectors import K_VALUES, boundary_cases
from vme_matrix_stress_vectors import vector_hash


def summarize(records):
    cases = boundary_cases()
    assert len(records) == len(cases) == 21
    expected = {case[0]: case for case in cases}
    assert len({row["case"] for row in records}) == 21
    assert {row["case"] for row in records} == set(expected)
    for row in records:
        case = expected[row["case"]]
        assert row["K"] == case[1].shape[1]
        assert row["tk_per_instruction"] == 1 and row["checked_elements"] == 256
        assert row["vector_sha256"] == vector_hash(case[1], case[2])
    fingerprints = "".join(vector_hash(case[1], case[2]) for case in cases)
    return dict(cases=21, checked_elements=5376, K_values=list(K_VALUES),
                scope="full_tile_arithmetic_tk1_not_performance",
                vector_set_sha256=hashlib.sha256(fingerprints.encode("ascii")).hexdigest())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test_log")
    args = parser.parse_args()
    log = Path(args.test_log).read_text(encoding="utf-8")
    assert "[GOOGLE_K_BOUNDARY_CHECK] cases=21 checked_elements=5376 passed" in log
    marker = "[GOOGLE_K_BOUNDARY] "
    records = [json.loads(line.split(marker, 1)[1]) for line in log.splitlines() if marker in line]
    print("[GOOGLE_K_BOUNDARY_SUMMARY] " + json.dumps(summarize(records), sort_keys=True))
