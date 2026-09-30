# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

load("@coralnpu_hw//third_party/python:requirements.bzl", "requirement")
load("@rules_python//python:defs.bzl", "py_library")
load("//rules:coco_tb.bzl", "cocotb_test_suite", "verilator_cocotb_model")
load("//rules:coralnpu_v2.bzl", "coralnpu_v2_binary")
load(
    "//tests/cocotb:build_defs.bzl",
    "VCS_BUILD_ARGS",
    "VCS_DEFINES",
    "VCS_TEST_ARGS",
    "VERILATOR_BUILD_ARGS",
)

VME_TEST_TESTCASES = [
    "vme_mset_csr_test",
    "vme_matmul_int8_test",
    "vme_matmul_fp32_test",
    "vme_decode_test",
    "vme_load_store_test",
    "vme_transpose_test",
    "vme_msettk_clamp_test",
    "vme_msettm_clamp_test",
    "vme_msettm_matmul_test",
    "vme_altfmt_test",
    "vme_vset_mtype_reset_test",
    "vme_mset_retire_test",
    "vme_mset_vtmmu_sequence_test",
    "vme_mstatus_ms_test",
]

cocotb_test_suite(
    name = "vme_test",
    simulators = [
        "verilator",
        "vcs",
    ],
    testcases = VME_TEST_TESTCASES,
    testcases_vname = "VME_TEST_TESTCASES",
    tests_kwargs = {
        "waves": False,
        "hdl_toplevel": "VmeCoreMiniAxi",
        "seed": "42",
        "test_module": ["vme_test_bench.py"],
        "deps": [
            "//coralnpu_test_utils:core_mini_axi_sim_interface",
            "//coralnpu_test_utils/sim_backends:verilator_test_fixture",
            requirement("tqdm"),
            "@bazel_tools//tools/python/runfiles",
        ],
        "data": [
            ":vme_altfmt_test_program",
            ":vme_matmul_test_program",
            ":vme_test_program",
            ":vme_decode_test",
            ":vme_load_store_test",
            ":vme_transpose_test",
            ":vme_vset_mtype_reset_test_program",
            ":vme_mset_vtmmu_sequence_test",
            ":vme_mstatus_ms_test",
        ],
        "size": "medium",
    },
    vcs_build_args = VCS_BUILD_ARGS,
    vcs_data = [
        ":vme_altfmt_test_program",
        ":vme_matmul_test_program",
        ":vme_test_program",
        ":vme_decode_test",
        ":vme_load_store_test",
        ":vme_transpose_test",
        ":vme_vset_mtype_reset_test_program",
        ":vme_mset_vtmmu_sequence_test",
        ":vme_mstatus_ms_test",
        "//tests/cocotb:coverage_exclude.cfg",
        "//hdl/verilog:dpi_files",
    ],
    vcs_defines = dict(
        VCS_DEFINES,
        ZVT_ON = "",
    ),
    vcs_test_args = VCS_TEST_ARGS,
    vcs_verilog_sources = [
        "//hdl/chisel/src/coralnpu:vme_core_mini_axi_cc_library_verilog",
    ],
    verilator_model = "//tests/cocotb:vme_core_mini_axi_model",
)

coralnpu_v2_binary(
    name = "vme_altfmt_test_program",
    srcs = ["vme_altfmt_test_program.cc"],
    hdrs = ["vme_test_utils.h"],
)

coralnpu_v2_binary(
    name = "vme_test_program",
    srcs = ["vme_test_program.cc"],
    hdrs = ["vme_test_utils.h"],
)

coralnpu_v2_binary(
    name = "vme_matmul_test_program",
    srcs = ["vme_matmul_test_program.cc"],
    hdrs = ["vme_test_utils.h"],
)

coralnpu_v2_binary(
    name = "vme_decode_test",
    srcs = ["vme_decode_test.cc"],
)

coralnpu_v2_binary(
    name = "vme_load_store_test",
    srcs = ["vme_load_store_test.cc"],
)

coralnpu_v2_binary(
    name = "vme_transpose_test",
    srcs = ["vme_transpose_test.cc"],
)

