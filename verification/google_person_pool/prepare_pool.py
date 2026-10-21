"""Independent VME+RVV AveragePool candidate; leave Depthwise and v1 untouched."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
VME=HERE.parent/"google_person_vme"
sys.path.insert(0,str(VME))
spec=importlib.util.spec_from_file_location("_pool_parent_candidate",VME/"prepare.py")
parent=importlib.util.module_from_spec(spec);spec.loader.exec_module(parent)
PACKAGE="tests/cocotb/person_detect_vme_pool_v1"
MANIFEST="person_detect_vme_pool_v1_manifest.json"


def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError("Parent anchor changed: "+old)
    return text.replace(old,new)


def program_source():
    text=parent.program_source().decode()
    text=replace_once(text,'#include "conv_vme.h"','#include "conv_vme.h"\n#include "pool_op.h"')
    text=replace_once(text,'resolver.AddAveragePool2D(tflite::Register_AVERAGE_POOL_2D_INT8())',
                      'resolver.AddAveragePool2D(person_pool::RegisterAveragePool())')
    text=replace_once(text,'  pd_status = 3;',
        '''  if (pd_pool_calls != 1 || pd_pool_fallbacks || !pd_pool_vector_blocks || pd_pool_mismatches)
    return fail(108);
#if PD_POOL_VALIDATE
  if (pd_pool_validated != 1) return fail(109);
#endif
  pd_status = 3;''')
    return text.encode()


def host_source():
    text=(VME/"host_model_test.cc").read_text()
    text=replace_once(text,'#include "conv_vme.h"','#include "conv_vme.h"\n#include "pool_op.h"')
    text=replace_once(text,'resolver.AddAveragePool2D(tflite::Register_AVERAGE_POOL_2D_INT8())',
                      'resolver.AddAveragePool2D(person_pool::RegisterAveragePool())')
    text=replace_once(text,'    CHECK(pd_vme_emulated_tiles>0);',
        '''    CHECK(pd_vme_emulated_tiles>0);
    CHECK(pd_pool_calls==static_cast<unsigned>(c+1));
    CHECK(pd_pool_validated==pd_pool_calls && pd_pool_fallbacks==0 && pd_pool_mismatches==0);
    CHECK(pd_pool_emulated_blocks>0 && pd_pool_vector_blocks==0);''')
    text=text.replace("PERSON_VME_HOST_MODEL_CASE","PERSON_POOL_HOST_MODEL_CASE").replace("layers=14 byte_exact", "conv_layers=14 pool_layers=1 byte_exact")
    text=text.replace("PERSON_VME_HOST_MODEL_PASS","PERSON_POOL_HOST_MODEL_PASS").replace("compared_layers=28", "compared_layers=30")
    return text.encode()


def build_text():
    text=parent.build_text().decode()
    text=text.replace('name = "person_vme_validate"','name = "person_vme_pool_validate"').replace('name = "person_vme_fast"','name = "person_vme_pool_fast"')
    text=text.replace('srcs = ["person_program.cc", "model_data.cc", "conv_vme.cc"]',
                      'srcs = ["person_program.cc", "model_data.cc", "conv_vme.cc", "pool_op.cc"]')
    text=text.replace('"pointwise_core.h", "vme_tile.h"]',
                      '"pointwise_core.h", "vme_tile.h", "pool_op.h", "pool_core.h", "pool_rvv.h"]')
    text=text.replace('"conv_vme.cc", "fixtures.cc"','"conv_vme.cc", "pool_op.cc", "fixtures.cc"')
    text=text.replace('"pointwise_core.h", "fixtures.h"]',
                      '"pointwise_core.h", "fixtures.h", "pool_op.h", "pool_core.h", "pool_rvv.h"]')
    for validate in (0,1):
        text=text.replace('"-DPD_VME_VALIDATE='+str(validate)+'"',
                          '"-DPD_VME_VALIDATE='+str(validate)+'", "-DPD_POOL_VALIDATE='+str(validate)+'"')
    text=text.replace('"-DPD_VME_EMULATE=1"','"-DPD_VME_EMULATE=1", "-DPD_POOL_EMULATE=1"')
    text+='''
cc_test(
    name = "host_pool_core_test",
    srcs = ["pool_core_test.cc", "pool_core.h"],
    copts = ["-O2", "-DPD_POOL_TFLM_REFERENCE=1"],
    deps = ["@tflite_micro//tensorflow/lite/micro:op_resolvers"],
)
'''
    return text.encode()


def expected_files(assets):
    result={PACKAGE+n[len(parent.PACKAGE):]:b for n,b in parent.expected_files(assets).items()}
    for n in ("pool_op.cc","pool_op.h","pool_core.h","pool_rvv.h","pool_core_test.cc"):
        result[PACKAGE+"/"+n]=(HERE/n).read_bytes()
    result[PACKAGE+"/BUILD"]=build_text()
    result[PACKAGE+"/person_program.cc"]=program_source()
    result[PACKAGE+"/host_model_test.cc"]=host_source()
    return result


def prepare(root,assets):
    if not (root/parent.MANIFEST).is_file():raise ValueError("Install/verify the existing VME v1 first")
    parent.prepare(root,assets)
    files=expected_files(assets)
    identity=dict(schema=1,status="CANDIDATE_NOT_RTL_VALIDATED",package=PACKAGE,
        parent_manifest_sha256=parent.sha((root/parent.MANIFEST).read_bytes()),
        upstream=parent.UPSTREAM,tflm_commit=parent.TFLM_COMMIT,model_sha256=parent.MODEL_SHA256,
        itcm_kib=256,dtcm_kib=512,depthwise="official_default_registration_unchanged",
        backend="VME_pointwise_RVV_average_pool_reference_depthwise_softmax_reshape",
        files={n:parent.sha(b) for n,b in files.items()},generator_sha256=parent.sha(Path(__file__).read_bytes()))
    marker=root/MANIFEST
    if marker.exists():
        if json.loads(marker.read_text())!=identity or any((root/n).read_bytes()!=b for n,b in files.items()):
            raise ValueError("Existing pool candidate differs; nothing overwritten")
    else:
        if (root/PACKAGE).exists():raise ValueError("Unowned pool candidate directory")
        (root/PACKAGE).mkdir(parents=True,exist_ok=False)
        for n,b in files.items():
            with (root/n).open("xb") as stream:stream.write(b)
        with marker.open("x",encoding="utf-8") as stream:json.dump(identity,stream,indent=2)
    parent.prepare(root,assets)
    print("[PERSON_POOL_CANDIDATE_VERIFIED] depthwise_unchanged=true parent_unchanged=true NPU_RTL=NOT_RUN")
    return identity


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--upstream",type=Path,required=True);p.add_argument("--assets",type=Path,required=True)
    a=p.parse_args();prepare(a.upstream.resolve(strict=True),a.assets.resolve(strict=True))
