"""Install an independent VME candidate. Never modify the default firmware/RTL."""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "google_person_detect"
sys.path.insert(0, str(BASE))
import prepare_person as baseline
from spec import MODEL_NAME, MODEL_SHA256, TFLM_COMMIT, UPSTREAM, checked_asset, sha

PACKAGE = "tests/cocotb/person_detect_vme_v1"
MANIFEST = "person_detect_vme_v1_manifest.json"
TEAM = "fa4b83e43bb0b1d58b18eb5f4c31d98ee4054123"


def program_source():
    text = (BASE / "person_program.cc").read_text(encoding="utf-8")
    replacements = {
        '// Entire unchanged pretrained model, pinned TFLM INT8 kernels, no VME offload.':
            '// VME pointwise candidate; other operators remain pinned TFLM INT8.',
        '#include "person_program.h"': '#include "person_program.h"\n#include "conv_vme.h"',
        'resolver.AddConv2D(tflite::Register_CONV_2D_INT8())':
            'resolver.AddConv2D(person_vme::RegisterPointwise())',
        '  pd_status = 3;': '''  if (pd_vme_conv_calls != 14 || pd_vme_fallback_calls ||
      !pd_vme_commands || pd_vme_mismatches) return fail(106);
#if PD_VME_VALIDATE
  if (pd_vme_validated_layers != 14) return fail(107);
#endif
  pd_status = 3;''',
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise ValueError("Baseline adapter anchor changed: " + old)
        text = text.replace(old, new)
    return text.encode()


def build_text():
    deps = '''[
        "@tflite_micro//tensorflow/lite/micro:micro_framework",
        "@tflite_micro//tensorflow/lite/micro:micro_log",
        "@tflite_micro//tensorflow/lite/micro:op_resolvers",
        "@tflite_micro//tensorflow/lite/kernels/internal:common",
    ]'''
    text = '''# Experimental candidates: host emulation != RTL PASS.
load("@rules_cc//cc:defs.bzl", "cc_test")
load("//rules:coralnpu_v2.bzl", "coralnpu_v2_binary")
package(default_visibility = ["//visibility:public"])
'''
    for mode, validate in (("validate", 1), ("fast", 0)):
        text += f'''
coralnpu_v2_binary(
    name = "person_vme_{mode}",
    srcs = ["person_program.cc", "model_data.cc", "conv_vme.cc"],
    hdrs = ["person_program.h", "conv_vme.h", "pointwise_core.h", "vme_tile.h"],
    copts = ["-O2", "-fno-tree-vectorize", "-fno-tree-slp-vectorize", "-fno-lto", "-DPD_VME_VALIDATE={validate}"],
    itcm_size_kbytes = 256,
    dtcm_size_kbytes = 512,
    stack_size_bytes = 16384,
    enable_vmem = False,
    deps = {deps},
)
'''
    text += f'''
cc_test(
    name = "host_model_test",
    srcs = ["host_model_test.cc", "model_data.cc", "conv_vme.cc", "fixtures.cc",
            "person_program.h", "conv_vme.h", "pointwise_core.h", "fixtures.h"],
    copts = ["-O2", "-DPD_VME_EMULATE=1", "-DPD_VME_VALIDATE=1"],
    deps = {deps},
    timeout = "long",
)
cc_test(name = "host_core_test", srcs = ["core_test.cc", "pointwise_core.h"])
'''
    return text.encode()


def fixture_files(assets):
    # Use the existing strict decoder; preserve official tensor-encoded bytes.
    from export_person import fixture_bytes
    header = '#pragma once\nextern const unsigned char pd_fixture_person[9216];\nextern const unsigned char pd_fixture_no_person[9216];\n'
    source = '#include "fixtures.h"\n'
    for name in ("person", "no_person"):
        raw = fixture_bytes(checked_asset(assets, name + ".bmp"))
        source += 'const unsigned char pd_fixture_' + name + '[9216] = {\n'
        source += ',\n'.join(','.join(map(str, raw[i:i+32])) for i in range(0,len(raw),32)) + '\n};\n'
    return {"fixtures.h": header.encode(), "fixtures.cc": source.encode()}


def expected_files(assets):
    sources = ("conv_vme.cc", "conv_vme.h", "pointwise_core.h", "vme_tile.h",
               "core_test.cc", "host_model_test.cc")
    result = {n: (HERE / n).read_bytes() for n in sources}
    result.update(fixture_files(assets))
    result.update({"BUILD": build_text(), "person_program.cc": program_source(),
                   "person_program.h": (BASE / "person_program.h").read_bytes(),
                   "model_data.cc": baseline.model_source(checked_asset(assets, MODEL_NAME))})
    return {PACKAGE + '/' + n: data for n, data in result.items()}


def prepare(root, assets):
    # Read-only baseline verifier for its fixed source/geometry evidence.
    baseline.capacity.verify(root)
    installed = json.loads((root / baseline.MANIFEST).read_text())
    if installed.get("upstream") != UPSTREAM or installed.get("model_sha256") != MODEL_SHA256:
        raise ValueError("Missing/mismatching installed baseline identity")
    for name, expected in installed["files"].items():
        if sha((root / name).read_bytes()) != expected:
            raise ValueError("Baseline file changed: " + name)
    files = expected_files(assets)
    identity = dict(schema=1, status="CANDIDATE_NOT_VALIDATED", upstream=UPSTREAM,
                    tflm_commit=TFLM_COMMIT, team_reference=TEAM, model_sha256=MODEL_SHA256,
                    itcm_kib=256, dtcm_kib=512,
                    backend="VME_pointwise_INT8_reference_depthwise_pool_softmax",
                    baseline_manifest_sha256=sha((root / baseline.MANIFEST).read_bytes()),
                    files={n: sha(b) for n,b in files.items()},
                    generator_sha256=sha(Path(__file__).read_bytes()))
    marker = root / MANIFEST
    if marker.exists():
        if json.loads(marker.read_text()) != identity:
            raise ValueError("Existing candidate differs; preserve it, use a new version")
        for n, b in files.items():
            if (root / n).read_bytes() != b:
                raise ValueError("Candidate file changed: " + n)
    else:
        if (root / PACKAGE).exists():
            raise ValueError("Unowned candidate directory; nothing overwritten")
        (root / PACKAGE).mkdir(parents=True, exist_ok=False)
        for n, b in files.items():
            with (root / n).open("xb") as stream:
                stream.write(b)
        with marker.open("x", encoding="utf-8") as stream:
            json.dump(identity, stream, indent=2)
            stream.write('\n')
    print("[PERSON_VME_CANDIDATE_PREPARED] baseline_unchanged=true NPU_RTL=NOT_RUN")
    return identity


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.upstream.resolve(strict=True), args.assets.resolve(strict=True))
