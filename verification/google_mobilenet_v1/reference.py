"""Generate host BUILTIN_REF golden tensors. This is NOT an NPU/RTL test."""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import time

import numpy as np

from inspect_model import inspect_bytes

MODEL_SHA256 = "ecc3a67c47c5a609ec35f6a58a7d97532834e43df4cb7d3f1204a8164b7d20dd"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inputs():
    """Deterministic byte-pattern probes, NOT photos or ImageNet accuracy cases."""
    shape = (1, 224, 224, 3)
    yield "neutral128", np.full(shape, 128, dtype=np.uint8)
    yield "ramp", (np.arange(np.prod(shape), dtype=np.uint32) % 256).astype(np.uint8).reshape(shape)
    y, x, c = np.indices(shape[1:], dtype=np.uint32)
    yield "checker", (((y + x + c) % 2) * 255).astype(np.uint8)[None, ...]


def require_model(data):
    if digest(data) != MODEL_SHA256:
        raise ValueError("Unexpected model bytes; never silently replace the fixed candidate")
    report = inspect_bytes(data)
    if (len(report["inputs"]) != 1 or len(report["outputs"]) != 1
            or report["inputs"][0]["shape"] != [1, 224, 224, 3]
            or report["inputs"][0]["dtype"] != "UINT8"
            or report["outputs"][0]["shape"] != [1, 1001]
            or report["outputs"][0]["dtype"] != "UINT8"):
        raise ValueError("Unexpected model interface")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New directory, never overwritten")
    args = parser.parse_args()
    data = args.model.read_bytes()
    inventory = require_model(data)
    from ai_edge_litert.interpreter import Interpreter, OpResolverType

    # Explicit reference kernels, no external delegates, one thread. Preserve
    # intermediates to produce a separate per-operator regression oracle.
    interpreter = Interpreter(model_content=data, num_threads=1,
                              experimental_delegates=[],
                              experimental_op_resolver_type=OpResolverType.BUILTIN_REF,
                              experimental_preserve_all_tensors=True)
    interpreter.allocate_tensors()
    input_info, output_info = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
    if (input_info["index"] != inventory["inputs"][0]["index"]
            or output_info["index"] != inventory["outputs"][0]["index"]
            or tuple(input_info["shape"]) != (1, 224, 224, 3)
            or tuple(output_info["shape"]) != (1, 1001)
            or input_info["dtype"] != np.uint8 or output_info["dtype"] != np.uint8):
        raise ValueError("Runtime interface does not match static inspection")
    args.output.mkdir(parents=False, exist_ok=False)
    manifest = dict(schema=1, scope="host_litert_builtin_ref_not_NPU_or_RTL_or_accuracy",
                    status="INCOMPLETE", model_sha256=MODEL_SHA256,
                    runtime={key: metadata.version(key) for key in
                             ("ai-edge-litert", "numpy", "flatbuffers", "tflite")},
                    python=platform.python_version(), platform=platform.platform(),
                    op_resolver="BUILTIN_REF", delegates=[], num_threads=1,
                    repetitions_per_case=2, cases=[])
    started = time.perf_counter()
    manifest_path = args.output / "manifest.json"
    # An interrupted directory is explicitly incomplete and is never reused.
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    for name, input_data in inputs():
        case_dir = args.output / name
        case_dir.mkdir()
        interpreter.set_tensor(input_info["index"], input_data)
        interpreter.invoke()
        tensors, rows = [], []
        for operator in inventory["operators"]:
            for tensor_id in operator["outputs"]:
                result = interpreter.get_tensor(tensor_id)
                expected = inventory["tensors"][tensor_id]
                if list(result.shape) != expected["shape"] or result.dtype.name.upper() != expected["dtype"]:
                    raise ValueError("Intermediate shape/type differs from fixed graph")
                filename = "op%02d_t%d.npy" % (operator["index"], tensor_id)
                np.save(case_dir / filename, result, allow_pickle=False)
                tensors.append((tensor_id, result))
                rows.append(dict(operator=operator["index"], name=operator["name"],
                                 tensor=tensor_id, shape=list(result.shape), dtype=result.dtype.name,
                                 bytes=result.nbytes, data_sha256=digest(result.tobytes()), file=filename))
        output = interpreter.get_tensor(output_info["index"])
        # Repeat independently from the input and compare every operator output.
        interpreter.set_tensor(input_info["index"], input_data)
        interpreter.invoke()
        for tensor_id, previous in tensors:
            if not np.array_equal(previous, interpreter.get_tensor(tensor_id)):
                raise ValueError("Repeated reference inference is not bitwise stable")
        np.save(case_dir / "input.npy", input_data, allow_pickle=False)
        np.save(case_dir / "output.npy", output, allow_pickle=False)
        flat = output.ravel()
        top5 = sorted(range(flat.size), key=lambda i: (-int(flat[i]), i))[:5]
        case = dict(name=name, input_sha256=digest(input_data.tobytes()),
                    output_sha256=digest(output.tobytes()), output_elements=int(output.size),
                    top5_indices=top5, top5_uint8_values=[int(flat[i]) for i in top5],
                    operator_outputs=rows, repeats_bitwise_equal=True,
                    input_kind="synthetic_byte_pattern_not_accuracy_image")
        with (case_dir / "case.json").open("x", encoding="utf-8") as stream:
            json.dump(case, stream, indent=2)
            stream.write("\n")
        manifest["cases"].append(case)
        print("[MOBILENET_HOST_REFERENCE_CASE] " + json.dumps(
            {k: case[k] for k in ("name", "output_elements", "output_sha256", "repeats_bitwise_equal")}),
            flush=True)
    manifest["status"] = "PASS"
    manifest["host_wall_seconds"] = time.perf_counter() - started
    manifest["checked_operator_outputs_per_repeat"] = sum(
        len(c["operator_outputs"]) for c in manifest["cases"])
    # This is the newly created manifest owned by this invocation, not an old result.
    with manifest_path.open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    print("[MOBILENET_HOST_REFERENCE_PASS] " + json.dumps({
        "cases": len(manifest["cases"]), "repeats": 2,
        "scope": manifest["scope"], "host_wall_seconds": manifest["host_wall_seconds"],
        "directory": str(args.output.resolve())}), flush=True)


if __name__ == "__main__":
    main()
