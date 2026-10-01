# Copyright 2025 Google LLC
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
load("//rules:utils.bzl", "generate_cc_arrays")
load(
    "//tests/cocotb:build_defs.bzl",
    "VCS_BUILD_ARGS",
    "VCS_DEFINES",
    "VCS_TEST_ARGS",
    "VERILATOR_BUILD_ARGS",
)


# ==============================================================================
# Conv Test 
# ==============================================================================

coralnpu_v2_binary(
    name = "mxu_conv_test",
    srcs = ["mxu_conv_test.cc"],
    itcm_size_kbytes = 1024,  # Highmem
    dtcm_size_kbytes = 1024,  # Highmem
    deps = [
        "//sw/opt/litert-micro:mxu", 
        "//sw/opt/litert-micro:conv", 
        "@tflite_micro//tensorflow/lite/kernels/internal:reference_base"
    ],
)

cocotb_test_suite(
    name = "cocotb_mxu_conv",
    testcases = ["cocotb_mxu_conv"],  # <--- 【关键修改】添加这行，通常对应你的 python 脚本名或测试集名
    simulators = [
        "verilator",
        "vcs",
    ],
    tests_kwargs = {
        "waves": False,
        "hdl_toplevel": "RvvCoreMiniHighmemAxi",
        "size": "enormous",
        "default_testcase_size": "medium",
        "test_module": ["cocotb_mxu_conv.py"], # 你的 Python 测试脚本
        "deps": [
            "//coralnpu_test_utils:core_mini_axi_sim_interface",
            "//coralnpu_test_utils:sim_test_fixture",
            "@rules_python//python/runfiles",
        ],
        "data": ["mxu_conv_test.elf"],
    },
    vcs_build_args = VCS_BUILD_ARGS,
    vcs_data = glob(["**/*.elf"], allow_empty = True) + [
        "//tests/cocotb:coverage_exclude.cfg",
    ],
    vcs_defines = VCS_DEFINES,
    vcs_test_args = VCS_TEST_ARGS,
    vcs_verilog_sources = ["//hdl/chisel/src/coralnpu:rvv_core_mini_highmem_axi_cc_library_verilog"],
    verilator_model = "//tests/cocotb:rvv_core_mini_highmem_axi_model",
)

# Common seven signed-INT8 logical tiles, now through the fork's real RVV core
# and MXU wrapper. The program is distinct from the existing TFLM conv test.
coralnpu_v2_binary(
    name = "mxu_fullcore_tile_program",
    srcs = ["mxu_fullcore_tile_program.cc"],
)

py_library(
    name = "mxu_fullcore_tile_vectors",
    srcs = ["mxu_fullcore_tile_vectors.py"],
    deps = [requirement("numpy")],
)

cocotb_test_suite(
    name = "mxu_fullcore_tile",
    simulators = ["verilator"],
    testcases = ["mxu_fullcore_tile_test"],
    tests_kwargs = {
        "waves": False,
        "hdl_toplevel": "RvvCoreMiniAxi",
        "seed": "42",
        "test_module": ["mxu_fullcore_tile_bench.py"],
        "deps": [
            ":mxu_fullcore_tile_vectors",
            "//coralnpu_test_utils:sim_test_fixture",
            "@rules_python//python/runfiles",
        ],
        "data": [":mxu_fullcore_tile_program"],
        "size": "medium",
    },
    verilator_model = "//tests/cocotb:rvv_core_mini_axi_model",
)

coralnpu_v2_binary(
    name = "mxu_fullcore_shared_weight_batch_program",
    srcs = ["mxu_fullcore_shared_weight_batch_program.cc"],
)

cocotb_test_suite(
    name = "mxu_fullcore_shared_weight_batch",
    simulators = ["verilator"],
    testcases = ["mxu_fullcore_shared_weight_batch_test"],
    tests_kwargs = {
        "waves": False,
        "hdl_toplevel": "RvvCoreMiniAxi",
        "seed": "42",
        "test_module": ["mxu_fullcore_shared_weight_batch_bench.py"],
        "deps": [
            ":mxu_fullcore_tile_vectors",
            "//coralnpu_test_utils:sim_test_fixture",
            "@rules_python//python/runfiles",
        ],
        "data": [":mxu_fullcore_shared_weight_batch_program"],
        "size": "medium",
    },
    verilator_model = "//tests/cocotb:rvv_core_mini_axi_model",
)

# Same logical performance sweep as the official Tk=4 test, using the
# fork's existing full-core MXU binary and physical 16x16 tile interface.
cocotb_test_suite(
    name = "mxu_fullcore_speed_sweep",
    simulators = ["verilator"],
    testcases = ["mxu_fullcore_speed_sweep_test"],
    tests_kwargs = {
        "waves": False,
        "hdl_toplevel": "RvvCoreMiniAxi",
        "seed": "42",
        "test_module": ["mxu_fullcore_speed_sweep_bench.py"],
        "deps": [
            ":mxu_fullcore_tile_vectors",
            "//coralnpu_test_utils:sim_test_fixture",
            "@rules_python//python/runfiles",
        ],
        "data": [":mxu_fullcore_tile_program"],
        "size": "medium",
    },
    verilator_model = "//tests/cocotb:rvv_core_mini_axi_model",
)
