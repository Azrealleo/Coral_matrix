#!/usr/bin/env python3
"""Export model-like padded MXU tiles without modifying repository RTL."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.dont_write_bytecode = True

from vme_matrix_model_tile_vectors import full_tile, logical_hash, model_cases, reference
from vme_matrix_stress_vectors import vector_hash
from generate_mxu_boundary import packed_inputs
from generate_signed_stress import write_hex128


def export(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    manifest = []
    for name, a, b in model_cases():
        m, k = a.shape
        n = b.shape[1]
        k_hw = ((k + 15) // 16) * 16
        full_a, full_b = full_tile(a, b, k_hw)
        assert k_hw % 16 == 0 and k_hw <= 256
        acts, weights = packed_inputs(full_a, full_b)
        directory = destination / name
        directory.mkdir()
        write_hex128(directory / "act.hex", acts.tobytes())
        write_hex128(directory / "weight.hex", weights.tobytes())
        write_hex128(directory / "golden.hex", reference(full_a, full_b).tobytes())
        manifest.append(dict(case=name, M=m, N=n, K=k, K_hw=k_hw,
                             useful_macs=m * n * k, physical_macs=256 * k_hw,
                             logical_sha256=logical_hash(a, b),
                             physical_vector_sha256=vector_hash(full_a, full_b)))
    (destination / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (destination / "cases.txt").write_text(
        "".join("{case} {M} {N} {K} {K_hw} {logical_sha256}\n".format(**row)
                for row in manifest), encoding="ascii")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="new vector directory, never overwritten")
    args = parser.parse_args()
    rows = export(args.destination)
    for record in rows:
        print("[MODEL_TILE_VECTOR] " + json.dumps(record, sort_keys=True))
    fingerprints = "".join(row["logical_sha256"] for row in rows)
    print("[MODEL_TILE_MANIFEST] cases=7 logical_set_sha256=" +
          hashlib.sha256(fingerprints.encode("ascii")).hexdigest())
