"""Add an independent official RVV linear microbenchmark; never rewrite old tests."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from spec import UPSTREAM, PACKAGE, TOP, CASES, SCOPE, vectors

HERE = Path(__file__).resolve().parent
OFFICIAL = "tests/cocotb/rvv/ml_ops/gemma_kernels/rvv_int8_matmul.cc"
MANIFEST = "llm_linear_v1_manifest.json"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build_text():
    return '''load("@rules_cc//cc:defs.bzl", "cc_test")
load("@rules_python//python:defs.bzl", "py_library")
load("//rules:coralnpu_v2.bzl", "coralnpu_v2_binary")
load("//rules:chisel.bzl", "chisel_cc_library")
load("//rules:coco_tb.bzl", "cocotb_test_suite", "verilator_cocotb_model")
load("//hdl/chisel/src/coralnpu:flags.bzl", "VME_CORE_MINI_AXI_COMMON_GEN_FLAGS", "VME_CORE_MINI_AXI_VOPTS")
load("//tests/cocotb:build_defs.bzl", "VERILATOR_BUILD_ARGS")
load("//third_party/python:requirements.bzl", "requirement")
package(default_visibility=["//visibility:public"])
coralnpu_v2_binary(
    name="probe_program",srcs=["linear_bench.cc","rvv_int8_matmul.cc"],
    copts=["-O2","-fno-tree-vectorize","-fno-tree-slp-vectorize","-fno-lto"],
    itcm_size_kbytes=256,dtcm_size_kbytes=512,stack_size_bytes=16384,enable_vmem=False,
)
cc_test(name="host_reference_test",srcs=["linear_bench.cc"],
    copts=["-O2","-DLLM_HOST=1"],)
chisel_cc_library(
    name="rtl",chisel_lib="//hdl/chisel/src/coralnpu:coralnpu",
    emit_class="coralnpu.EmitCore",module_name="'''+TOP+'''",
    verilog_file_path="'''+TOP+'''.sv",
    extra_outs=["V'''+TOP+'''_parameters.h","'''+TOP+'''.zip"],
    gen_flags=["--moduleName=VmeCoreMini","--itcmSizeKBytes=256","--dtcmSizeKBytes=512"]+VME_CORE_MINI_AXI_COMMON_GEN_FLAGS,
    vopts=VME_CORE_MINI_AXI_VOPTS,
)
verilator_cocotb_model(name="model",hdl_toplevel="'''+TOP+'''",
    cflags=VERILATOR_BUILD_ARGS+["-DZVT_ON","-DZVTBF16FMM_ON"],
    verilog_source=":'''+TOP+'''.sv",trace=False,deps=["//hdl/verilog:sram_backdoor"],)
py_library(name="support",srcs=["spec.py","audit.py"],deps=[requirement("pyelftools")])
cocotb_test_suite(name="linear",simulators=["verilator"],
    testcases=['''+','.join('"llm_'+c[0]+'_test"' for c in CASES)+'''],
    verilator_model=":model",tests_kwargs={
        "hdl_toplevel":"'''+TOP+'''","test_module":["linear_rtl_bench.py"],
        "waves":False,"seed":"137","size":"large",
        "extra_env":["COCOTB_USE_FRONTDOOR=1"],
        "data":[":probe_program.elf",":'''+TOP+'''.sv",":V'''+TOP+'''_parameters.h"],
        "deps":[":support","@bazel_tools//tools/python/runfiles",
            "//coralnpu_test_utils:core_mini_axi_sim_interface",
            "//coralnpu_test_utils/sim_backends:verilator_test_fixture"],
    },)
'''


def expected(root):
    raw = subprocess.check_output(["git", "-C", str(root), "show", UPSTREAM+":"+OFFICIAL])
    files = {name: (HERE/name).read_bytes() for name in
             ("spec.py", "audit.py", "linear_bench.cc", "linear_rtl_bench.py")}
    files.update({"rvv_int8_matmul.cc": raw, "BUILD": build_text().encode()})
    return files


def install(root, files):
    files = {PACKAGE+"/"+n: data for n, data in files.items()}
    manifest = dict(schema=1, upstream=UPSTREAM, scope=SCOPE, official_source=OFFICIAL,
        official_source_sha256=digest(files[PACKAGE+"/rvv_int8_matmul.cc"]),
        generator_sha256=digest(Path(__file__).read_bytes()), itcm_kib=256, dtcm_kib=512,
        cases=[dict(case_id=i, case=c[0], M=c[1], K=c[2], N=c[3],
                    vector_sha256=vectors(i)["vector_sha256"], signature=vectors(i)["signature"])
               for i, c in enumerate(CASES)], files={n: digest(b) for n,b in files.items()})
    marker = root/MANIFEST
    if marker.exists():
        if json.loads(marker.read_text()) != manifest or any((root/n).read_bytes() != b for n,b in files.items()):
            raise ValueError("Existing LLM test changed; nothing overwritten; use a new version")
    else:
        if (root/PACKAGE).exists():
            raise ValueError("Unowned LLM directory; nothing overwritten")
        (root/PACKAGE).mkdir(parents=True)
        for n,b in files.items():
            with (root/n).open("xb") as stream:
                stream.write(b)
        with marker.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
    return manifest


def prepare(root):
    # Verify the previously qualified address-map/CSR/floating-point patches.
    path = HERE.parent/"google_tcm_capacity/prepare.py"
    sys.path.insert(0, str(path.parent))
    module_spec = importlib.util.spec_from_file_location("_llm_capacity_base", path)
    base = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(base)
    base.verify(root)
    result = install(root, expected(root))
    print("[LLM_LINEAR_PREPARED] official_RVV_source_unchanged=true model=NOT_LOADED RTL=NOT_RUN")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--upstream", type=Path, required=True)
    a = p.parse_args(); prepare(a.upstream.resolve(strict=True))
