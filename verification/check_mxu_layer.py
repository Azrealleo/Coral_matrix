#!/usr/bin/env python3
"""Local long-K vectors/export/harness checks; never claims RTL coverage."""

import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.dont_write_bytecode = True

from vme_matrix_layer_vectors import LAYER_SHAPES, layer_cases, layer_hash, passes, reference, tiles
from generate_mxu_layer import export
from summarize_google_layer import summarize
from check_google_burst import FakeFixture, harness_functions


class LongMatrixFixture(FakeFixture):
    async def run_to_halt(self, timeout_cycles):
        assert timeout_cycles == 200000 and self.values["perf_tk"] == 1
        k = self.values["perf_k"]
        assert 256 < k <= 528
        a = self.values["perf_a"].view(np.int8).reshape(532, 16)[:k].T.astype(np.int64)
        b = self.values["perf_b"].view(np.int8).reshape(532, 16)[:k].astype(np.int64)
        self.output = (a @ b).astype("<i4")
        if self.corrupt:
            self.output[0, 0] += 1
        self.values.update(perf_status=1, perf_mtype=(16 << 10) | (1 << 5) | 3,
                           perf_vtype=0x1C0)
        return 999  # Synthetic host-contract result, not simulated latency.


class LayerTests(unittest.TestCase):
    def test_shapes_scalar_tiling_and_passes(self):
        self.assertEqual(len(LAYER_SHAPES), 2)
        for name, a, b in layer_cases():
            m, k = a.shape
            n = b.shape[1]
            self.assertEqual(k % 16, 0)  # Current Yangg152 1x1 MXU dispatch gate.
            self.assertTrue(np.any(a < 0) and np.any(a >= 0), name)
            self.assertTrue(np.any(b < 0) and np.any(b >= 0), name)
            scalar = [[sum(int(a[i, p]) * int(b[p, j]) for p in range(k))
                       for j in range(n)] for i in range(m)]
            np.testing.assert_array_equal(reference(a, b), scalar)
            self.assertEqual(sum(p[1] for p in passes(k)), k)
            for row, col, vm, vn, ta, tb in tiles(a, b):
                expected = np.zeros((16, 16), dtype="<i4")
                expected[:vm, :vn] = reference(a, b)[row:row + vm, col:col + vn]
                np.testing.assert_array_equal(reference(ta, tb), expected)
                split = np.zeros((16, 16), dtype=np.int64)
                for start, logical, physical in passes(k):
                    pa = np.zeros((16, physical), dtype=np.int8)
                    pb = np.zeros((physical, 16), dtype=np.int8)
                    pa[:, :logical] = ta[:, start:start + logical]
                    pb[:logical] = tb[start:start + logical]
                    split += pa.astype(np.int64) @ pb.astype(np.int64)
                np.testing.assert_array_equal(split, expected)

    def test_export_hex_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="mxu_layer_check_") as temporary:
            target = Path(temporary) / "vectors"
            manifest = export(target)
            self.assertEqual([len(row["tiles"]) for row in manifest], [4, 1])
            self.assertEqual(json.loads((target / "manifest.json").read_text()), manifest)
            self.assertEqual(len((target / "tiles.txt").read_text().splitlines()), 5)

            def unpack(path, lines):
                words = path.read_text().splitlines()
                self.assertEqual(len(words), lines)
                return b"".join(int(word, 16).to_bytes(16, "little") for word in words)

            for row, (name, a, b) in zip(manifest, layer_cases()):
                self.assertEqual(row["logical_sha256"], layer_hash(a, b))
                for tile, (r, c, vm, vn, ta, tb) in zip(row["tiles"], tiles(a, b)):
                    td = target / name / tile["tile"]
                    self.assertEqual((tile["row"], tile["column"], tile["valid_m"], tile["valid_n"]),
                                     (r, c, vm, vn))
                    gold = np.frombuffer(unpack(td / "golden.hex", 64), "<i4").reshape(16, 16)
                    np.testing.assert_array_equal(gold, reference(ta, tb))
                    for index, (start, logical, physical) in enumerate(passes(a.shape[1])):
                        self.assertEqual(tile["pass_k"][index], physical)
                        acts = np.frombuffer(unpack(td / "act_{}.hex".format(index), 256), np.int8).reshape(256, 16)
                        weights = np.frombuffer(unpack(td / "weight_{}.hex".format(index), 256), np.int8).reshape(256, 16)
                        act = acts[:physical].reshape(16, physical)
                        np.testing.assert_array_equal(act[:, :logical], ta[:, start:start + logical])
                        np.testing.assert_array_equal(weights[:logical], tb[start:start + logical])
                        self.assertTrue(np.all(act[:, logical:] == 0))
                        self.assertTrue(np.all(weights[logical:physical] == 0))
            with self.assertRaises(FileExistsError):
                export(target)

    def test_existing_full_core_upload_contract_via_mock(self):
        namespace, log = harness_functions()
        count = 0
        for name, a, b in layer_cases():
            for row, col, _, _, ta, tb in tiles(a, b):
                result = asyncio.run(namespace["_run_case"](
                    LongMatrixFixture(), "fake.elf",
                    ("{}_r{}_c{}".format(name, row, col), ta, tb, 1, True),
                    max_k=528))
                self.assertEqual(result, 999)
                count += 1
        self.assertEqual(len(log.messages), count)
        with self.assertRaises(AssertionError):
            name, a, b = layer_cases()[0]
            _, _, _, _, ta, tb = next(tiles(a, b))
            asyncio.run(namespace["_run_case"](
                LongMatrixFixture(corrupt=True), "fake.elf", (name, ta, tb, 1, True),
                max_k=528))

    def test_summary_rejects_missing_duplicate_and_tampered_records(self):
        tile_rows, layer_rows = [], []
        for name, a, b in layer_cases():
            m, k = a.shape
            n = b.shape[1]
            ts = list(tiles(a, b))
            for repeat in range(3):
                for row, col, vm, vn, _, _ in ts:
                    tile_rows.append(dict(case=name, repeat=repeat, row=row, column=col,
                                          valid_m=vm, valid_n=vn, K=k,
                                          launch_wait_to_halt_cycles=999,
                                          logical_sha256=layer_hash(a, b)))
                layer_rows.append(dict(case=name, repeat=repeat, M=m, N=n, K=k,
                                       tiles=len(ts), checked_elements=m * n,
                                       useful_macs=m * n * k,
                                       sum_tile_launch_wait_to_halt_cycles=999 * len(ts),
                                       logical_sha256=layer_hash(a, b),
                                       scope="sum_sequential_full_core_tile_launches_not_model_runtime"))
        rows, digest = summarize(tile_rows, layer_rows)
        self.assertEqual(len(rows), 2)
        with self.assertRaises(AssertionError):
            summarize(tile_rows[:-1], layer_rows)
        with self.assertRaises(AssertionError):
            summarize(tile_rows[:-1] + tile_rows[:1], layer_rows)
        for field, value in (("valid_n", 0), ("logical_sha256", "wrong"),
                             ("launch_wait_to_halt_cycles", 0)):
            changed = copy.deepcopy(tile_rows)
            changed[-1][field] = value
            with self.assertRaises(AssertionError):
                summarize(changed, layer_rows)
        swapped_cycles = copy.deepcopy(tile_rows)
        swapped_cycles[0]["launch_wait_to_halt_cycles"] += 1
        swapped_cycles[1]["launch_wait_to_halt_cycles"] -= 1
        with self.assertRaises(AssertionError):
            summarize(swapped_cycles, layer_rows)
        print("[LAYER_STATIC] cases=2 tiles=5 logical_set_sha256=" + digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
