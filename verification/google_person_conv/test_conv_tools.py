"""Single-Conv tooling checks; local tests are not NPU performance results."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
import tflite as t

import prepare_conv as prepare
import audit_conv as audit

HERE=Path(__file__).resolve().parent
ASSETS=HERE.parent.parent/".upstream-git/model-cache/person_detect_b75c6ff4"


class ConvChecks(unittest.TestCase):
    def original(self):
        path=ASSETS/"person_detect.tflite"
        if not path.exists():self.skipTest("Actual pinned model cache unavailable")
        data=path.read_bytes();self.assertEqual(prepare.digest(data),prepare.parent.MODEL_SHA256)
        return t.Model.GetRootAsModel(data,0)

    def test_selected_derivatives_have_one_conv_and_original_constants_and_quantization(self):
        model=self.original()
        for index,m in prepare.SELECTION:
            data,original,shapes=prepare.one_conv(model,index,m)
            small=t.Model.GetRootAsModel(data,0);g=small.Subgraphs(0)
            self.assertEqual(g.OperatorsLength(),1);self.assertEqual(g.TensorsLength(),4)
            self.assertEqual(small.OperatorCodes(0).BuiltinCode(),t.BuiltinOperator.CONV_2D)
            self.assertEqual(list(g.Tensors(0).ShapeAsNumpy()),[1,1,m,shapes[0][3]])
            self.assertEqual(list(g.Tensors(3).ShapeAsNumpy()),[1,1,m,shapes[3][3]])
            for i in range(4):
                a,b=original[i].Quantization(),g.Tensors(i).Quantization()
                for name in ("Scale","ZeroPoint","Min","Max"):
                    self.assertEqual([getattr(a,name)(j) for j in range(getattr(a,name+"Length")())],
                                     [getattr(b,name)(j) for j in range(getattr(b,name+"Length")())])
                self.assertEqual(a.QuantizedDimension(),b.QuantizedDimension())
            for i in (1,2):self.assertEqual(prepare.constant(model,original[i]),prepare.constant(small,g.Tensors(i)))
            old=t.Conv2DOptions();oldraw=model.Subgraphs(0).Operators(index).BuiltinOptions();old.Init(oldraw.Bytes,oldraw.Pos)
            new=t.Conv2DOptions();newraw=g.Operators(0).BuiltinOptions();new.Init(newraw.Bytes,newraw.Pos)
            for n in ("Padding","StrideW","StrideH","FusedActivationFunction","DilationWFactor","DilationHFactor","QuantizedBiasType"):
                self.assertEqual(getattr(old,n)(),getattr(new,n)())

    def test_local_litert_reference_accepts_each_small_model_not_vme_execution(self):
        model=self.original()
        try:from ai_edge_litert.interpreter import Interpreter,OpResolverType
        except ImportError:self.skipTest("Local LiteRT reference not installed")
        for index,m in prepare.SELECTION:
            data,_,shapes=prepare.one_conv(model,index,m)
            engine=Interpreter(model_content=data,experimental_op_resolver_type=OpResolverType.BUILTIN_REF,num_threads=1)
            engine.allocate_tensors()
            inputs=np.frombuffer(prepare.inputs_for(index,m*shapes[0][3]),dtype=np.int8).reshape(1,1,m,shapes[0][3])
            engine.set_tensor(engine.get_input_details()[0]["index"],inputs);engine.invoke()
            first=engine.get_tensor(engine.get_output_details()[0]["index"])
            engine.invoke();second=engine.get_tensor(engine.get_output_details()[0]["index"])
            np.testing.assert_array_equal(first,second)
            self.assertEqual(first.shape,(1,1,m,shapes[3][3]))
            self.assertEqual(first.dtype,np.int8)

    def test_input_deterministic_signed_and_invalid_selection_rejected(self):
        raw=prepare.inputs_for(2,128)
        self.assertEqual(raw,prepare.inputs_for(2,128))
        self.assertNotEqual(raw,prepare.inputs_for(8,128))
        signed=np.frombuffer(raw,dtype=np.int8)
        self.assertTrue((signed<0).any() and (signed>0).any())
        model=self.original()
        for index,m in ((0,1),(2,0),(2,2305)):
            with self.assertRaises(ValueError):prepare.one_conv(model,index,m)

    def test_identity_install_is_independent_and_refuses_mutation(self):
        model=self.original()
        del model
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(prepare.parent,"prepare"):
                first=prepare.prepare(root,ASSETS);second=prepare.prepare(root,ASSETS)
                self.assertEqual(first,second);self.assertEqual(len(first["cases"]),5)
                kernel=root/prepare.PACKAGE/"conv_vme.cc"
                self.assertEqual(kernel.read_bytes(),(prepare.VME/"conv_vme.cc").read_bytes())
                kernel.write_bytes(b"user modification")
                with self.assertRaisesRegex(ValueError,"nothing overwritten"):prepare.prepare(root,ASSETS)
                self.assertEqual(kernel.read_bytes(),b"user modification")

    def test_native_evidence_requires_all_five_cases_and_checked_counts(self):
        cases=[dict(id=i,name="case"+str(i),M=16,N=i+1) for i in range(5)]
        lines=''.join("[PERSON_CONV_HOST_CASE] id="+str(c["id"])+" name="+c["name"]+" checked="+
            str(4*c["M"]*c["N"])+" signature=137 ref_and_emulated_vme_equal=true\n" for c in cases)
        lines+="[PERSON_CONV_HOST_PASS] cases=5 complete_model=NOT_RUN hardware=NOT_RUN\n"
        self.assertEqual(len(audit.checked_host(lines,cases)),5)
        for bad in (lines*2,lines.replace("checked=64","checked=63"),lines+"FAILED\n",lines.replace("cases=5","cases=4")):
            with self.assertRaises(ValueError):audit.checked_host(bad,cases)

    def test_selector_is_initialized_data_not_bss_and_diagnostics_need_correct_width(self):
        class Symbol(dict):
            def __init__(self,name,index):
                super().__init__(st_value=0x01000000+index*32,st_size=audit.EXTRA[name],st_shndx=2);self.name=name
        symbols=[Symbol(n,i) for i,n in enumerate(audit.EXTRA)]
        image=bytearray(4096)
        for s in symbols:
            if s.name=="pd_conv_case":image[s["st_value"]-0x01000000:s["st_value"]-0x01000000+4]=bytes.fromhex("feffffff")
        class Segment(dict):
            def data(self):return bytes(image)
        segment=Segment(p_type="PT_LOAD",p_paddr=0x01000000,p_filesz=len(image))
        elf=SimpleNamespace(get_section_by_name=lambda _:SimpleNamespace(iter_symbols=lambda:symbols),iter_segments=lambda:[segment])
        report=dict(segments=[dict(address=0,bytes=1024),dict(address=0x01000000,bytes=8192)],
            symbols={"__heap_start__":{"address":0x01002000},"__heap_end__":{"address":0x0107c000}})
        with patch.object(audit.probe_audit,"inspect",side_effect=lambda _:copy.deepcopy(report)),patch.object(audit,"ELFFile",return_value=elf):
            self.assertEqual(audit.inspect(b"synthetic")["steady_repeats"],3)
            image[:4]=bytes(4)
            with self.assertRaisesRegex(ValueError,"survive CRT"):audit.inspect(b"synthetic")
            image[:4]=bytes.fromhex("feffffff");symbols[1]["st_size"]=1
            with self.assertRaisesRegex(ValueError,"geometry"):audit.inspect(b"synthetic")

    def test_timing_excludes_checks_and_reference_not_hidden_inside_vme(self):
        text=(HERE/"conv_bench.cc").read_text()
        begin=text.index("const uint32_t start=Cycle();")
        end=text.index("const uint32_t elapsed=Cycle()-start;",begin)
        self.assertEqual(text[begin:end].count("interpreter.Invoke()"),1)
        self.assertNotIn("memcpy",text[begin:end]);self.assertNotIn("printf",text[begin:end])
        self.assertIn("for(unsigned r=0;r<kConvSamples",text)
        self.assertIn("((t+r)%2)",text)
        build=prepare.build_text()
        self.assertIn('"-DPD_VME_VALIDATE=0"',build)
        self.assertIn('"-DPD_VME_EMULATE=1"',build)
        self.assertNotIn("person_detect_vme_pool_v1",build)


if __name__=="__main__":unittest.main()
