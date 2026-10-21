"""Independent one-Conv microbench: original constants/quantization, small M."""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
VME=HERE.parent/"google_person_vme"
sys.path.insert(0,str(VME))
spec=importlib.util.spec_from_file_location("_conv_parent_candidate",VME/"prepare.py")
parent=importlib.util.module_from_spec(spec);spec.loader.exec_module(parent)
PACKAGE="tests/cocotb/person_conv_bench_v1"
MANIFEST="person_conv_bench_v1_manifest.json"
SELECTION=((2,16),(8,16),(24,9),(26,1),(28,1))
REPEATS=3


def digest(data):return hashlib.sha256(data).hexdigest()


def vector(b,values,kind):
    sizes={"offset":(4,4),"i32":(4,4),"i64":(8,8),"f32":(4,4)}
    size,align=sizes[kind];b.StartVector(size,len(values),align)
    method={"offset":b.PrependUOffsetTRelative,"i32":b.PrependInt32,"i64":b.PrependInt64,"f32":b.PrependFloat32}[kind]
    for value in reversed(values):method(value)
    return b.EndVector()


def quant(b,t,q):
    if q is None or q.DetailsType()!=0:raise ValueError("Unsupported quantization details")
    fields={n:vector(b,[getattr(q,n)(i) for i in range(getattr(q,n+"Length")())],kind)
            for n,kind in (("Min","f32"),("Max","f32"),("Scale","f32"),("ZeroPoint","i64"))}
    t.QuantizationParametersStart(b)
    for n,value in fields.items():getattr(t,"QuantizationParametersAdd"+n)(b,value)
    t.QuantizationParametersAddQuantizedDimension(b,q.QuantizedDimension())
    return t.QuantizationParametersEnd(b)


def constant(model,tensor):
    buf=model.Buffers(tensor.Buffer())
    return bytes(buf.DataAsNumpy()) if buf.DataLength() else b""


def one_conv(model,index,positions):
    import flatbuffers
    import tflite as t
    g=model.Subgraphs(0);op=g.Operators(index);code=model.OperatorCodes(op.OpcodeIndex())
    if code.BuiltinCode()!=t.BuiltinOperator.CONV_2D or op.InputsLength()!=3 or op.OutputsLength()!=1:
        raise ValueError("Selected operator is not a supported biased Conv2D")
    original=[g.Tensors(op.Inputs(i)) for i in range(3)]+[g.Tensors(op.Outputs(0))]
    shape=[[int(x) for x in item.ShapeAsNumpy()] for item in original]
    if (shape[0][0]!=1 or shape[1][1:3]!=[1,1] or shape[0][3]!=shape[1][3] or
        shape[1][0]!=shape[3][3] or not 1<=positions<=shape[0][1]*shape[0][2]):
        raise ValueError("Unsupported original pointwise shape")
    options=t.Conv2DOptions();raw=op.BuiltinOptions();options.Init(raw.Bytes,raw.Pos)
    if (options.StrideH()!=1 or options.StrideW()!=1 or options.DilationHFactor()!=1 or
        options.DilationWFactor()!=1):raise ValueError("Only unit-stride/dilation pointwise")
    b=flatbuffers.Builder(1024)
    buffers=[]
    for data in (b"",constant(model,original[1]),constant(model,original[2])):
        values=b.CreateByteVector(data);t.BufferStart(b);t.BufferAddData(b,values);buffers.append(t.BufferEnd(b))
    tensors=[]
    for i,item in enumerate(original):
        dims=[1,1,positions,shape[i][3]] if i in (0,3) else shape[i]
        dims=vector(b,dims,"i32");q=quant(b,t,item.Quantization())
        name=b.CreateString("bench_op"+str(index)+"_tensor"+str(i))
        t.TensorStart(b);t.TensorAddShape(b,dims);t.TensorAddType(b,item.Type())
        t.TensorAddBuffer(b,(0,1,2,0)[i]);t.TensorAddName(b,name);t.TensorAddQuantization(b,q)
        t.TensorAddHasRank(b,item.HasRank());tensors.append(t.TensorEnd(b))
    t.Conv2DOptionsStart(b)
    for n in ("Padding","StrideW","StrideH","FusedActivationFunction","DilationWFactor","DilationHFactor","QuantizedBiasType"):
        getattr(t,"Conv2DOptionsAdd"+n)(b,getattr(options,n)())
    opts=t.Conv2DOptionsEnd(b)
    inputs=vector(b,[0,1,2],"i32");outputs=vector(b,[3],"i32")
    t.OperatorStart(b);t.OperatorAddOpcodeIndex(b,0);t.OperatorAddInputs(b,inputs);t.OperatorAddOutputs(b,outputs)
    t.OperatorAddBuiltinOptionsType(b,t.BuiltinOptions.Conv2DOptions);t.OperatorAddBuiltinOptions(b,opts)
    operator=t.OperatorEnd(b)
    tensors=vector(b,tensors,"offset");inputs=vector(b,[0],"i32");outputs=vector(b,[3],"i32")
    operators=vector(b,[operator],"offset")
    t.SubGraphStart(b);t.SubGraphAddTensors(b,tensors);t.SubGraphAddInputs(b,inputs)
    t.SubGraphAddOutputs(b,outputs);t.SubGraphAddOperators(b,operators);graph=t.SubGraphEnd(b)
    t.OperatorCodeStart(b);t.OperatorCodeAddBuiltinCode(b,code.BuiltinCode())
    t.OperatorCodeAddDeprecatedBuiltinCode(b,code.DeprecatedBuiltinCode());t.OperatorCodeAddVersion(b,code.Version())
    opcode=t.OperatorCodeEnd(b)
    graphs=vector(b,[graph],"offset");opcodes=vector(b,[opcode],"offset");buffers=vector(b,buffers,"offset")
    description=b.CreateString("one-op diagnostic derivative of original person model; synthetic activations")
    t.ModelStart(b);t.ModelAddVersion(b,model.Version());t.ModelAddSubgraphs(b,graphs)
    t.ModelAddOperatorCodes(b,opcodes);t.ModelAddBuffers(b,buffers);t.ModelAddDescription(b,description)
    b.Finish(t.ModelEnd(b),file_identifier=b"TFL3")
    return bytes(b.Output()),original,shape


