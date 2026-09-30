#!/usr/bin/env python3
"""Strictly validate full-core long-K/multi-tile run records."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.dont_write_bytecode = True

from vme_matrix_layer_vectors import layer_cases, layer_hash, tiles


def summarize(tile_records, layer_records):
    expected_cases = layer_cases()
    assert len(expected_cases) == 2
    assert len(layer_records) == 6 and len(tile_records) == 15
    expected_keys = set()
    summary = []
    for name, a, b in expected_cases:
        m, k = a.shape
        n = b.shape[1]
        tile_list = list(tiles(a, b))
        counts = []
        tile_cycle_vectors = []
        for repeat in range(3):
            expected = {(row, column) for row, column, _, _, _, _ in tile_list}
            matching = [r for r in tile_records if r["case"] == name and r["repeat"] == repeat]
            assert {(r["row"], r["column"]) for r in matching} == expected
            assert len(matching) == len(tile_list)
            tile_cycle_vectors.append(tuple(
                r["launch_wait_to_halt_cycles"] for r in
                sorted(matching, key=lambda r: (r["row"], r["column"]))))
            subtotal = 0
            for tile in matching:
                key = (name, repeat, tile["row"], tile["column"])
                assert key not in expected_keys
                expected_keys.add(key)
                reference_tile = next(t for t in tile_list if
                                      (t[0], t[1]) == (tile["row"], tile["column"]))
                assert tile["valid_m"] == reference_tile[2]
                assert tile["valid_n"] == reference_tile[3]
                assert tile["K"] == k and tile["logical_sha256"] == layer_hash(a, b)
                cycles = tile["launch_wait_to_halt_cycles"]
                assert isinstance(cycles, int) and cycles > 0
                subtotal += cycles
            layer = [r for r in layer_records if r["case"] == name and r["repeat"] == repeat]
            assert len(layer) == 1
            layer = layer[0]
            assert (layer["M"], layer["N"], layer["K"]) == (m, n, k)
            assert layer["tiles"] == len(tile_list) and layer["checked_elements"] == m * n
            assert layer["useful_macs"] == m * n * k
            assert layer["sum_tile_launch_wait_to_halt_cycles"] == subtotal
            assert layer["logical_sha256"] == layer_hash(a, b)
            assert layer["scope"] == "sum_sequential_full_core_tile_launches_not_model_runtime"
            counts.append(subtotal)
        assert len(set(counts)) == 1, "Nondeterministic layer " + name
        assert len(set(tile_cycle_vectors)) == 1, "Nondeterministic tile " + name
        summary.append(dict(case=name, M=m, N=n, K=k, tiles=len(tile_list),
                            repeats=3, useful_macs=m * n * k,
                            sum_tile_launch_wait_to_halt_cycles=counts[0],
                            logical_sha256=layer_hash(a, b),
                            scope="sum_sequential_full_core_tile_launches_not_model_runtime"))
    digest = hashlib.sha256("".join(row["logical_sha256"] for row in summary)
                            .encode("ascii")).hexdigest()
    return summary, digest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test_log")
    args = parser.parse_args()
    log = Path(args.test_log).read_text(encoding="utf-8")
    assert "[GOOGLE_LAYER_CHECK] cases=2 tiles=5 repeats=3 passed" in log
    def parse(marker):
        return [json.loads(line.split(marker, 1)[1]) for line in log.splitlines()
                if marker in line]
    rows, digest = summarize(parse("[GOOGLE_LAYER_TILE] "), parse("[GOOGLE_LAYER] "))
    print("[GOOGLE_LAYER_MANIFEST] cases=2 tiles=5 repeats=3 logical_set_sha256=" + digest)
    for row in rows:
        print("[GOOGLE_LAYER_SUMMARY] " + json.dumps(row, sort_keys=True))
