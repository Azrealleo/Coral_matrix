#!/usr/bin/env python3
"""Local vector/export/harness checks. NOT RTL or model-inference testing."""

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

from vme_matrix_model_tile_vectors import MODEL_SHAPES, full_tile, logical_hash, model_cases, reference
from vme_matrix_stress_vectors import vector_hash
from generate_mxu_model_tile import export
from summarize_google_model_tile import summarize
from check_google_burst import harness_functions
from check_mxu_boundary import FullMatrixFixture


class ModelTileTests(unittest.TestCase):
    def test_logical_shapes_scalar_results_and_padding(self):
        self.assertEqual(len(MODEL_SHAPES), 7)
        for name, a, b in model_cases():
            m, k = a.shape
            n = b.shape[1]
            self.assertTrue(np.any(a < 0) and np.any(a >= 0), name)
            self.assertTrue(np.any(b < 0) and np.any(b >= 0), name)
            scalar = [[sum(int(a[i, p]) * int(b[p, j]) for p in range(k))
                       for j in range(n)] for i in range(m)]
            np.testing.assert_array_equal(reference(a, b), scalar, err_msg=name)
            for physical_k in (k, ((k + 15) // 16) * 16):
                fa, fb = full_tile(a, b, physical_k)
                self.assertEqual(fa.shape, (16, physical_k))
                self.assertEqual(fb.shape, (physical_k, 16))
                np.testing.assert_array_equal(fa[:m, :k], a)
                np.testing.assert_array_equal(fb[:k, :n], b)
                self.assertTrue(np.all(fa[m:] == 0))
                self.assertTrue(np.all(fa[:, k:] == 0))
                self.assertTrue(np.all(fb[k:] == 0))
                self.assertTrue(np.all(fb[:, n:] == 0))
                expected = np.zeros((16, 16), dtype="<i4")
                expected[:m, :n] = reference(a, b)
                np.testing.assert_array_equal(reference(fa, fb), expected)

    def test_export_hex_manifest_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="mxu_model_tile_check_") as temporary:
            destination = Path(temporary) / "vectors"
            manifest = export(destination)
            self.assertEqual(len(manifest), 7)
            self.assertEqual(json.loads((destination / "manifest.json").read_text()), manifest)
            self.assertEqual(len((destination / "cases.txt").read_text().splitlines()), 7)
            for row, (name, a, b) in zip(manifest, model_cases()):
                self.assertEqual(row["case"], name)
                self.assertEqual(row["logical_sha256"], logical_hash(a, b))
                khw = row["K_hw"]
                fa, fb = full_tile(a, b, khw)
                self.assertEqual(row["physical_vector_sha256"], vector_hash(fa, fb))
                self.assertEqual(row["useful_macs"], row["M"] * row["N"] * row["K"])
                self.assertEqual(row["physical_macs"], 256 * khw)

                def unpack(filename, count):
                    lines = (destination / name / filename).read_text().splitlines()
                    self.assertEqual(len(lines), count)
                    self.assertTrue(all(len(line) == 32 for line in lines))
                    return b"".join(int(line, 16).to_bytes(16, "little") for line in lines)

                acts = np.frombuffer(unpack("act.hex", 256), np.int8).reshape(256, 16)
                weights = np.frombuffer(unpack("weight.hex", 256), np.int8).reshape(256, 16)
                np.testing.assert_array_equal(acts[:16 * (khw // 16)].reshape(16, khw), fa)
                np.testing.assert_array_equal(weights[:khw], fb)
                np.testing.assert_array_equal(np.frombuffer(unpack("golden.hex", 64), "<i4").reshape(16, 16), reference(fa, fb))
            with self.assertRaises(FileExistsError):
                export(destination)

    def test_existing_official_host_contract_via_mock(self):
        namespace, log = harness_functions()
        for name, a, b in model_cases():
            fa, fb = full_tile(a, b)
            result = asyncio.run(namespace["_run_case"](
                FullMatrixFixture(), "fake.elf", (name, fa, fb, 1, True),
                input_schedule="model_tile_tk1_full_core_fixture"))
            self.assertEqual(result, 999)  # Synthetic only, not a cycle claim.
        self.assertEqual(len(log.messages), 7)
        with self.assertRaises(AssertionError):
            name, a, b = model_cases()[0]
            fa, fb = full_tile(a, b)
            asyncio.run(namespace["_run_case"](
                FullMatrixFixture(corrupt=True), "fake.elf", (name, fa, fb, 1, True)))
        self.assertEqual(len(log.messages), 7)

    def test_summary_rejects_incomplete_or_changed_result(self):
        records = []
        for name, a, b in model_cases():
            m, k = a.shape
            n = b.shape[1]
            fa, fb = full_tile(a, b)
            for repeat in range(3):
                records.append(dict(case=name, repeat=repeat, M=m, N=n, K=k,
                                    K_hw=k, tk_per_instruction=1,
                                    checked_elements=256, useful_macs=m * n * k,
                                    physical_macs=256 * k,
                                    logical_sha256=logical_hash(a, b),
                                    physical_vector_sha256=vector_hash(fa, fb),
                                    launch_wait_to_halt_cycles=999,
                                    scope="full_core_fixture_not_mxu_unit"))
        rows, digest = summarize(records)
        self.assertEqual(len(rows), 7)
        self.assertEqual(len(digest), 64)
        with self.assertRaises(AssertionError):
            summarize(records[:-1])
        for field, value in (("K", 999), ("M", 0), ("logical_sha256", "wrong"),
                             ("physical_vector_sha256", "wrong"),
                             ("launch_wait_to_halt_cycles", 1000),
                             ("physical_macs", 0)):
            changed = copy.deepcopy(records)
            changed[-1][field] = value
            with self.assertRaises(AssertionError):
                summarize(changed)
        print("[MODEL_TILE_STATIC] cases=7 logical_set_sha256=" + digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