def inputs_for(index,count):
    seed=137+index;result=bytearray()
    for _ in range(count):
        seed^=(seed<<13)&0xffffffff;seed^=seed>>17;seed^=(seed<<5)&0xffffffff;seed&=0xffffffff
        result.append(seed&255)
    return bytes(result)


def fixtures(assets):
    import tflite as t
    for name,version in (("flatbuffers","25.12.19"),("tflite","2.18.0")):
        if importlib.metadata.version(name)!=version:raise ValueError("Use pinned generator dependency: "+name)
    data=parent.checked_asset(assets,parent.MODEL_NAME);model=t.Model.GetRootAsModel(data,0)
    header='''// Generated diagnostics, NOT the unchanged complete pretrained model.
#pragma once
#include <cstdint>
#include <cstddef>
struct ConvCase {const unsigned char* model;const int8_t* input;unsigned bytes,input_bytes;int op,m,k,n;const char* name;};
extern const ConvCase kConvCases[5];
constexpr unsigned kConvCaseCount=5,kConvSteadyRepeats=3,kConvSamples=4,kConvArenaBytes=65536;
'''
    source='#include "conv_cases.h"\n';cases=[];table=[]
    def array(name,raw):
        return 'alignas(16) const unsigned char '+name+'[] __attribute__((section(".data.conv_fixtures"),used))={\n'+\
            ',\n'.join(','.join(map(str,raw[i:i+32])) for i in range(0,len(raw),32))+'\n};\n'
    for case_id,(index,m) in enumerate(SELECTION):
        small,original,shapes=one_conv(model,index,m);k,n=shapes[0][3],shapes[3][3]
        inputs=inputs_for(index,m*k);name="op"+str(index)+"_m"+str(m)+"_k"+str(k)+"_n"+str(n)
        source+=array("model_"+str(case_id),small)+array("input_"+str(case_id),inputs)
        table.append('{model_'+str(case_id)+',reinterpret_cast<const int8_t*>(input_'+str(case_id)+'),'+
            ','.join(map(str,(len(small),len(inputs),index,m,k,n)))+',"'+name+'"}')
        cases.append(dict(id=case_id,name=name,original_operator_index=index,original_input_shape=shapes[0],
            original_output_shape=shapes[3],benchmark_input_shape=[1,1,m,k],benchmark_output_shape=[1,1,m,n],
            M=m,K=k,N=n,useful_macs=m*k*n,derived_model_sha256=digest(small),input_sha256=digest(inputs),
            input_kind="synthetic_seed137_plus_op_not_captured_model_activation",weight_sha256=digest(constant(model,original[1])),
            bias_sha256=digest(constant(model,original[2])),constants_and_quantization="copied_original_unchanged"))
    source+='const ConvCase kConvCases[5]={\n'+',\n'.join(table)+'\n};\n'
    return {"conv_cases.h":header.encode(),"conv_cases.cc":source.encode()},cases


