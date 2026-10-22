"""Independent RVV/VME linear package; old measured candidates unchanged."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import lv_spec as spec

HERE=Path(__file__).resolve().parent
MANIFEST="llm_vme_linear_v1_manifest.json"
OFFICIAL="tests/cocotb/rvv/ml_ops/gemma_kernels/rvv_int8_matmul.cc"


def build_text():
    return '''load("@rules_cc//cc:defs.bzl", "cc_test")
load("//rules:coralnpu_v2.bzl", "coralnpu_v2_binary")
package(default_visibility=["//visibility:public"])
coralnpu_v2_binary(name="probe_program",srcs=["linear_bench.cc","rvv_int8_matmul.cc"],
    hdrs=["linear_core.h","vme_tile.h"],
    copts=["-std=c++17","-O2","-fno-tree-vectorize","-fno-tree-slp-vectorize","-fno-lto"],
    itcm_size_kbytes=256,dtcm_size_kbytes=512,stack_size_bytes=16384,enable_vmem=False,)
cc_test(name="host_reference_test",srcs=["linear_bench.cc","linear_core.h"],
    copts=["-std=c++17","-O2","-DLV_HOST=1"],)
cc_test(name="host_packing_test",srcs=["core_test.cc","linear_core.h"],
    copts=["-std=c++17","-O2"],)
'''


def expected(root):
    files={n:(HERE/n).read_bytes() for n in ("linear_core.h","linear_bench.cc","core_test.cc","lv_spec.py","lv_audit.py")}
    tile=HERE.parent/"google_person_vme/vme_tile.h"
    if spec.sha(tile)!=spec.TILE_SHA:raise ValueError("Qualified VME HardwareTile changed")
    files.update({"BUILD":build_text().encode(),"vme_tile.h":tile.read_bytes(),"baseline_spec.py":spec.reference_path().read_bytes(),
        "rvv_int8_matmul.cc":subprocess.check_output(["git","-C",str(root),"show",spec.UPSTREAM+":"+OFFICIAL])})
    return files


def install(root,files):
    import hashlib
    digest=lambda raw:hashlib.sha256(raw).hexdigest()
    files={spec.PACKAGE+"/"+n:v for n,v in files.items()}
    manifest=dict(schema=1,kind="llm_vme_linear_preparation_v1",upstream=spec.UPSTREAM,scope=spec.SCOPE,
        generator_sha256=spec.sha(__file__),itcm_kib=256,dtcm_kib=512,official_source=OFFICIAL,
        official_source_sha256=digest(files[spec.PACKAGE+"/rvv_int8_matmul.cc"]),hardware_tile_sha256=spec.TILE_SHA,
        vector_reference_sha256=spec.REFERENCE_SHA,cases=[dict(id=i,name=c[0],M=c[1],K=c[2],N=c[3],
            vector_sha256=spec.vectors(i)["vector_sha256"],signature=spec.expected_signature(i)) for i,c in enumerate(spec.CASES)],
        files={n:digest(v) for n,v in files.items()})
    marker=root/MANIFEST
    if marker.exists():
        if json.loads(marker.read_text())!=manifest or any((root/n).read_bytes()!=v for n,v in files.items()):
            raise ValueError("Existing VME comparison differs; nothing overwritten; use new version")
    else:
        if (root/spec.PACKAGE).exists():raise ValueError("Unowned comparison package; nothing overwritten")
        (root/spec.PACKAGE).mkdir(parents=True)
        for n,v in files.items():
            with (root/n).open("xb") as stream:stream.write(v)
        with marker.open("x",encoding="utf-8") as stream:json.dump(manifest,stream,indent=2)
    return manifest


def prepare(root):
    # Only validate/install the original unchanged linear package and its base
    # address-map patches; NEVER overwrite any already measured package.
    path=HERE.parent/"google_llm_ops/prepare.py";sys.path.insert(0,str(path.parent))
    s=importlib.util.spec_from_file_location("_lv_original_linear_prepare",path)
    base=importlib.util.module_from_spec(s);s.loader.exec_module(base);base.prepare(root)
    result=install(root,expected(root))
    print("[LLM_VME_PREPARED] previous_candidates_unchanged=true RTL=NOT_RUN")
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--upstream",type=Path,required=True)
    prepare(p.parse_args().upstream.resolve(strict=True))