coralnpu_v2_binary(
    name = "vme_vset_mtype_reset_test_program",
    srcs = ["vme_vset_mtype_reset_test_program.cc"],
    hdrs = ["vme_test_utils.h"],
)

coralnpu_v2_binary(
    name = "vme_mset_vtmmu_sequence_test",
    srcs = ["vme_mset_vtmmu_sequence_test.cc"],
    hdrs = ["vme_test_utils.h"],
)

coralnpu_v2_binary(
    name = "vme_mstatus_ms_test",
    srcs = ["vme_mstatus_ms_test.cc"],
)

# Verification-only full-tile benchmark; reuses the existing compiled model.
cocotb_test_suite(
    name = "vme_matrix_perf",
    simulators = ["verilator"],
    testcases = [
        "vme_matrix_signed_diagnostic_test",
        "vme_matrix_common_perf_test",
    ],
    tests_kwargs = {
        "waves": False,
        "hdl_toplevel": "VmeCoreMiniAxi",
        "seed": "42",
        "test_module": ["vme_matrix_perf_bench.py"],
        "deps": [
            "//coralnpu_test_utils/sim_backends:verilator_test_fixture",
            "@bazel_tools//tools/python/runfiles",
        ],
        "data": [":vme_matrix_perf_program"],
        "size": "medium",
    },
    verilator_model = "//tests/cocotb:vme_core_mini_axi_model",
)

coralnpu_v2_binary(
    name = "vme_matrix_perf_program",
    srcs = ["vme_matrix_perf_program.cc"],
    hdrs = ["vme_test_utils.h"],
)

py_library(
    name = "vme_matrix_engine_probe",
    srcs = ["vme_matrix_engine_counter.py", "vme_matrix_engine_probe.py"],
    deps = [requirement("cocotb")],
)

py_library(
    name = "vme_matrix_perf_support",
    srcs = ["vme_matrix_perf_bench.py", "vme_matrix_burst_vectors.py"],
    deps = [
        "//coralnpu_test_utils/sim_backends:verilator_test_fixture",
        "@bazel_tools//tools/python/runfiles",
        requirement("cocotb"),
        requirement("numpy"),
    ],
)

# Separate visibility-only model: original regressions keep their model/cache.
verilator_cocotb_model(
    name = "vme_matrix_engine_model",
    cflags = VERILATOR_BUILD_ARGS + ["-DZVT_ON"],
    hdl_toplevel = "VmeCoreMiniAxi",
    trace = False,
    verilog_source = "//hdl/chisel/src/coralnpu:VmeCoreMiniAxi.sv",
    vlt_tpl = "zvt_perf.vlt.tpl",
    deps = ["//hdl/verilog:sram_backdoor"],
)

cocotb_test_suite(
    name = "vme_matrix_engine",
    simulators = ["verilator"],
    testcases = ["vme_matrix_engine_profile_test", "vme_matrix_engine_burst_test"],
    tests_kwargs = {
        "waves": False,
        "hdl_toplevel": "VmeCoreMiniAxi",
        "seed": "42",
        "test_module": ["vme_matrix_engine_bench.py"],
        "deps": [
            ":vme_matrix_engine_probe",
            ":vme_matrix_perf_support",
            "//coralnpu_test_utils/sim_backends:verilator_test_fixture",
            "@bazel_tools//tools/python/runfiles",
        ],
        "data": [":vme_matrix_perf_program", ":vme_matrix_burst_program"],
        "size": "medium",
    },
    verilator_model = ":vme_matrix_engine_model",
)

coralnpu_v2_binary(
    name = "vme_matrix_burst_program",
    srcs = ["vme_matrix_burst_program.cc"],
    hdrs = ["vme_test_utils.h"],
)

py_library(
    name = "vme_matrix_stress_vectors",
    srcs = ["vme_matrix_stress_vectors.py"],
    deps = [requirement("numpy")],
)