def build_text():
    deps='["@tflite_micro//tensorflow/lite/micro:micro_framework", "@tflite_micro//tensorflow/lite/micro:micro_log", "@tflite_micro//tensorflow/lite/micro:op_resolvers", "@tflite_micro//tensorflow/lite/kernels/internal:common"]'
    return '''load("@rules_cc//cc:defs.bzl", "cc_test")
load("//rules:coralnpu_v2.bzl", "coralnpu_v2_binary")
package(default_visibility=["//visibility:public"])
'''+'''coralnpu_v2_binary(
    name="probe_program",
    srcs=["conv_bench.cc","conv_cases.cc","conv_vme.cc"],
    hdrs=["conv_cases.h","conv_vme.h","pointwise_core.h","vme_tile.h"],
    copts=["-O2","-fno-tree-vectorize","-fno-tree-slp-vectorize","-fno-lto","-DPD_VME_VALIDATE=0"],
    itcm_size_kbytes=256,dtcm_size_kbytes=512,stack_size_bytes=16384,enable_vmem=False,
    deps='''+deps+''',
)
cc_test(
    name="host_test",
    srcs=["conv_bench.cc","conv_cases.cc","conv_vme.cc","conv_cases.h","conv_vme.h","pointwise_core.h"],
    copts=["-O2","-DPD_CONV_HOST=1","-DPD_VME_EMULATE=1","-DPD_VME_VALIDATE=0"],
    deps='''+deps+''',
    timeout="long",
)
'''


def prepare(root,assets):
    parent.prepare(root,assets)
    files,cases=fixtures(assets)
    files.update({n:(VME/n).read_bytes() for n in ("conv_vme.cc","conv_vme.h","pointwise_core.h","vme_tile.h")})
    files.update({"conv_bench.cc":(HERE/"conv_bench.cc").read_bytes(),"BUILD":build_text().encode()})
    files={PACKAGE+"/"+n:b for n,b in files.items()}
    manifest=dict(schema=1,kind="single_conv_spatial_fragment_benchmark",source_model_sha256=parent.MODEL_SHA256,
        upstream=parent.UPSTREAM,tflm_commit=parent.TFLM_COMMIT,itcm_kib=256,dtcm_kib=512,cases=cases,
        steady_repeats=REPEATS,first_call_samples=1,
        compilation="bench_and_custom_kernel_O2_no_autovec_no_LTO_reference_unchanged_pinned_TFLM",
        scope="single_op_Invoke_includes_VME_pack_bias_correction_quantize_writeback_excludes_Prepare_and_checks",
        files={n:digest(b) for n,b in files.items()},generator_sha256=digest(Path(__file__).read_bytes()))
    marker=root/MANIFEST
    if marker.exists():
        if json.loads(marker.read_text())!=manifest or any((root/n).read_bytes()!=b for n,b in files.items()):
            raise ValueError("Existing Conv benchmark differs; preserve it, nothing overwritten")
    else:
        if (root/PACKAGE).exists():raise ValueError("Unowned Conv benchmark directory")
        (root/PACKAGE).mkdir(parents=True)
        for n,b in files.items():
            with (root/n).open("xb") as stream:stream.write(b)
        with marker.open("x",encoding="utf-8") as stream:json.dump(manifest,stream,indent=2)
    print("[PERSON_CONV_CANDIDATE_PREPARED] old_candidates_unchanged=true full_model=NOT_RUN RTL=NOT_RUN")
    return manifest


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--upstream",type=Path,required=True);p.add_argument("--assets",type=Path,required=True)
    a=p.parse_args();prepare(a.upstream.resolve(strict=True),a.assets.resolve(strict=True))
