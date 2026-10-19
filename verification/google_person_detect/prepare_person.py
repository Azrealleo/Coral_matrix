"""Add a firmware-only package to the checked existing single-NPU source."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

from spec import ARENA_BYTES, DTCM_KIB, ITCM_LINK_KIB, MODEL_BYTES, MODEL_NAME
from spec import MODEL_SHA256, STACK_BYTES, TFLM_COMMIT, UPSTREAM, checked_asset, sha

HERE = Path(__file__).resolve().parent
CAPACITY = HERE.parent / "google_tcm_capacity"
sys.path.insert(0, str(CAPACITY))
capacity_spec = importlib.util.spec_from_file_location("_person_capacity_prepare", CAPACITY / "prepare.py")
capacity = importlib.util.module_from_spec(capacity_spec)
capacity_spec.loader.exec_module(capacity)
PACKAGE = "tests/cocotb/person_detect_baseline"
MANIFEST = "person_detect_firmware_manifest.json"


def build_text():
    return '''# Firmware resource measurement only; no RTL or model inference target.
load("//rules:coralnpu_v2.bzl", "coralnpu_v2_binary")
package(default_visibility = ["//visibility:public"])
coralnpu_v2_binary(
    name = "person_program",
    srcs = ["person_program.cc", "model_data.cc"],
    hdrs = ["person_program.h"],
    copts = ["-O2"],
    itcm_size_kbytes = 512,
    dtcm_size_kbytes = 512,
    stack_size_bytes = 16384,
    enable_vmem = False,
    deps = [
        "@tflite_micro//tensorflow/lite/micro:micro_framework",
        "@tflite_micro//tensorflow/lite/micro:micro_log",
        "@tflite_micro//tensorflow/lite/micro:op_resolvers",
    ],
)
'''


def model_source(data):
    if len(data) != MODEL_BYTES or sha(data) != MODEL_SHA256:
        raise ValueError("Not the pinned original model")
    rows = [",".join(str(v) for v in data[i:i + 32]) for i in range(0, len(data), 32)]
    return ('// Original TensorFlow Authors model, Apache-2.0; bytes unchanged.\n'
            '// SHA256 ' + MODEL_SHA256 + '\n#include "person_program.h"\n'
            'alignas(16) const unsigned char pd_model[kPersonModelBytes]\n'
            '    __attribute__((section(".data.pd_model"), used)) = {\n'
            + ",\n".join(rows) + '\n};\n').encode()


def expected_files(data):
    return {PACKAGE + "/BUILD": build_text().encode(),
            PACKAGE + "/model_data.cc": model_source(data),
            **{PACKAGE + "/" + n: (HERE / n).read_bytes()
               for n in ("person_program.cc", "person_program.h")}}


def evidence(root):
    baseline = json.loads((root / "tcm_capacity_manifest.json").read_text())
    for run in sorted(root.parent.glob("run_d512.*"), reverse=True):
        try:
            if json.loads((run / "manifest.json").read_text()) != baseline:
                continue
            capacity.checked_log((run / "test.log").read_text(), 512)
            capacity.checked_parameters((run / "parameters.h").read_text(), 512)
            return dict(directory=str(run), test_log_sha256=sha((run / "test.log").read_bytes()))
        except (OSError, ValueError, KeyError):
            continue
    raise ValueError("Requires the matching actual 512KiB geometry PASS, not a new RTL run")


def prepare(root, assets):
    capacity.verify(root)
    # Check the original source's TFLM revision, rather than selecting a new runtime.
    defs = capacity.git(root, "show", UPSTREAM + ":rules/repo_defs.bzl").decode()
    if "tflite-micro/archive/" + TFLM_COMMIT + ".zip" not in defs:
        raise ValueError("Unexpected upstream TFLM revision")
    data = checked_asset(assets, MODEL_NAME)
    files = expected_files(data)
    tools = {name: sha((HERE / name).read_bytes()) for name in
             ("prepare_person.py", "spec.py", "person_program.cc", "person_program.h",
              "firmware_report.py", "build_firmware.sh", "check_host.py")}
    identity = dict(schema=1, scope="firmware_resource_measurement_not_RTL_or_inference_PASS",
                    upstream=UPSTREAM, tflm_commit=TFLM_COMMIT, model_sha256=MODEL_SHA256,
                    model_unchanged=True, kernel_backend="pinned_TFLM_INT8_not_VME_offload",
                    itcm_link_ceiling_kib=ITCM_LINK_KIB, dtcm_kib=DTCM_KIB,
                    arena_reserved_bytes=ARENA_BYTES, stack_reserved_bytes=STACK_BYTES,
                    capacity_manifest_sha256=sha((root / "tcm_capacity_manifest.json").read_bytes()),
                    files={n: sha(b) for n, b in files.items()}, tools=tools)
    manifest_path = root / MANIFEST
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if any(old.get(k) != v for k, v in identity.items()):
            raise ValueError("Installed person baseline differs; preserve it, do not overwrite")
        for name, expected in identity["files"].items():
            if sha((root / name).read_bytes()) != expected:
                raise ValueError("Installed baseline file changed: " + name)
        print("[PERSON_FIRMWARE_PACKAGE_VERIFIED] original_model=true RTL=NOT_RUN")
        return old
    if (root / PACKAGE).exists() or any((root / n).exists() for n in files):
        raise ValueError("Existing unowned baseline directory; nothing overwritten")
    identity["geometry_evidence"] = evidence(root)
    (root / PACKAGE).mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        with (root / name).open("xb") as stream:
            stream.write(content)
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(identity, stream, indent=2)
        stream.write("\n")
    capacity.verify(root)
    print("[PERSON_FIRMWARE_PACKAGE_PREPARED] original_model=true RTL=NOT_RUN")
    return identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.upstream.resolve(strict=True), args.assets.resolve(strict=True))


if __name__ == "__main__":
    main()
