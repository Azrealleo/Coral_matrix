"""Independent FP32 suite; preserve the already-qualified INT8 package bytes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
from tx_spec import CASES, KINDS, PACKAGE, LINEAR_PACKAGE, TOP, UPSTREAM, SCOPE, fixture

HERE=Path(__file__).resolve().parent
MANIFEST="llm_transformer_v1_manifest.json"
OFFICIAL="tests/cocotb/rvv/ml_ops/gemma_kernels/rvv_matmul.cc"


def digest(data):return hashlib.sha256(data).hexdigest()


def fixtures():
    source=['#include "kernels.h"\n'];table=[]
    def array(name,values):
        # Exact binary32 hex literals: no uint32/float strict-aliasing trick.
        source.append('alignas(16) const float '+name+'[] __attribute__((section(".data.tx_fixtures"),used))={'+
                      ','.join(value.hex()+'f' for value in (values or [0.0]))+'};\n')
        return name
    for i,(name,kind,shape) in enumerate(CASES):
        item=fixture(i);pointers=[array("data_"+str(i)+"_"+n,item[n]) for n in ("x","w","v","y")]
        table.append('{"'+name+'",'+kind+','+','.join(map(str,shape))+','+
                     ','.join(str(len(item[n])) for n in ("x","w","v","y"))+','+','.join(pointers)+'}')
    source.append('extern const Case kCases[]={'+',\n'.join(table)+'};\n')
    source.append('extern const unsigned kCaseCount='+str(len(CASES))+';\n')
    return ''.join(source).encode()


def build_text():
    return '''load("@rules_cc//cc:defs.bzl", "cc_test")
load("@rules_python//python:defs.bzl", "py_library")
load("//rules:coralnpu_v2.bzl", "coralnpu_v2_binary")
load("//rules:coco_tb.bzl", "cocotb_test_suite")
load("//third_party/python:requirements.bzl", "requirement")
package(default_visibility=["//visibility:public"])
coralnpu_v2_binary(name="probe_program",srcs=["bench.cc","kernels.cc","fixtures.cc","rvv_matmul.cc"],
    hdrs=["kernels.h"],copts=["-std=c++17","-O2","-fno-tree-vectorize","-fno-tree-slp-vectorize","-fno-lto","-ffp-contract=off"],
    itcm_size_kbytes=256,dtcm_size_kbytes=512,stack_size_bytes=16384,enable_vmem=False,)
cc_test(name="host_reference_test",srcs=["bench.cc","kernels.cc","fixtures.cc","kernels.h"],
    copts=["-std=c++17","-O2","-DTX_HOST=1","-ffp-contract=off"],)
py_library(name="support",srcs=["tx_spec.py","tx_audit.py"],deps=[requirement("pyelftools")])
cocotb_test_suite(name="ops",simulators=["verilator"],
    testcases=['''+','.join('"tx_'+c[0]+'_test"' for c in CASES)+'''],
    verilator_model="//'''+LINEAR_PACKAGE+''':model",tests_kwargs={
        "hdl_toplevel":"'''+TOP+'''","test_module":["tx_bench.py"],"waves":False,"seed":"137","size":"large",
        "extra_env":["COCOTB_USE_FRONTDOOR=1"],
        "data":[":probe_program.elf","//'''+LINEAR_PACKAGE+''':'''+TOP+'''.sv",
            "//'''+LINEAR_PACKAGE+''':V'''+TOP+'''_parameters.h"],
        "deps":[":support","@bazel_tools//tools/python/runfiles",
            "//coralnpu_test_utils:core_mini_axi_sim_interface",
            "//coralnpu_test_utils/sim_backends:verilator_test_fixture"],},)
'''


def install(root,files):
    files={PACKAGE+"/"+n:v for n,v in files.items()}
    manifest=dict(schema=1,kind="llm_operator_preparation_not_complete_model",upstream=UPSTREAM,scope=SCOPE,
        generator_sha256=digest(Path(__file__).read_bytes()),itcm_kib=256,dtcm_kib=512,
        original_INT8_package_unchanged=True,official_source=OFFICIAL,
        official_source_sha256=digest(files[PACKAGE+"/rvv_matmul.cc"]),
        custom_operators="project_FP32_RVV_baselines_scalar_libm_exp_tanh_not_official_Gemma_kernels",
        cases=[{k:v for k,v in fixture(i).items() if k not in ("x","w","v","y")} for i in range(len(CASES))],
        files={n:digest(v) for n,v in files.items()})
    marker=root/MANIFEST
    if marker.exists():
        if json.loads(marker.read_text())!=manifest or any((root/n).read_bytes()!=b for n,b in files.items()):
            raise ValueError("Existing FP32 suite differs; nothing overwritten; use a new version")
    else:
        if (root/PACKAGE).exists():raise ValueError("Unowned FP32 package; nothing overwritten")
        (root/PACKAGE).mkdir(parents=True)
        for n,b in files.items():
            with (root/n).open("xb") as stream:stream.write(b)
        with marker.open("x",encoding="utf-8") as stream:json.dump(manifest,stream,indent=2)
    return manifest


def expected(root):
    files={n:(HERE/n).read_bytes() for n in ("kernels.h","kernels.cc","bench.cc","tx_spec.py","tx_audit.py","tx_bench.py")}
    files.update({"fixtures.cc":fixtures(),"BUILD":build_text(),
        "rvv_matmul.cc":subprocess.check_output(["git","-C",str(root),"show",UPSTREAM+":"+OFFICIAL])})
    files["BUILD"]=files["BUILD"].encode()
    return files


def prepare(root):
    # Recheck, do not regenerate/modify, the original qualified INT8 package.
    path=HERE.parent/"prepare.py";sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location("_tx_original_linear_prepare",path)
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
    base.prepare(root)
    result=install(root,expected(root))
    print("[LLM_TX_PREPARED] INT8_unchanged=true model=NOT_LOADED RTL=NOT_RUN")
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--upstream",type=Path,required=True)
    a=p.parse_args();prepare(a.upstream.resolve(strict=True))
