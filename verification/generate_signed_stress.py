#!/usr/bin/env python3
"""Export the common signed stress vectors for the unchanged fork testbench.

Generated HEX/JSON are run artifacts, not source edits. Destination must be
new: never overwrite previous vectors or results. Needs only Python and NumPy.
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.dont_write_bytecode = True
from vme_matrix_stress_vectors import LEGACY_NAMES, batch_hash, reference, stress_batches, vector_hash


def write_hex128(path, data):
    assert len(data) % 16 == 0
    path.write_text("".join("{:032x}\n".format(int.from_bytes(data[i:i + 16], "little"))
                            for i in range(0, len(data), 16)), encoding="ascii")


def export_batches(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    batches = stress_batches()
    manifest = []
    for batch, cases in batches:
        directory = destination / batch / "cases"
        directory.mkdir(parents=True)
        for legacy, (name, a, b, tk, signed_b) in zip(LEGACY_NAMES, cases):
            k = a.shape[1]
            assert k % 16 == 0 and tk == 4
            c = reference(a, b)
            # Activation: row-major, each 16-byte row chunk is a beat.
            # Weight: one K row of 16 columns per beat. Golden: four i32/beat.
            write_hex128(directory / (legacy + "_act.hex"), a.tobytes())
            write_hex128(directory / (legacy + "_weight.hex"), b.tobytes())
            write_hex128(directory / (legacy + "_golden.hex"), c.tobytes())
            (directory / (legacy + "_cfg.hex")).write_text(
                "{:02x}\n".format(0 if k == 256 else k), encoding="ascii")
            row = dict(batch=batch, case=name, legacy_case=legacy, K=k,
                       signed_a=True, signed_b=signed_b, checked_elements=256,
                       act_min=int(a.min()), act_max=int(a.max()),
                       weight_min=int(b.min()), weight_max=int(b.max()),
                       golden_min=int(c.min()), golden_max=int(c.max()),
                       vector_sha256=vector_hash(a, b))
            manifest.append(row)
    assert len(manifest) == 32
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (destination / "batches.txt").write_text(
        "".join(batch + "\n" for batch, _ in batches), encoding="ascii")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="new directory for the generated vectors")
    args = parser.parse_args()
    manifest = export_batches(args.destination)
    for row in manifest:
        print("[SIGNED_STRESS_VECTOR] " + json.dumps(row, sort_keys=True))
    for batch, cases in stress_batches():
        print("[SIGNED_STRESS_MANIFEST] batch={} cases=4 batch_sha256={}".format(batch, batch_hash(cases)))
    print("[SIGNED_STRESS_GENERATED] batches=8 cases=32; no RTL simulation performed")


if __name__ == "__main__":
    main()
