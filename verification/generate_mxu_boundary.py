#!/usr/bin/env python3
"""Export arbitrary-K vectors for the new independent MXU diagnostic TB."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.dont_write_bytecode = True
from vme_matrix_boundary_vectors import boundary_cases
from vme_matrix_stress_vectors import reference, vector_hash
from generate_signed_stress import write_hex128


def packed_inputs(a, b):
    k = a.shape[1]
    chunks = (k + 15) // 16
    # Poison all unused input bytes, not zero. Activation row padding belongs
    # AFTER EACH logical row, not after the full matrix's flat byte stream.
    row_padded = np.full((16, chunks * 16), 37, dtype=np.int8)
    row_padded[:, :k] = a
    act_beats = np.full((256, 16), 37, dtype=np.int8)
    act_beats[:16 * chunks] = row_padded.reshape(16 * chunks, 16)
    weight_beats = np.full((256, 16), 53, dtype=np.int8)
    weight_beats[:k] = b
    return act_beats, weight_beats


def export(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    manifest = []
    for name, a, b, _, _ in boundary_cases():
        directory = destination / name
        directory.mkdir()
        acts, weights = packed_inputs(a, b)
        write_hex128(directory / "act.hex", acts.tobytes())
        write_hex128(directory / "weight.hex", weights.tobytes())
        write_hex128(directory / "golden.hex", reference(a, b).tobytes())
        k = a.shape[1]
        manifest.append(dict(case=name, K=k, act_beats=16 * ((k + 15) // 16),
                             weight_beats=k, checked_elements=256,
                             vector_sha256=vector_hash(a, b)))
    (destination / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    controls = [row for k in (16, 64, 256) for row in manifest if row["K"] == k]
    ordered = controls + [row for row in manifest if row["K"] not in (16, 64, 256)]
    (destination / "cases.txt").write_text(
        "".join("{} {}\n".format(row["case"], row["K"]) for row in ordered), encoding="ascii")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="new output directory; never overwritten")
    args = parser.parse_args()
    for row in export(args.destination):
        print("[MXU_BOUNDARY_VECTOR] " + json.dumps(row, sort_keys=True))
    fingerprints = "".join(vector_hash(case[1], case[2]) for case in boundary_cases())
    print("[MXU_BOUNDARY_MANIFEST] cases=21 vector_set_sha256=" +
          hashlib.sha256(fingerprints.encode("ascii")).hexdigest())
