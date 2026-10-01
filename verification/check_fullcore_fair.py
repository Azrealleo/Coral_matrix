#!/usr/bin/env python3
"""Local shared-vector/packing/parser checks; not full-core RTL simulation."""

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

from mxu_fullcore_tile_vectors import full_tile as fork_full_tile
from mxu_fullcore_tile_vectors import model_cases as fork_cases
from mxu_fullcore_tile_vectors import logical_hash as fork_hash
from mxu_fullcore_tile_vectors import reference as fork_reference
from vme_matrix_model_tile_vectors import full_tile as google_full_tile
from vme_matrix_model_tile_vectors import model_cases as google_cases
from vme_matrix_model_tile_vectors import logical_hash as google_hash
from compare_fullcore_tiles import compare, compare_three, summarize_fork


class FullcoreFairTests(unittest.TestCase):
    def test_exact_shared_vectors_and_packing(self):
        self.assertEqual(len(fork_cases()), 7)
        for (name, a, b), (gname, ga, gb) in zip(fork_cases(), google_cases()):
            self.assertEqual(name, gname)
            np.testing.assert_array_equal(a, ga)
            np.testing.assert_array_equal(b, gb)
            self.assertEqual(fork_hash(a, b), google_hash(ga, gb))
            m, k = a.shape
            n = b.shape[1]
            k_hw = ((k + 15) // 16) * 16
            fa, fb = fork_full_tile(a, b, k_hw)
            self.assertEqual((fa.shape, fb.shape), ((16, k_hw), (k_hw, 16)))
            google_a, google_b = google_full_tile(ga, gb, k_hw)
            np.testing.assert_array_equal(fa, google_a)
            np.testing.assert_array_equal(fb, google_b)
            packed_a = np.zeros(4096, dtype=np.int8)
            packed_b = np.zeros(4096, dtype=np.int8)
            packed_a[:16 * k_hw] = fa.reshape(-1)
            packed_b[:k_hw * 16] = fb.reshape(-1)
            np.testing.assert_array_equal(packed_a[:16 * k_hw].reshape(16, k_hw), fa)
            np.testing.assert_array_equal(packed_b[:k_hw * 16].reshape(k_hw, 16), fb)
            expected = np.zeros((16, 16), dtype="<i4")
            expected[:m, :n] = fork_reference(a, b)
            np.testing.assert_array_equal(fork_reference(fa, fb), expected)

    def test_strict_pairing_and_changed_data_rejection(self):
        google_records, google_tk4_records, fork_records = [], [], []
        for name, a, b in fork_cases():
            m, k = a.shape
            n = b.shape[1]
            k_hw = ((k + 15) // 16) * 16
            fa, fb = fork_full_tile(a, b, k_hw)
            gfa, gfb = google_full_tile(a, b)
            k4 = ((k + 3) // 4) * 4
            t4a, t4b = google_full_tile(a, b, k4)
            fhash = hashlib.sha256(
                fa.tobytes() + fb.tobytes() + fork_reference(fa, fb).tobytes()).hexdigest()
            ghash = hashlib.sha256(
                gfa.tobytes() + gfb.tobytes() + fork_reference(gfa, gfb).tobytes()).hexdigest()
            t4hash = hashlib.sha256(
                t4a.tobytes() + t4b.tobytes() + fork_reference(t4a, t4b).tobytes()).hexdigest()
            for repeat in range(3):
                common = dict(case=name, repeat=repeat, M=m, N=n, K=k,
                              checked_elements=256, useful_macs=m * n * k,
                              logical_sha256=fork_hash(a, b))
                google_records.append(dict(common, K_hw=k, tk_per_instruction=1,
                                           physical_macs=256 * k,
                                           physical_vector_sha256=ghash,
                                           launch_wait_to_halt_cycles=999,
                                           scope="full_core_fixture_not_mxu_unit"))
                google_tk4_records.append(dict(common, K_hw=k4, tk_per_instruction=4,
                                               physical_macs=256 * k4,
                                               physical_vector_sha256=t4hash,
                                               launch_wait_to_halt_cycles=888,
                                               scope="official_tk4_full_core_fixture_not_array_only"))
                fork_records.append(dict(common, K_hw=k_hw, physical_macs=256 * k_hw,
                                         physical_vector_sha256=fhash,
                                         launch_wait_to_halt_cycles=777,
                                         scope="fork_full_core_fixture_not_standalone_unit"))
        paired, digest = compare(google_records, fork_records)
        self.assertEqual(len(paired), 7)
        self.assertEqual(digest, "87085fb87e02f0b4d28c7de2aa256e55df836807842fe899538367211c72fbda")
        self.assertTrue(all(row["google_fullcore_cycles"] == 999 and
                            row["fork_fullcore_cycles"] == 777 for row in paired))
        paired_three, digest_three = compare_three(google_records, google_tk4_records,
                                                  fork_records)
        self.assertEqual(digest_three, digest)
        self.assertEqual(len(paired_three), 7)
        self.assertTrue(all(row["google_tk4_fullcore_cycles"] == 888 for row in paired_three))
        with self.assertRaises(AssertionError):
            summarize_fork(fork_records[:-1])
        for field, value in (("K_hw", 17), ("logical_sha256", "wrong"),
                             ("physical_vector_sha256", "wrong"),
                             ("launch_wait_to_halt_cycles", 778),
                             ("scope", "wrong")):
            changed = copy.deepcopy(fork_records)
            changed[-1][field] = value
            with self.assertRaises(AssertionError):
                compare(google_records, changed)
        changed_tk4 = copy.deepcopy(google_tk4_records)
        changed_tk4[-1]["physical_vector_sha256"] = "wrong"
        with self.assertRaises(AssertionError):
            compare_three(google_records, changed_tk4, fork_records)
        print("[FULLCORE_FAIR_STATIC] cases=7 logical_set_sha256=" + digest)

    def test_program_contract_and_syntax(self):
        text = (ROOT / "coralnpu-Yangg152/tests/mxu/mxu_fullcore_tile_program.cc").read_text()
        self.assertIn("bench_a[row * k + chunk * kTile]", text)
        self.assertIn("bench_b[depth * kTile]", text)
        self.assertIn("bench_out[beat * 4]", text)
        self.assertLess(text.index('asm volatile("vsetvli zero, %0, e8, m1'),
                        text.index("Configure(k);"))
        self.assertIn("Configure(k);", text)
        self.assertIn("Zero();", text)
        self.assertIn("MultiplyAccumulate();", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
