#!/usr/bin/env python3
"""Validate all 32 official stress records against the shared vectors."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.dont_write_bytecode = True
from vme_matrix_stress_vectors import batch_hash, stress_batches, vector_hash


def summarize(records):
    batches = stress_batches()
    expected = {case[0]: (batch, case) for batch, cases in batches for case in cases}
    assert len(records) == len(expected) == 32, "Expected all 32 functional records"
    assert len({row["case"] for row in records}) == 32, "Duplicate case"
    assert {row["case"] for row in records} == set(expected), "Missing/unexpected case"
    for row in records:
        batch, case = expected[row["case"]]
        assert row["batch"] == batch and row["K"] == case[1].shape[1]
        assert row["checked_elements"] == 256
        assert row["vector_sha256"] == vector_hash(case[1], case[2])
    return [dict(batch=batch, cases=4, checked_elements=1024,
                 batch_sha256=batch_hash(cases)) for batch, cases in batches]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test_log")
    args = parser.parse_args()
    log = Path(args.test_log).read_text(encoding="utf-8")
    assert "[GOOGLE_SIGNED_STRESS_CHECK] batches=8 cases=32 checked_elements=8192 passed" in log
    marker = "[GOOGLE_SIGNED_STRESS] "
    records = [json.loads(line.split(marker, 1)[1]) for line in log.splitlines() if marker in line]
    rows = summarize(records)
    for row in rows:
        print("[GOOGLE_SIGNED_STRESS_SUMMARY] " + json.dumps(row, sort_keys=True))


if __name__ == "__main__":
    main()
