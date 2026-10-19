"""Local parser tests only; no inference, firmware compilation, or RTL PASS."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import flatbuffers
import tflite

from inspect_model import inspect_bytes, storage_bytes


def fixture(shape=(1, 1001), dynamic=False, variable=False):
    b = flatbuffers.Builder(1024)

    def ints(start, values):
        start(b, len(values))
        for v in reversed(values):
            b.PrependInt32(v)
        return b.EndVector()

    def offsets(start, values):
        start(b, len(values))
        for v in reversed(values):
            b.PrependUOffsetTRelative(v)
        return b.EndVector()

    name = b.CreateString("input_and_output")
    dims = ints(tflite.TensorStartShapeVector, shape)
    signature = ints(tflite.TensorStartShapeSignatureVector, (-1, 1001)) if dynamic else None
    tflite.TensorStart(b)
    tflite.TensorAddName(b, name)
    tflite.TensorAddShape(b, dims)
    tflite.TensorAddType(b, tflite.TensorType.UINT8)
    tflite.TensorAddIsVariable(b, variable)
    if signature:
        tflite.TensorAddShapeSignature(b, signature)
    tensor = tflite.TensorEnd(b)
    tensors = offsets(tflite.SubGraphStartTensorsVector, [tensor])
    ins = ints(tflite.SubGraphStartInputsVector, [0])
    outs = ints(tflite.SubGraphStartOutputsVector, [0])
    tflite.SubGraphStart(b)
    tflite.SubGraphAddTensors(b, tensors)
    tflite.SubGraphAddInputs(b, ins)
    tflite.SubGraphAddOutputs(b, outs)
    graph = tflite.SubGraphEnd(b)
    graphs = offsets(tflite.ModelStartSubgraphsVector, [graph])
    tflite.BufferStart(b)
    buffer = tflite.BufferEnd(b)
    buffers = offsets(tflite.ModelStartBuffersVector, [buffer])
    tflite.ModelStart(b)
    tflite.ModelAddVersion(b, 3)
    tflite.ModelAddSubgraphs(b, graphs)
    tflite.ModelAddBuffers(b, buffers)
    model = tflite.ModelEnd(b)
    b.Finish(model, file_identifier=b"TFL3")
    return bytes(b.Output())


class InventoryTests(unittest.TestCase):
    def test_uint8_shape(self):
        self.assertEqual(storage_bytes([1, 224, 224, 3], "UINT8"), 150528)

    def test_int32_and_int4(self):
        self.assertEqual(storage_bytes([16, 16], "INT32"), 1024)
        self.assertEqual(storage_bytes([3], "INT4"), 2)

    def test_scalar_and_empty(self):
        self.assertEqual(storage_bytes([], "INT32"), 4)
        self.assertEqual(storage_bytes([0, 4], "UINT8"), 0)

    def test_unsupported_storage(self):
        for shape, dtype in [([-1, 3], "UINT8"), ([2], "STRING")]:
            with self.assertRaises(ValueError):
                storage_bytes(shape, dtype)

    def test_model_roundtrip_and_scope(self):
        report = inspect_bytes(fixture())
        self.assertEqual(report["outputs"][0]["shape"], [1, 1001])
        self.assertEqual(report["outputs"][0]["bytes"], 1001)
        self.assertEqual(report["operator_counts"], {})
        self.assertEqual(report["constant_buffer_bytes"], 0)
        self.assertIn("not_inference", report["scope"])
        self.assertTrue(report["itcm_requirement"].startswith("NOT_MEASURED"))

    def test_larger_than_dtcm(self):
        report = inspect_bytes(fixture((1, 112, 112, 64)))
        self.assertEqual(report["largest_nonconstant_tensor"]["bytes"], 802816)
        self.assertEqual(report["whole_tensor_over_dtcm"], [0])

    def test_dynamic_refused(self):
        with self.assertRaises(ValueError):
            inspect_bytes(fixture(dynamic=True))

    def test_variable_refused(self):
        with self.assertRaises(ValueError):
            inspect_bytes(fixture(variable=True))

    def test_wrong_file_refused(self):
        for data in (b"", b"01234567", fixture().replace(b"TFL3", b"NOPE", 1)):
            with self.assertRaises(ValueError):
                inspect_bytes(data)

    def test_invalid_budget(self):
        with self.assertRaises(ValueError):
            inspect_bytes(fixture(), 0)

    def test_report_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model, report = root / "model.tflite", root / "report.json"
            model.write_bytes(fixture())
            report.write_text("KEEP", encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).with_name("inspect_model.py")),
                                     str(model), "--output", str(report)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report.read_text(encoding="utf-8"), "KEEP")

    def test_official_candidate_if_downloaded(self):
        model = (Path(__file__).resolve().parents[2] / ".upstream-git/model-cache"
                 / "mobilenet_v1_2018_08_02/mobilenet_v1_1.0_224_quant.tflite")
        if not model.is_file():
            self.skipTest("Optional original model not downloaded; no RTL is run")
        data = model.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         "ecc3a67c47c5a609ec35f6a58a7d97532834e43df4cb7d3f1204a8164b7d20dd")
        report = inspect_bytes(data)
        self.assertEqual(report["operator_counts"], {"CONV_2D": 15, "DEPTHWISE_CONV_2D": 13,
                         "AVERAGE_POOL_2D": 1, "RESHAPE": 1, "SOFTMAX": 1})
        self.assertEqual(report["outputs"][0]["shape"], [1, 1001])
        self.assertEqual(report["inputs"][0]["dtype"], "UINT8")
        self.assertEqual(report["largest_nonconstant_tensor"]["bytes"], 802816)
        self.assertEqual(report["constant_buffer_bytes"], 4257900)


if __name__ == "__main__":
    unittest.main()
