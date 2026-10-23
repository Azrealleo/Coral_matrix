"""Install a new direct-call benchmark; never rewrite an old experiment."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import lv_spec as spec

HERE=Path(__file__).resolve().parent
MANIFEST='official_rvv_v1_manifest.json'
ROOT='tests/cocotb/rvv/ml_ops/gemma_kernels/'
OFFICIAL=('rvv_rms_norm.cc','rvv_residual_add.cc','rvv_tanh_gelu_mul.cc','rvv_common_vec.h','rvv_matmul.cc')


def fixtures():
    out=['#include "kernels.h"\n'];table=[];algorithms=[]
    def array(name,values):
        out.append('alignas(16) const float '+name+'[] __attribute__((section(".data.official_fixtures"),used))={'+
            ','.join(spec.f32(v).hex()+'f' for v in (values or [0.]))+'};\n')
        return name
    kinds=('MATMUL','RMS','SOFTMAX','ROPE','SWIGLU','GEGLU','RESIDUAL','KVAPPEND','ATTENTION')
    for i in range(7):
        d=spec.fixture(i);ptrs=[array('f'+str(i)+n,d[n]) for n in ('x','w','v','y')]
        algorithms.append(array('a'+str(i),d['algorithm']))
        table.append('{"'+d['name']+'",'+d['kind']+','+','.join(map(str,d['shape']))+','+
            ','.join(str(len(d[n])) for n in ('x','w','v','y'))+','+','.join(ptrs)+'}')
    out.append('extern const Case kCases[]={'+',\n'.join(table)+'};\nextern const unsigned kCaseCount=7;\n')
    out.append('extern const float* const kAlgorithm[]={'+','.join(algorithms)+'};\n')
    return ''.join(out).encode()


def build_text():
    headers=['kernels.h','rvv_common_vec.h']
    srcs=['linear_bench.cc','kernels.cc','fixtures.cc',*[n for n in OFFICIAL if n.endswith('.cc')]]
    return '''load("@rules_cc//cc:defs.bzl", "cc_test")
load("@rules_python//python:defs.bzl", "py_library")
load("//rules:coralnpu_v2.bzl", "coralnpu_v2_binary")
load("//rules:coco_tb.bzl", "cocotb_test_suite")
load("//third_party/python:requirements.bzl", "requirement")
package(default_visibility=["//visibility:public"])
coralnpu_v2_binary(name="probe_program",srcs='''+repr(srcs)+''',hdrs='''+repr(headers)+''',
    copts=["-std=c++17","-O2","-fno-tree-vectorize","-fno-tree-slp-vectorize","-fno-lto","-ffp-contract=off"],
    itcm_size_kbytes=256,dtcm_size_kbytes=512,stack_size_bytes=16384,enable_vmem=False,)
cc_test(name="host_reference_test",srcs=["linear_bench.cc","kernels.cc","kernels.h","fixtures.cc","host_mirrors.cc"],
    copts=["-std=c++17","-O2","-DTX_HOST=1","-ffp-contract=off"],)
py_library(name="support",srcs=["lv_spec.py","lv_audit.py","lv_packet.py","lv_bench.py","baseline_spec.py","tx_reference.py"],
    deps=[requirement("pyelftools")])
cocotb_test_suite(name="opt",simulators=["verilator"],testcases='''+repr([spec.testcase(i) for i in (6,*range(6))])+''',
    verilator_model="//tests/cocotb/llm_linear_v1:model",tests_kwargs={
    "hdl_toplevel":"'''+spec.TOP+'''","test_module":["vm_bench.py"],"waves":False,"seed":"137","size":"large",
    "extra_env":["COCOTB_USE_FRONTDOOR=1"],
    "data":[":probe_program.elf","//tests/cocotb/llm_linear_v1:'''+spec.TOP+'''.sv",
       "//tests/cocotb/llm_linear_v1:V'''+spec.TOP+'''_parameters.h"],
    "deps":[":support","@bazel_tools//tools/python/runfiles","//coralnpu_test_utils:core_mini_axi_sim_interface",
       "//coralnpu_test_utils/sim_backends:verilator_test_fixture"],},)
'''


def expected(root):
    names=('linear_bench.cc','kernels.cc','kernels.h','host_mirrors.cc','lv_spec.py','lv_audit.py','lv_packet.py',
           'lv_bench.py','vm_bench.py','tx_reference.py')
    files={n:(HERE/n).read_bytes() for n in names}
    files['baseline_spec.py']=spec.reference_path().read_bytes()
    files['vme_tile.h']=(HERE.parent/'google_person_vme/vme_tile.h').read_bytes() # export-helper integrity only
    if spec.sha(HERE.parent/'google_person_vme/vme_tile.h')!=spec.TILE_SHA:raise ValueError('Frozen checker helper changed')
    for name in OFFICIAL:
        files[name]=subprocess.check_output(['git','-C',str(root),'show',spec.UPSTREAM+':'+ROOT+name])
    files['fixtures.cc']=fixtures();files['BUILD']=build_text().encode()
    return files


def prepare(root):
    p=HERE.parent/'google_llm_ops/prepare.py';sys.path.insert(0,str(p.parent))
    loader=importlib.util.spec_from_file_location('_official_model_prepare',p)
    base=importlib.util.module_from_spec(loader);loader.loader.exec_module(base);base.prepare(root)
    files=expected(root);digest=lambda b:__import__('hashlib').sha256(b).hexdigest()
    marker=root/MANIFEST
    record=dict(schema=1,upstream=spec.UPSTREAM,scope=spec.SCOPE,generator_sha256=spec.sha(__file__),
        hardware_tile_sha256=spec.TILE_SHA,vector_reference_sha256=spec.REFERENCE_SHA,
        official_sources={ROOT+n:digest(files[n]) for n in OFFICIAL},
        files={spec.PACKAGE+'/'+n:digest(b) for n,b in files.items()})
    if marker.exists():
        if json.loads(marker.read_text())!=record or any((root/spec.PACKAGE/n).read_bytes()!=b for n,b in files.items()):
            raise ValueError('Existing official-RVV package differs; preserve it and use a new version')
    else:
        directory=root/spec.PACKAGE
        if directory.exists():raise ValueError('Unowned package; nothing overwritten')
        directory.mkdir(parents=True)
        for name,data in files.items():
            with (directory/name).open('xb') as f:f.write(data)
        with marker.open('x',encoding='utf-8') as f:json.dump(record,f,indent=2)
    print('[OFFICIAL_RVV_PREPARED] official_sources_byte_identical=true old_experiments_unchanged=true RTL=NOT_RUN')
    return record


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--upstream',type=Path,required=True)
    prepare(p.parse_args().upstream.resolve(strict=True))
