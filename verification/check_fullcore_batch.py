#!/usr/bin/env python3
"""Static shared-B batch vector/packing/log checks; not RTL simulation."""

import copy
import hashlib
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "coralnpu-google/tests/cocotb/vme_test"))
sys.path.insert(0, str(ROOT / "coralnpu-Yangg152/tests/mxu"))
sys.dont_write_bytecode = True

from mxu_fullcore_tile_vectors import shared_weight_batch_cases as fork_cases  # noqa: E402
from vme_matrix_model_tile_vectors import shared_weight_batch_cases as google_cases  # noqa: E402
from compare_fullcore_batch import compare  # noqa: E402


class SharedWeightBatchTests(unittest.TestCase):
    def test_program_schedule_contract(self):
        google = (ROOT / "coralnpu-google/tests/cocotb/vme_test/"
                  "vme_matrix_shared_weight_batch_program.cc").read_text()
        fork = (ROOT / "coralnpu-Yangg152/tests/mxu/"
                "mxu_fullcore_shared_weight_batch_program.cc").read_text()
        self.assertLess(google.index("for (uint32_t tile = 0; tile < tiles; ++tile)"),
                        google.index("const uint8_t *b = &batch_b[base * kTe]"))
        self.assertIn("if (tile == 0)", fork)
        self.assertLess(fork.index("if (tile == 0)"),
                        fork.index("LoadW(&batch_b[depth * kTile]"))
        self.assertLess(fork.index("Zero();"), fork.index("if (tile == 0)"))

    def test_vectors_packing_and_strict_parser(self):
        g_cases, f_cases = google_cases(), fork_cases()
        self.assertEqual(len(g_cases), 9)
        self.assertEqual(len(f_cases), 9)
        self.assertEqual(len({name for name, _, _ in g_cases}), 9)
        google_rows, fork_rows = [], []
        for (name, a, b), (f_name, fa, fb) in zip(g_cases, f_cases):
            self.assertEqual(name, f_name)
            np.testing.assert_array_equal(a, fa)
            np.testing.assert_array_equal(b, fb)
            tiles, _, k = a.shape
            expected = (a.astype(np.int64) @ b.astype(np.int64)).astype("<i4")
            g_packed = np.zeros((16, 256, 16), dtype=np.int8)
            g_packed[:tiles, :k] = a.transpose(0, 2, 1)
            f_packed = np.zeros((16, 4096), dtype=np.int8)
            for tile in range(tiles):
                f_packed[tile, :16 * k] = a[tile].reshape(-1)
                np.testing.assert_array_equal(g_packed[tile, :k], a[tile].T)
                np.testing.assert_array_equal(
                    f_packed[tile, :16 * k].reshape(16, k), a[tile])
            digest = hashlib.sha256(
                a.tobytes() + b.tobytes() + expected.tobytes()).hexdigest()
            for repeat in range(3):
                common = dict(case=name, repeat=repeat, K=k, tiles=tiles,
                              checked_elements=tiles * 256,
                              useful_macs=tiles * 256 * k,
                              logical_sha256=digest)
                google_rows.append(dict(
                    common, launch_wait_to_halt_cycles=1000 + tiles * k,
                    weight_load_schedule="B_reloaded_from_memory_per_tile",
                    scope="official_tk4_full_core_shared_weight_batch"))
                fork_rows.append(dict(
                    common, launch_wait_to_halt_cycles=2000 + tiles * k,
                    weight_load_schedule="B_loaded_once_into_MXU_SRAM",
                    scope="fork_full_core_shared_weight_batch"))
        paired, digest = compare(google_rows, fork_rows)
        self.assertEqual(len(paired), 9)
        self.assertEqual(len(digest), 64)
        with self.assertRaises(AssertionError):
            compare(google_rows[:-1], fork_rows)
        for field, value in (("K", 17), ("tiles", 2), ("logical_sha256", "wrong"),
                             ("weight_load_schedule", "wrong"),
                             ("launch_wait_to_halt_cycles", 1)):
            changed = copy.deepcopy(fork_rows)
            changed[-1][field] = value
            with self.assertRaises(AssertionError):
                compare(google_rows, changed)
        print("[FULLCORE_BATCH_STATIC] cases=9 repeats=3 logical_set_sha256=" + digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
