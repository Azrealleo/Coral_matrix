#!/usr/bin/env python3
"""Export shared layer tiles and per-pass MXU HEX vectors into a new directory."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.dont_write_bytecode = True

from vme_matrix_layer_vectors import layer_cases, layer_hash, passes, reference, tiles
from generate_mxu_boundary import packed_inputs
from generate_signed_stress import write_hex128


def export(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    manifest = []
    for name, a, b in layer_cases():
        m, k = a.shape
        n = b.shape[1]
        case_dir = destination / name
        case_dir.mkdir()
        entries = []
        for row, column, valid_m, valid_n, full_a, full_b in tiles(a, b):
            tile_name = "r{}_c{}".format(row, column)
            tile_dir = case_dir / tile_name
            tile_dir.mkdir()
            write_hex128(tile_dir / "golden.hex", reference(full_a, full_b).tobytes())
            pass_k = []
            for index, (start, logical, physical) in enumerate(passes(k)):
                padded_a = full_a[:, start:start + logical]
                padded_b = full_b[start:start + logical]
                if physical != logical:
                    import numpy as np
                    a_hw = np.zeros((16, physical), dtype=np.int8)
                    b_hw = np.zeros((physical, 16), dtype=np.int8)
                    a_hw[:, :logical] = padded_a
                    b_hw[:logical] = padded_b
                else:
                    a_hw, b_hw = padded_a, padded_b
                acts, weights = packed_inputs(a_hw, b_hw)
                write_hex128(tile_dir / "act_{}.hex".format(index), acts.tobytes())
                write_hex128(tile_dir / "weight_{}.hex".format(index), weights.tobytes())
                pass_k.append(physical)
            entries.append(dict(tile=tile_name, row=row, column=column,
                                valid_m=valid_m, valid_n=valid_n,
                                pass_k=pass_k))
        manifest.append(dict(case=name, M=m, N=n, K=k,
                             logical_sha256=layer_hash(a, b), tiles=entries))
    (destination / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (destination / "tiles.txt").write_text(
        "".join("{} {} {} {} {} {} {} {} {}\n".format(
            row["case"], tile["tile"], row["K"], len(tile["pass_k"]),
            *(tile["pass_k"] + [0] * (3 - len(tile["pass_k"]))),
            row["logical_sha256"], tile["valid_m"] * tile["valid_n"] * row["K"])
            for row in manifest for tile in row["tiles"]), encoding="ascii")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination")
    args = parser.parse_args()
    rows = export(args.destination)
    for row in rows:
        print("[MXU_LAYER_VECTOR] " + json.dumps(row, sort_keys=True))
    digest = hashlib.sha256("".join(row["logical_sha256"] for row in rows)
                            .encode("ascii")).hexdigest()
    print("[MXU_LAYER_MANIFEST] cases=2 tiles=5 logical_set_sha256=" + digest)
