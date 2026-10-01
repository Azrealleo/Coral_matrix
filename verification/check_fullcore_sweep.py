#!/usr/bin/env python3
"""Static vector and strict log-pairing checks; no RTL simulation here."""

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

from mxu_fullcore_tile_vectors import (  # noqa: E402
    full_tile as fork_full_tile, logical_hash, reference,
    speed_sweep_cases as fork_cases,
)
from vme_matrix_model_tile_vectors import (  # noqa: E402
    full_tile as official_full_tile,
    speed_sweep_cases as official_cases,
)
from compare_fullcore_sweep import compare  # noqa: E402


class FullcoreSweepTests(unittest.TestCase):
    def test_vectors_and_parser(self):
        fork = fork_cases()
        official = official_cases()
        self.assertEqual(len(fork), 22)
        self.assertEqual(len(official), 22)
        self.assertEqual(len({name for name, _, _ in fork}), 22)
        google_rows, fork_rows = [], []
        for (name, a, b), (other_name, oa, ob) in zip(fork, official):
            self.assertEqual(name, other_name)
            np.testing.assert_array_equal(a, oa)
            np.testing.assert_array_equal(b, ob)
            m, k = a.shape
            n = b.shape[1]
            f_k = ((k + 15) // 16) * 16
            g_k = ((k + 3) // 4) * 4
            fa, fb = fork_full_tile(a, b, f_k)
            ga, gb = official_full_tile(a, b, g_k)
            expected = np.zeros((16, 16), dtype="<i4")
            expected[:m, :n] = reference(a, b)
            np.testing.assert_array_equal(reference(fa, fb), expected)
            np.testing.assert_array_equal(reference(ga, gb), expected)
            f_hash = hashlib.sha256(
                fa.tobytes() + fb.tobytes() + expected.tobytes()).hexdigest()
            g_hash = hashlib.sha256(
                ga.tobytes() + gb.tobytes() + expected.tobytes()).hexdigest()
            for repeat in range(3):
                common = dict(case=name, repeat=repeat, M=m, N=n, K=k,
                              checked_elements=256, useful_macs=m * n * k,
                              logical_sha256=logical_hash(a, b))
                google_rows.append(dict(common, K_hw=g_k, tk_per_instruction=4,
                                        physical_macs=256 * g_k,
                                        physical_vector_sha256=g_hash,
                                        launch_wait_to_halt_cycles=1000 + k,
                                        scope="official_tk4_full_core_speed_sweep"))
                fork_rows.append(dict(common, K_hw=f_k, physical_macs=256 * f_k,
                                      physical_vector_sha256=f_hash,
                                      launch_wait_to_halt_cycles=2000 + k,
                                      scope="fork_full_core_speed_sweep"))
        paired, digest = compare(google_rows, fork_rows)
        self.assertEqual(len(paired), 22)
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(row["google_tk4_fullcore_cycles"] <
                            row["fork_fullcore_cycles"] for row in paired))
        with self.assertRaises(AssertionError):
            compare(google_rows[:-1], fork_rows)
        for field, value in (("K_hw", 1), ("logical_sha256", "wrong"),
                             ("physical_vector_sha256", "wrong"),
                             ("launch_wait_to_halt_cycles", 1),
                             ("scope", "wrong")):
            changed = copy.deepcopy(fork_rows)
            changed[-1][field] = value
            with self.assertRaises(AssertionError):
                compare(google_rows, changed)
        print("[FULLCORE_SWEEP_STATIC] cases=22 repeats=3 logical_set_sha256=" + digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
