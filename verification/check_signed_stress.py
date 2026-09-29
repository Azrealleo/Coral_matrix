#!/usr/bin/env python3
"""Synthetic vector/export/log-parser checks. NO simulator/compiler is used."""

import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "coralnpu-google/tests/cocotb/vme_test"
sys.path.insert(0, str(PACKAGE))
sys.dont_write_bytecode = True
from vme_matrix_stress_vectors import BATCH_NAMES, LEGACY_NAMES, batch_hash, reference, stress_batches, vector_hash
from generate_signed_stress import export_batches
from summarize_signed_stress import summarize


class SignedStressTests(unittest.TestCase):
    def test_shapes_signs_and_scalar_references(self):
        batches = stress_batches()
        self.assertEqual(tuple(batch for batch, _ in batches), BATCH_NAMES)
        for batch, cases in batches:
            self.assertEqual(len(cases), 4)
            for index, (name, a, b, tk, signed_b) in enumerate(cases):
                k = (16, 64, 256, 16)[index]
                self.assertEqual(a.shape, (16, k))
                self.assertEqual(b.shape, (k, 16))
                self.assertEqual(a.dtype, np.int8)
                self.assertEqual(b.dtype, np.int8)
                self.assertEqual(tk, 4)
                self.assertEqual(signed_b, index != 3)
                if index == 3:
                    self.assertTrue(np.all(a >= 0) and np.all(b >= 0))
                elif batch in BATCH_NAMES[:4]:
                    self.assertTrue(np.all(a < 0) if batch.startswith("negative_") else np.all(a > 0))
                    self.assertTrue(np.all(b < 0) if batch.endswith("_negative") else np.all(b > 0))
                elif batch == "all_minus128":
                    np.testing.assert_array_equal(reference(a, b), np.full((16, 16), k * 16384))
                elif batch == "random_seed137":
                    # A random sample need not contain both endpoints. Those
                    # are required explicitly in the separate directed cases.
                    self.assertTrue(np.any(a < 0) and np.any(a > 0))
                    self.assertTrue(np.any(b < 0) and np.any(b > 0))
                else:
                    self.assertTrue(np.any(a == -128) and np.any(a == 127))
                    self.assertTrue(np.any(b == -128) and np.any(b == 127))
                scalar = [[sum(int(a[i, p]) * int(b[p, j]) for p in range(k))
                           for j in range(16)] for i in range(16)]
                np.testing.assert_array_equal(reference(a, b), scalar, err_msg=name)

    def test_export_roundtrip_and_refusal_to_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="signed_stress_check_") as temporary:
            destination = Path(temporary) / "vectors"
            manifest = export_batches(destination)
            self.assertEqual(len(manifest), 32)
            self.assertEqual(json.loads((destination / "manifest.json").read_text()), manifest)
            self.assertEqual((destination / "batches.txt").read_text().splitlines(), list(BATCH_NAMES))
            for batch, cases in stress_batches():
                for legacy, (name, a, b, _, _) in zip(LEGACY_NAMES, cases):
                    directory = destination / batch / "cases"

                    def unpack(suffix):
                        lines = (directory / (legacy + "_" + suffix + ".hex")).read_text().splitlines()
                        self.assertTrue(all(len(line) == 32 for line in lines))
                        return b"".join(int(line, 16).to_bytes(16, "little") for line in lines)

                    k = a.shape[1]
                    np.testing.assert_array_equal(np.frombuffer(unpack("act"), np.int8).reshape(16, k), a)
                    np.testing.assert_array_equal(np.frombuffer(unpack("weight"), np.int8).reshape(k, 16), b)
                    np.testing.assert_array_equal(np.frombuffer(unpack("golden"), "<i4").reshape(16, 16), reference(a, b))
                    cfg = int((directory / (legacy + "_cfg.hex")).read_text(), 16)
                    self.assertEqual(cfg, 0 if k == 256 else k)
                    row = next(row for row in manifest if row["case"] == name)
                    self.assertEqual(row["vector_sha256"], vector_hash(a, b))
            with self.assertRaises(FileExistsError):
                export_batches(destination)
            self.assertEqual(json.loads((destination / "manifest.json").read_text()), manifest)

    def test_official_harness_reference_and_fingerprints(self):
        # Import the actual reference functions without importing Cocotb.
        path = PACKAGE / "vme_matrix_perf_bench.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ("_reference", "_vector_hash")]
        self.assertEqual(len(functions), 2)
        module = ast.Module(body=functions)
        if "type_ignores" in ast.Module._fields:
            module.type_ignores = []
        namespace = dict(np=np, hashlib=hashlib)
        exec(compile(module, str(path), "exec"), namespace)
        for _, cases in stress_batches():
            for _, a, b, _, _ in cases:
                np.testing.assert_array_equal(namespace["_reference"](a, b), reference(a, b))
                self.assertEqual(namespace["_vector_hash"](a, b), vector_hash(a, b))

    def test_deterministic_batch_hashes(self):
        first = [(name, batch_hash(cases)) for name, cases in stress_batches()]
        second = [(name, batch_hash(cases)) for name, cases in stress_batches()]
        self.assertEqual(first, second)
        self.assertEqual(len({digest for _, digest in first}), 8)
        for batch, fingerprint in first:
            print("[SIGNED_STRESS_STATIC_HASH] batch={} batch_sha256={}".format(batch, fingerprint))

    def test_summary_requires_every_matching_record(self):
        records = [dict(batch=batch, case=case[0], K=case[1].shape[1], checked_elements=256,
                        vector_sha256=vector_hash(case[1], case[2]))
                   for batch, cases in stress_batches() for case in cases]
        rows = summarize(records)
        self.assertEqual(len(rows), 8)
        for field, value in (("case", "wrong"), ("K", 64), ("batch", "wrong"),
                             ("checked_elements", 255), ("vector_sha256", "wrong")):
            changed = copy.deepcopy(records)
            changed[-1][field] = value
            with self.assertRaises(AssertionError):
                summarize(changed)
        with self.assertRaises(AssertionError):
            summarize(records[:-1])
        with self.assertRaises(AssertionError):
            summarize(records[:-1] + records[:1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
