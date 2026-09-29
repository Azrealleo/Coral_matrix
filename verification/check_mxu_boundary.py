#!/usr/bin/env python3
"""Local reference/export/harness/parser checks. NOT C++ or RTL simulation."""

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
from vme_matrix_boundary_vectors import K_VALUES, boundary_cases
from vme_matrix_stress_vectors import reference, vector_hash
from generate_mxu_boundary import export, packed_inputs
from summarize_google_boundary import summarize
from check_google_burst import FakeFixture, harness_functions


class FullMatrixFixture(FakeFixture):
    """Mock upload contract only; computes full matrices, not a cycle model."""
    async def run_to_halt(self, timeout_cycles):
        assert timeout_cycles == 200000 and self.values["perf_tk"] == 1
        assert np.all(self.values["perf_out"] == 0xDEADBEEF)
        k = self.values["perf_k"]
        a = self.values["perf_a"].view(np.int8).reshape(260, 16)[:k].T.astype(np.int64)
        b = self.values["perf_b"].view(np.int8).reshape(260, 16)[:k].astype(np.int64)
        self.output = (a @ b).astype("<i4")
        if self.corrupt:
            self.output[7, 11] += 1
        self.values.update(perf_status=1, perf_mtype=(16 << 10) | (1 << 5) | 3,
                           perf_vtype=0xC0 | (self.values["perf_signed_b"] << 8))
        return 999  # Explicitly synthetic, not an RTL latency prediction.


class BoundaryTests(unittest.TestCase):
    def test_common_cases_and_independent_scalar_references(self):
        self.assertEqual(tuple(case[1].shape[1] for case in boundary_cases()), K_VALUES)
        self.assertEqual(len(K_VALUES), 21)
        for name, a, b, tk, signed_b in boundary_cases():
            k = a.shape[1]
            self.assertEqual((a.shape, b.shape, tk, signed_b), ((16, k), (k, 16), 1, True))
            self.assertEqual(a.dtype, np.int8)
            self.assertEqual(b.dtype, np.int8)
            scalar = [[sum(int(a[i, p]) * int(b[p, j]) for p in range(k))
                       for j in range(16)] for i in range(16)]
            np.testing.assert_array_equal(reference(a, b), scalar, err_msg=name)

    def test_padded_hex_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="mxu_boundary_check_") as temporary:
            destination = Path(temporary) / "vectors"
            manifest = export(destination)
            self.assertEqual(len(manifest), 21)
            self.assertEqual(json.loads((destination / "manifest.json").read_text()), manifest)
            self.assertEqual((destination / "cases.txt").read_text().splitlines()[:3],
                             ["boundary_k16 16", "boundary_k64 64", "boundary_k256 256"])
            for name, a, b, _, _ in boundary_cases():
                k = a.shape[1]
                chunks = (k + 15) // 16
                acts, weights = packed_inputs(a, b)
                rows = acts[:16 * chunks].reshape(16, chunks * 16)
                np.testing.assert_array_equal(rows[:, :k], a)
                self.assertTrue(np.all(rows[:, k:] == 37))
                self.assertTrue(np.all(acts[16 * chunks:] == 37))
                np.testing.assert_array_equal(weights[:k], b)
                self.assertTrue(np.all(weights[k:] == 53))

                def unpack(filename, count):
                    lines = (destination / name / filename).read_text().splitlines()
                    self.assertEqual(len(lines), count)
                    self.assertTrue(all(len(line) == 32 for line in lines))
                    return b"".join(int(line, 16).to_bytes(16, "little") for line in lines)

                np.testing.assert_array_equal(np.frombuffer(unpack("act.hex", 256), np.int8).reshape(256, 16), acts)
                np.testing.assert_array_equal(np.frombuffer(unpack("weight.hex", 256), np.int8).reshape(256, 16), weights)
                np.testing.assert_array_equal(np.frombuffer(unpack("golden.hex", 64), "<i4").reshape(16, 16), reference(a, b))
                row = next(row for row in manifest if row["case"] == name)
                self.assertEqual(row["act_beats"], 16 * chunks)
                self.assertEqual(row["weight_beats"], k)
                self.assertEqual(row["vector_sha256"], vector_hash(a, b))
            with self.assertRaises(FileExistsError):
                export(destination)

    def test_actual_host_harness_upload_and_rejection(self):
        namespace, log = harness_functions()
        for case in boundary_cases():
            np.testing.assert_array_equal(namespace["_reference"](case[1], case[2]), reference(case[1], case[2]))
            self.assertEqual(namespace["_vector_hash"](case[1], case[2]), vector_hash(case[1], case[2]))
            asyncio.run(namespace["_run_case"](FullMatrixFixture(), "fake.elf", case,
                                               input_schedule="shared_k_boundary_tk1_functional_only"))
        self.assertEqual(len(log.messages), 21)
        for message, case in zip(log.messages, boundary_cases()):
            row = json.loads(message.split("[GOOGLE_MATRIX_PERF] ")[1])
            self.assertEqual(row["matrix_instructions"], case[1].shape[1])
            self.assertEqual(row["checked_elements"], 256)
        with self.assertRaises(AssertionError):
            asyncio.run(namespace["_run_case"](FullMatrixFixture(corrupt=True), "fake.elf", boundary_cases()[0]))
        self.assertEqual(len(log.messages), 21)

    def test_strict_complete_summary(self):
        records = [dict(case=name, K=a.shape[1], checked_elements=256,
                        tk_per_instruction=tk, vector_sha256=vector_hash(a, b))
                   for name, a, b, tk, _ in boundary_cases()]
        row = summarize(records)
        self.assertEqual(row["checked_elements"], 5376)
        self.assertEqual(row["K_values"], list(K_VALUES))
        for field, value in (("K", 16), ("case", "wrong"), ("checked_elements", 255),
                             ("tk_per_instruction", 4), ("vector_sha256", "wrong")):
            changed = copy.deepcopy(records)
            changed[-1][field] = value
            with self.assertRaises(AssertionError):
                summarize(changed)
        with self.assertRaises(AssertionError):
            summarize(records[:-1])
        with self.assertRaises(AssertionError):
            summarize(records[:-1] + records[:1])
        print("[BOUNDARY_STATIC_SUMMARY] " + json.dumps(row, sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