# Shared arithmetic regression, not a new performance boundary/model.
cocotb_test_suite(
    name = "vme_matrix_signed_stress",
    simulators = ["verilator"],
    testcases = ["vme_matrix_signed_stress_test"],
    tests_kwargs = {
        "waves": False,
        "hdl_toplevel": "VmeCoreMiniAxi",
        "seed": "42",
        "test_module": ["vme_matrix_signed_stress_bench.py"],
        "deps": [
            ":vme_matrix_perf_support",
            ":vme_matrix_stress_vectors",
            "//coralnpu_test_utils/sim_backends:verilator_test_fixture",
            "@bazel_tools//tools/python/runfiles",
        ],
        "data": [":vme_matrix_perf_program"],
        "size": "medium",
    },
    verilator_model = "//tests/cocotb:vme_core_mini_axi_model",
)

py_library(
    name = "vme_matrix_boundary_vectors",
    srcs = ["vme_matrix_boundary_vectors.py"],
    deps = [requirement("numpy")],
)

cocotb_test_suite(
    name = "vme_matrix_boundary",
    simulators = ["verilator"],
    testcases = ["vme_matrix_k_boundary_test"],
    tests_kwargs = {
        "waves": False,
        "hdl_toplevel": "VmeCoreMiniAxi",
        "seed": "42",
        "test_module": ["vme_matrix_boundary_bench.py"],
        "deps": [
            ":vme_matrix_perf_support",
            ":vme_matrix_boundary_vectors",
            "//coralnpu_test_utils/sim_backends:verilator_test_fixture",
            "@bazel_tools//tools/python/runfiles",
        ],
        "data": [":vme_matrix_perf_program"],
        "size": "medium",
    },
    verilator_model = "//tests/cocotb:vme_core_mini_axi_model",
)

py_library(
    name = "vme_matrix_model_tile_vectors",
    srcs = ["vme_matrix_model_tile_vectors.py"],
    deps = [requirement("numpy")],
)

# Same logical 16x16 tile tasks as the fork's padded-K VCS diagnostics. This
# target measures the existing full-core Tk=1 fixture, not a matched PE-only
# runtime and not an optimized model kernel.
cocotb_test_suite(
    name = "vme_matrix_model_tile",
    simulators = ["verilator"],
    testcases = ["vme_matrix_model_tile_test"],
    tests_kwargs = {
        "waves": False,
        "hdl_toplevel": "VmeCoreMiniAxi",
        "seed": "42",
        "test_module": ["vme_matrix_model_tile_bench.py"],
        "deps": [
            ":vme_matrix_perf_support",
            ":vme_matrix_model_tile_vectors",
            "//coralnpu_test_utils/sim_backends:verilator_test_fixture",
            "@bazel_tools//tools/python/runfiles",
        ],
        "data": [":vme_matrix_perf_program"],
        "size": "medium",
    },
    verilator_model = "//tests/cocotb:vme_core_mini_axi_model",
)

coralnpu_v2_binary(
    name = "vme_matrix_layer_program",
    srcs = ["vme_matrix_layer_program.cc"],
    hdrs = ["vme_test_utils.h"],
)

py_library(
    name = "vme_matrix_layer_vectors",
    srcs = ["vme_matrix_layer_vectors.py"],
    deps = [requirement("numpy")],
)

# Accumulate K>256 in a single program launch per tile; M/N tiles use separate
# launches. This is not a complete convolution or matched-system benchmark.
cocotb_test_suite(
    name = "vme_matrix_layer",
    simulators = ["verilator"],
    testcases = ["vme_matrix_layer_test"],
    tests_kwargs = {
        "waves": False,
        "hdl_toplevel": "VmeCoreMiniAxi",
        "seed": "42",
        "test_module": ["vme_matrix_layer_bench.py"],
        "deps": [
            ":vme_matrix_perf_support",
            ":vme_matrix_layer_vectors",
            "//coralnpu_test_utils/sim_backends:verilator_test_fixture",
            "@bazel_tools//tools/python/runfiles",
        ],
        "data": [":vme_matrix_layer_program"],
        "size": "medium",
    },
    verilator_model = "//tests/cocotb:vme_core_mini_axi_model",
)
