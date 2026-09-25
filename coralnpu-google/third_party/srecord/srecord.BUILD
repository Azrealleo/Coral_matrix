# Copyright 2025 Google LLC

load("@coralnpu_host_cpus//:defs.bzl", "MAKE_JOBS")
load("@rules_foreign_cc//foreign_cc:defs.bzl", "cmake")

filegroup(
    name = "all_srcs",
    srcs = glob(["**"]),
)

cmake(
    name = "srecord",
    build_args = [
        "-j{}".format(MAKE_JOBS),
    ],
    cache_entries = {
        "CMAKE_CXX_STANDARD": "17",
        "CMAKE_CXX_STANDARD_LIBRARIES": "-lstdc++",
    },
    generate_args = [
        "-G Ninja",
    ],
    install = True,
    lib_source = ":all_srcs",
    out_binaries = ["srec_cat"],
    targets = ["srec_cat"],
    visibility = ["//visibility:public"],
)
