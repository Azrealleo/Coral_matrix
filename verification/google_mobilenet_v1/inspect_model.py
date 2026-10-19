"""Static TFLite inventory, NOT inference, an arena planner, or an ITCM estimate."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import tflite


def enum_names(cls):
    return {v: k for k, v in vars(cls).items() if k.isupper() and isinstance(v, int)}


TYPE_NAMES = enum_names(tflite.TensorType)
OP_NAMES = enum_names(tflite.BuiltinOperator)
TYPE_BITS = {
    "FLOAT32": 32, "FLOAT16": 16, "INT32": 32, "UINT8": 8,
    "INT64": 64, "BOOL": 8, "INT16": 16, "COMPLEX64": 64,
    "INT8": 8, "FLOAT64": 64, "COMPLEX128": 128, "UINT64": 64,
    "UINT32": 32, "UINT16": 16, "INT4": 4, "BFLOAT16": 16,
}


def storage_bytes(shape, dtype):
    if dtype not in TYPE_BITS or any(d < 0 for d in shape):
        raise ValueError("Only fixed-size numeric tensors can be budgeted")
    elements = 1
    for d in shape:
        elements *= d
    return (elements * TYPE_BITS[dtype] + 7) // 8


def vector(obj, name):
    return [int(getattr(obj, name)(i)) for i in range(getattr(obj, name + "Length")())]


def text(raw):
    return raw.decode("utf-8") if raw else ""


def numeric_options(operator, name):
    fields = {
        "CONV_2D": ("Conv2DOptions", ["Padding", "StrideH", "StrideW",
                    "DilationHFactor", "DilationWFactor", "FusedActivationFunction"]),
        "DEPTHWISE_CONV_2D": ("DepthwiseConv2DOptions", ["Padding", "StrideH", "StrideW",
                              "DepthMultiplier", "DilationHFactor", "DilationWFactor",
                              "FusedActivationFunction"]),
        "AVERAGE_POOL_2D": ("Pool2DOptions", ["Padding", "StrideH", "StrideW",
                            "FilterHeight", "FilterWidth", "FusedActivationFunction"]),
    }
    if name not in fields:
        return {}
    cls, members = fields[name]
    table = operator.BuiltinOptions()
    if table is None:
        return {}
    options = getattr(tflite, cls)()
    options.Init(table.Bytes, table.Pos)
    return {key: int(getattr(options, key)()) for key in members}


def inspect_bytes(data, dtcm_bytes=512 * 1024):
    if len(data) < 8 or data[4:8] != b"TFL3":
        raise ValueError("Not a TFL3 FlatBuffer")
    if dtcm_bytes <= 0:
        raise ValueError("DTCM budget must be positive")
    model = tflite.Model.GetRootAsModel(data, 0)
    if model.Version() != 3 or model.SubgraphsLength() != 1:
        raise ValueError("Only schema 3, single-subgraph models are supported here")
    graph = model.Subgraphs(0)
    tensors = []
    constants = set()
    for i in range(graph.TensorsLength()):
        tensor = graph.Tensors(i)
        shape = vector(tensor, "Shape")
        if tensor.IsVariable() or any(d < 0 for d in vector(tensor, "ShapeSignature")):
            raise ValueError("Variable or dynamic tensors require separate analysis")
        dtype = TYPE_NAMES.get(tensor.Type(), str(tensor.Type()))
        buffer_id = tensor.Buffer()
        if buffer_id >= model.BuffersLength():
            raise ValueError("Invalid tensor buffer index")
        buffer = model.Buffers(buffer_id)
        if buffer.Offset() or buffer.Size():
            raise ValueError("External FlatBuffer buffers are not supported here")
        constant_bytes = buffer.DataLength()
        if tensor.Sparsity() is not None:
            raise ValueError("Sparse tensors require separate storage analysis")
        if constant_bytes:
            constants.add(buffer_id)
        q = tensor.Quantization()
        quantization = None if q is None else {
            "scale": [float(q.Scale(j)) for j in range(q.ScaleLength())],
            "zero_point": vector(q, "ZeroPoint"),
            "quantized_dimension": int(q.QuantizedDimension()),
        }
        tensors.append(dict(index=i, name=text(tensor.Name()), shape=shape, dtype=dtype,
                            bytes=storage_bytes(shape, dtype), buffer=buffer_id,
                            constant_bytes=constant_bytes, quantization=quantization))

    def valid_indices(indices):
        if any(i < 0 or i >= len(tensors) for i in indices):
            raise ValueError("Invalid tensor index")
        return indices

    inputs = valid_indices(vector(graph, "Inputs"))
    outputs = valid_indices(vector(graph, "Outputs"))
    operators = []
    for i in range(graph.OperatorsLength()):
        operator = graph.Operators(i)
        if operator.OpcodeIndex() >= model.OperatorCodesLength():
            raise ValueError("Invalid operator code index")
        code = model.OperatorCodes(operator.OpcodeIndex())
        builtin = max(code.BuiltinCode(), code.DeprecatedBuiltinCode())
        name = OP_NAMES.get(builtin, "UNKNOWN_" + str(builtin))
        ins = valid_indices([j for j in vector(operator, "Inputs") if j != -1])
        outs = valid_indices(vector(operator, "Outputs"))
        io = sorted(set(ins + outs))
        resident = sum(tensors[j]["bytes"] for j in io if not tensors[j]["constant_bytes"])
        operators.append(dict(index=i, name=name, version=int(code.Version()),
                              custom_code=text(code.CustomCode()), inputs=ins, outputs=outs,
                              options=numeric_options(operator, name),
                              nonconstant_io_bytes_no_alias=resident))
    active = sorted({j for op in operators for j in op["inputs"] + op["outputs"]}
                    | set(inputs) | set(outputs))
    nonconstant = [tensors[j] for j in active if not tensors[j]["constant_bytes"]]
    largest = max(nonconstant, key=lambda t: t["bytes"], default=None)
    peak_op = max(operators, key=lambda op: op["nonconstant_io_bytes_no_alias"], default=None)
    return dict(schema=1, scope="static_flatbuffer_inventory_not_inference_or_arena_or_itcm_size",
                model_sha256=hashlib.sha256(data).hexdigest(), model_bytes=len(data),
                description=text(model.Description()), dtcm_budget_bytes=dtcm_bytes,
                inputs=[tensors[i] for i in inputs], outputs=[tensors[i] for i in outputs],
                operator_counts=dict(sorted(Counter(op["name"] for op in operators).items())),
                constant_buffer_bytes=sum(model.Buffers(i).DataLength() for i in constants),
                largest_nonconstant_tensor=largest, max_nonconstant_io_operator=peak_op,
                whole_tensor_over_dtcm=[t["index"] for t in nonconstant if t["bytes"] > dtcm_bytes],
                itcm_requirement="NOT_MEASURED_requires_cross_compiled_ELF_and_linker_map",
                notes=["No-alias IO sums are not a TFLM arena estimate or a universal lower bound.",
                       "Scratch, alignment, other live tensors, stack and runtime state are excluded.",
                       "A full tensor larger than DTCM needs tiling and/or external placement.",
                       "No inference, accuracy, matrix offload, cycle or RTL PASS is asserted."],
                operators=operators, tensors=tensors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--dtcm-kib", type=int, default=512)
    parser.add_argument("--output", type=Path, help="New report path; refuses overwriting")
    args = parser.parse_args()
    report = inspect_bytes(args.model.read_bytes(), args.dtcm_kib * 1024)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
    summary = {k: report[k] for k in ("scope", "model_sha256", "model_bytes", "operator_counts",
               "constant_buffer_bytes", "itcm_requirement")}
    summary["inputs"] = [{k: t[k] for k in ("shape", "dtype", "bytes", "quantization")}
                         for t in report["inputs"]]
    summary["outputs"] = [{k: t[k] for k in ("shape", "dtype", "bytes", "quantization")}
                          for t in report["outputs"]]
    largest = report["largest_nonconstant_tensor"]
    summary["largest_tensor"] = None if largest is None else {
        k: largest[k] for k in ("index", "name", "shape", "dtype", "bytes")}
    summary["max_nonconstant_io_bytes_no_alias"] = (
        report["max_nonconstant_io_operator"]["nonconstant_io_bytes_no_alias"]
        if report["max_nonconstant_io_operator"] else 0)
    print("[MOBILENET_STATIC_INVENTORY] " + json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
