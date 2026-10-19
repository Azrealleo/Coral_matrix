"""Host reference for official person/no-person fixtures, NOT NPU execution."""
import argparse
from importlib import metadata
import io
import json
from pathlib import Path
import platform
import sys

import numpy as np
from PIL import Image

from spec import LABELS, MODEL_NAME, MODEL_SHA256, TFLM_COMMIT, checked_asset, sha

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "google_mobilenet_v1"))
from inspect_model import inspect_bytes


def fixture(data):
    """Match pinned TFLM generate_cc_arrays.py: decoded BMP bytes, no subtraction."""
    with Image.open(io.BytesIO(data)) as image:
        if image.mode != "L" or image.size != (96, 96):
            raise ValueError("Expected the pinned 96x96 grayscale fixture")
        raw = image.tobytes()
    if len(raw) != 9216:
        raise ValueError("Unexpected image payload")
    # The official test memcpy's these bytes into int8 input. They are already
    # tensor-encoded; subtracting 128 again would change the official fixture.
    return np.frombuffer(raw, dtype=np.int8).copy().reshape(1, 96, 96, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = checked_asset(args.assets, MODEL_NAME)
    inventory = inspect_bytes(data)
    if (inventory["inputs"][0]["shape"] != [1, 96, 96, 1]
            or inventory["inputs"][0]["dtype"] != "INT8"
            or inventory["outputs"][0]["shape"] != [1, 2]
            or inventory["outputs"][0]["dtype"] != "INT8"):
        raise ValueError("Unexpected model interface")
    from ai_edge_litert.interpreter import Interpreter, OpResolverType
    interpreter = Interpreter(model_content=data, num_threads=1, experimental_delegates=[],
                              experimental_op_resolver_type=OpResolverType.BUILTIN_REF,
                              experimental_preserve_all_tensors=True)
    interpreter.allocate_tensors()
    input_id = interpreter.get_input_details()[0]["index"]
    output_id = interpreter.get_output_details()[0]["index"]
    if input_id != inventory["inputs"][0]["index"] or output_id != inventory["outputs"][0]["index"]:
        raise ValueError("Runtime/static tensor index mismatch")
    args.output.mkdir(parents=False, exist_ok=False)
    manifest = dict(schema=1, status="INCOMPLETE", scope="host_reference_not_NPU_RTL_or_dataset_accuracy",
                    tflm_commit=TFLM_COMMIT, model_sha256=MODEL_SHA256, labels=list(LABELS),
                    op_resolver="BUILTIN_REF", delegates=[], repeats=2,
                    python=platform.python_version(),
                    versions={key: metadata.version(key) for key in
                              ("ai-edge-litert", "numpy", "flatbuffers", "tflite", "Pillow")}, cases=[])
    path = args.output / "manifest.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
    for name in ("person", "no_person"):
        raw = checked_asset(args.assets, name + ".bmp")
        image = fixture(raw)
        interpreter.set_tensor(input_id, image)
        interpreter.invoke()
        outputs = []
        for op in inventory["operators"]:
            for index in op["outputs"]:
                outputs.append((op["index"], index, interpreter.get_tensor(index)))
        actual = interpreter.get_tensor(output_id)
        if actual.shape != (1, 2) or actual.dtype != np.int8:
            raise ValueError("Unexpected output")
        scores = actual.ravel().tolist()
        expected_class = LABELS.index(name)
        if scores[expected_class] <= scores[1 - expected_class]:
            raise ValueError("Official fixture classification failed: " + name + " " + str(scores))
        interpreter.set_tensor(input_id, image)
        interpreter.invoke()
        for _, index, first in outputs:
            if not np.array_equal(first, interpreter.get_tensor(index)):
                raise ValueError("Reference repeats differ")
        case_dir = args.output / name
        case_dir.mkdir()
        np.save(case_dir / "input.npy", image, allow_pickle=False)
        np.save(case_dir / "output.npy", actual, allow_pickle=False)
        rows = []
        for op, index, tensor in outputs:
            filename = "op%02d_t%d.npy" % (op, index)
            np.save(case_dir / filename, tensor, allow_pickle=False)
            rows.append(dict(operator=op, tensor=index, dtype=tensor.dtype.name, shape=list(tensor.shape),
                             file=filename, sha256=sha(tensor.tobytes())))
        case = dict(name=name, input_sha256=sha(image.tobytes()), output_sha256=sha(actual.tobytes()),
                    scores=scores, expected_class=expected_class, classified_correctly=True,
                    repeats_bitwise_equal=True, operator_outputs=rows)
        manifest["cases"].append(case)
        print("[PERSON_HOST_REFERENCE_CASE] " + json.dumps({k: case[k] for k in
              ("name", "input_sha256", "scores", "classified_correctly", "repeats_bitwise_equal")}), flush=True)
    manifest["status"] = "PASS"
    with path.open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    print("[PERSON_HOST_REFERENCE_PASS] cases=2 repeats=2 NPU_RTL=NOT_RUN directory=" + str(args.output.resolve()))


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print("[PERSON_LITERT_REFERENCE_NOT_ACCEPTED] " + str(error), file=sys.stderr)
        print("Original model is unchanged. Use the pinned native TFLM test; no reference PASS asserted.", file=sys.stderr)
        raise SystemExit(1)
