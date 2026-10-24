import importlib.util
import math
from pathlib import Path
import unittest

from analyze import attribute_vectors, check_observed, errors, f32, stages


class AnalysisTests(unittest.TestCase):
    def test_original_frozen_fixtures_reproduced(self):
        # Host reference source only, not an RVV implementation/execution.
        path = Path(__file__).resolve().parents[1]/'google_llm_ops/transformer/tx_spec.py'
        module = importlib.util.module_from_spec(importlib.util.spec_from_file_location('fixture', path))
        module.__spec__.loader.exec_module(module)
        cases = (('residual256', 'RESIDUAL', (256,0,0,0,0)),
                 ('rms64', 'RMS', (1,64,0,0,0)),
                 ('rms_tail37', 'RMS', (3,37,0,0,0)),
                 ('gelu32', 'GEGLU', (32,0,0,0,0)),
                 ('gelu_tail37', 'GEGLU', (37,0,0,0,0)),
                 ('gelu256', 'GEGLU', (256,0,0,0,0)))
        module.CASES = cases
        for index, count in ((3,26), (4,33), (5,215)):
            fixture = module.fixture(index)
            result = attribute_vectors(fixture['x'], fixture['w'], fixture['y'])
            self.assertEqual(result['clipped_elements'], 0)
            self.assertEqual(result['clipping_increment_max'], 0)
            self.assertEqual(result['metrics']['rational']['failed_elements'], count)
            self.assertEqual(result['metrics']['coefficients_only']['failed_elements'], 0)

    def test_error_not_explained_by_clamping_or_coefficients(self):
        result = attribute_vectors([2.0], [2.0])
        self.assertEqual(result['clipped_elements'], 0)
        self.assertGreater(result['metrics']['rational']['max_abs_error'], 0.04)
        self.assertLess(result['coefficient_delta_max'], 1e-6)

    def test_clamp_can_matter_outside_existing_fixtures(self):
        result = attribute_vectors([3.0], [1.0])
        self.assertEqual(result['clipped_elements'], 1)
        self.assertGreater(result['clipping_increment_max'], 0)

    def test_zero_and_negative_up(self):
        for x in (-8., -2., -1e-5, 0., 1e-5, 2., 8.):
            self.assertEqual(stages(x, 0.)['rational'], 0)
            self.assertEqual(stages(x, -1.)['rational'], -stages(x, 1.)['rational'])
        self.assertEqual(stages(0., 2.)['rational'], 0)

    def test_invalid_inputs_fail_closed(self):
        for x in (float('nan'), float('inf'), -float('inf')):
            with self.assertRaises(ValueError):
                stages(x, 1.)
            with self.assertRaises(ValueError):
                stages(1., x)
        for x, up in (([],[]), ([1.],[])):
            with self.assertRaises(ValueError):
                attribute_vectors(x, up)
        with self.assertRaises(ValueError):
            errors([float('nan')], [0.])

    def test_reference_cannot_be_replaced_to_make_quality_pass(self):
        with self.assertRaises(ValueError):
            attribute_vectors([2.], [2.], [stages(2.,2.)['rational']])

    def test_wrong_hardware_attribution_rejected(self):
        result = attribute_vectors([2.], [2.])
        row = dict(strict_math_quality_mismatches=4,
                   official_max_math_abs_error=result['metrics']['rational']['max_abs_error'],
                   official_max_algorithm_abs_error=0.)
        self.assertTrue(check_observed(result, row)['rtl_failure_count_matches'])
        for key, value in (('strict_math_quality_mismatches', 0),
                           ('official_max_math_abs_error', 0.)):
            bad = dict(row); bad[key] = value
            with self.assertRaises(ValueError):
                check_observed(result, bad)


if __name__ == '__main__':
    unittest.main()
