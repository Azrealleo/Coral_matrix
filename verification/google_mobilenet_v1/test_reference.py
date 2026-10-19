"""Host-golden scaffolding checks, never an NPU/RTL or accuracy claim."""
import json
from pathlib import Path
import unittest

import numpy as np

from reference import MODEL_SHA256, digest, inputs, require_model


class ReferenceTests(unittest.TestCase):
    def test_case_names_and_interface(self):
        cases = list(inputs())
        self.assertEqual([n for n, _ in cases], ["neutral128", "ramp", "checker"])
        for _, array in cases:
            self.assertEqual(array.shape, (1, 224, 224, 3))
            self.assertEqual(array.dtype, np.uint8)

    def test_neutral_is_quantized_zero(self):
        self.assertTrue(np.all(list(inputs())[0][1] == 128))

    def test_ramp_full_byte_range(self):
        array = list(inputs())[1][1].ravel()
        self.assertTrue(np.array_equal(array[:256], np.arange(256, dtype=np.uint8)))
        self.assertEqual(array[-1], 255)

    def test_checker(self):
        array = list(inputs())[2][1]
        self.assertEqual(array[0, 0, 0, 0], 0)
        self.assertEqual(array[0, 0, 0, 1], 255)
        self.assertEqual(array[0, 1, 0, 0], 255)
        self.assertEqual(set(np.unique(array)), {0, 255})

    def test_inputs_are_reproducible(self):
        for (name, first), (other, second) in zip(inputs(), inputs()):
            self.assertEqual(name, other)
            self.assertTrue(np.array_equal(first, second))
            self.assertEqual(digest(first.tobytes()), digest(second.tobytes()))

    def test_model_substitution_refused(self):
        with self.assertRaises(ValueError):
            require_model(b"different model")

    def test_optional_actual_golden_files(self):
        root = (Path(__file__).resolve().parents[2] / ".upstream-git/model-cache"
                / "mobilenet_v1_2018_08_02/reference_builtin_ref_v1")
        if not (root / "manifest.json").is_file():
            self.skipTest("Optional host-golden run absent; no inference/RTL is started")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "PASS")
        self.assertEqual(manifest["model_sha256"], MODEL_SHA256)
        self.assertEqual(manifest["op_resolver"], "BUILTIN_REF")
        self.assertEqual(manifest["delegates"], [])
        self.assertEqual(manifest["repetitions_per_case"], 2)
        self.assertEqual(manifest["checked_operator_outputs_per_repeat"], 93)
        self.assertEqual(len(manifest["cases"]), 3)
        for case, (name, data) in zip(manifest["cases"], inputs()):
            self.assertEqual(case["name"], name)
            case_dir = root / name
            self.assertTrue(np.array_equal(np.load(case_dir / "input.npy", allow_pickle=False), data))
            self.assertEqual(case["input_sha256"], digest(data.tobytes()))
            output = np.load(case_dir / "output.npy", allow_pickle=False)
            self.assertEqual(output.shape, (1, 1001))
            self.assertEqual(output.dtype, np.uint8)
            self.assertEqual(digest(output.tobytes()), case["output_sha256"])
            self.assertEqual(len(case["operator_outputs"]), 31)
            for row in case["operator_outputs"]:
                tensor = np.load(case_dir / row["file"], allow_pickle=False)
                self.assertEqual(digest(tensor.tobytes()), row["data_sha256"])
                self.assertEqual(list(tensor.shape), row["shape"])
                self.assertEqual(tensor.nbytes, row["bytes"])


if __name__ == "__main__":
    unittest.main()
