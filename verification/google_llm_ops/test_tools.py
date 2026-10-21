"""Tooling and independent scalar checks; these never claim NPU/RVV execution."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import spec
import prepare
import audit

HERE = Path(__file__).resolve().parent


def observation(index=0):
    name,m,k,n = spec.CASES[index]; v = spec.vectors(index)
    return dict(schema=1,scope=spec.SCOPE,case_id=index,case=name,M=m,K=k,N=n,
        itcm_kib=256,dtcm_kib=512,fault=False,natural_halt=True,firmware_status=3,
        mismatches=0,guard_ok=True,stack_low_canary_intact=True,
        checked_elements=4*m*n,signature=v["signature"],vector_sha256=v["vector_sha256"],
        input_readback_equal=True,output_readback_equal=True,rvv_calls=4,samples=4,
        elf_sha256="a"*64,rtl_sha256="b"*64,observation_elapsed_cycles=10000,
        empty_boundary_cycles=3,scalar_cycles=[800]*4,rvv_cycles=[100]*4)


class Tools(unittest.TestCase):
    def test_vectors_symmetric_weight_domain_and_independent_integer_range(self):
        for i,(_,m,k,n) in enumerate(spec.CASES):
            value = spec.vectors(i)
            self.assertEqual(value,spec.vectors(i))
            signed = lambda x: x if x<128 else x-256
            x,w = list(map(signed,value["x"])),list(map(signed,value["w"]))
            self.assertEqual((len(x),len(w),len(value["y"])),(m*k,k*n,m*n))
            self.assertIn(-128,x);self.assertNotIn(-128,w)
            self.assertTrue(all(abs(y)<=k*128*127 for y in value["y"]))
            self.assertEqual(value["y"][0],sum(x[d]*w[d*n] for d in range(k)))

    def test_actual_native_reference_matches_python_all_four_not_rvv(self):
        compiler = os.environ.get("LLM_TEST_CXX")
        if not compiler:
            self.skipTest("Set LLM_TEST_CXX to native C++ compiler")
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory)/("reference.exe" if os.name=="nt" else "reference")
            subprocess.run([compiler,"-std=c++17","-O2","-Wall","-Wextra","-Werror","-DLLM_HOST=1",
                            str(HERE/"linear_bench.cc"),"-o",str(executable)],check=True,capture_output=True)
            result = subprocess.run([str(executable)],check=True,capture_output=True,text=True)
            audit.checked_host(result.stdout)
            self.assertIn("RVV=NOT_RUN",result.stdout)

    def test_native_evidence_cannot_be_duplicate_or_partial_or_wrong_signature(self):
        text = "".join("[LLM_LINEAR_HOST_REFERENCE] case=%d checked=%d signature=%d RVV=NOT_RUN\n" %
            (i,4*c[1]*c[3],spec.vectors(i)["signature"]) for i,c in enumerate(spec.CASES))
        audit.checked_host(text)
        for bad in (text*2,text.splitlines()[0],text.replace("case=0","case=1"),
                    text.replace("signature=", "signature=1"),text+"FAILED\n"):
            with self.assertRaises(ValueError):audit.checked_host(bad)

    def test_no_false_performance_pass_from_bad_halt_shape_domain_or_cycles(self):
        row=observation();spec.accept(row,0)
        bad_values=dict(fault=True,natural_halt=False,firmware_status=2,mismatches=1,
            guard_ok=False,stack_low_canary_intact=False,checked_elements=31,
            signature=0,rvv_calls=0,output_readback_equal=False,vector_sha256="c"*64,
            itcm_kib=8,scalar_cycles=[800]*3,rvv_cycles=[0]*4,elf_sha256="",M=16,
            observation_elapsed_cycles=100)
        for key,value in bad_values.items():
            bad=copy.deepcopy(row);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):spec.accept(bad,0)
        slower=copy.deepcopy(row);slower["rvv_cycles"]=[900]*4
        self.assertLess(spec.accept(slower,0)["steady_scalar_over_rvv"],1)

    def test_rtl_log_needs_exactly_one_passed_cocotb_test(self):
        raw=spec.MARKER+json.dumps(observation())+"\x1b[39m\nTESTS=1 PASS=1 FAIL=0 SKIP=0\n"
        spec.checked_log(raw,0)
        for bad in (raw*2,raw.replace("PASS=1 FAIL=0","PASS=0 FAIL=1"),
                    raw.split("\n")[0],raw.replace(spec.MARKER,"[HOST_ONLY] ")):
            with self.assertRaises(ValueError):spec.checked_log(bad,0)

    def test_independent_install_refuses_existing_or_changed_files(self):
        data={"rvv_int8_matmul.cc":b"official", "linear_bench.cc":b"bench"}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            first=prepare.install(root,data)
            self.assertEqual(first,prepare.install(root,data))
            path=root/spec.PACKAGE/"linear_bench.cc"
            path.write_bytes(b"user edit")
            with self.assertRaises(ValueError):prepare.install(root,data)
            self.assertEqual(path.read_bytes(),b"user edit")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/spec.PACKAGE).mkdir(parents=True)
            with self.assertRaises(ValueError):prepare.install(root,data)

    def test_build_has_explicit_vectors_no_autovec_and_not_highmem_original_runner(self):
        text=prepare.build_text()
        for token in ('"-fno-tree-vectorize"','"-fno-tree-slp-vectorize"','"-fno-lto"',
                      'itcm_size_kbytes=256,dtcm_size_kbytes=512',
                      '--itcmSizeKBytes=256','--dtcmSizeKBytes=512','trace=False'):
            self.assertIn(token,text)
        self.assertNotIn("Highmem",text)
        self.assertNotIn("1024,dtcm_size_kbytes=1024",text)
        self.assertEqual(text.count('"llm_decode_tiny_test"'),1)

    def test_real_rv32_objects_and_scalar_disassembly_not_full_link_or_execution(self):
        compiler=os.environ.get("LLM_TEST_CROSS")
        objdump=os.environ.get("LLM_TEST_OBJDUMP")
        if not compiler or not objdump:
            self.skipTest("Set LLM_TEST_CROSS and LLM_TEST_OBJDUMP for target object checks")
        import re
        root=HERE.parent.parent
        official=subprocess.check_output(["git","--git-dir="+str(root/".upstream-git/coralnpu-google.git"),
            "show",spec.UPSTREAM+":"+prepare.OFFICIAL])
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)
            for name,raw in (("linear_bench.cc",(HERE/"linear_bench.cc").read_bytes()),("rvv_int8_matmul.cc",official)):
                source=target/name;source.write_bytes(raw)
                result=subprocess.run([compiler,"-std=c++17","-march=rv32imafcv_zicsr","-mabi=ilp32f",
                    "-O2","-fno-tree-vectorize","-fno-tree-slp-vectorize","-fno-lto","-c",str(source),
                    "-o",str(source.with_suffix(".o"))],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            output=subprocess.check_output([objdump,"-d","-C",str(target/"linear_bench.o")],text=True)
            match=re.search(r"^[0-9a-f]+ <\(anonymous namespace\)::Scalar\(.*?(?=\n[0-9a-f]+ <|\Z)",output,re.M|re.S)
            self.assertIsNotNone(match,output)
            self.assertIsNone(re.search(r"\t[v][a-z0-9]+[.\s]",match.group()),match.group())
            rvv=subprocess.check_output([objdump,"-d",str(target/"rvv_int8_matmul.o")],text=True)
            self.assertIn("vwmul",rvv);self.assertIn("vwmacc",rvv)

    def test_elf_audit_rejects_wrong_isa_memory_selector_or_symbol_size(self):
        class Segment(dict):
            def data(self):return b"\xfe\xff\xff\xff"
        class Symbol(dict):
            def __init__(self,name,address,size):
                super().__init__(st_value=address,st_size=size,st_shndx=1);self.name=name
        class FakeElf:
            elfclass=32;little_endian=True
            header=dict(e_machine="EM_RISCV",e_entry=0)
            def __init__(self):
                self.segments=[Segment(p_type="PT_LOAD",p_paddr=0,p_vaddr=0,p_memsz=4096,p_filesz=4096,p_flags=5),
                    Segment(p_type="PT_LOAD",p_paddr=0x01000000,p_vaddr=0x01000000,p_memsz=32768,p_filesz=4,p_flags=6)]
                self.symbols=[];address=0x01000000
                for name,size in audit.SIZES.items():
                    self.symbols.append(Symbol(name,address,size));address+=size
                for name,address in zip(audit.LINKER,(0x0107c000,0x01080000,0x01008000,0x0107c000)):
                    self.symbols.append(Symbol(name,address,0))
            def iter_segments(self):return iter(self.segments)
            def get_section_by_name(self,name):return self
            def iter_symbols(self):return iter(self.symbols)
        elf=FakeElf()
        with patch.object(audit,"ELFFile",return_value=elf):
            report=audit.inspect(b"test")
            self.assertEqual(report["NPU_RTL"],"NOT_RUN")
            self.assertEqual(report["dtcm_kib"],512)
        bads=[]
        bad=copy.deepcopy(elf);bad.elfclass=64;bads.append(bad)
        bad=copy.deepcopy(elf);bad.segments[1]["p_paddr"]=0x00100000;bads.append(bad)
        bad=copy.deepcopy(elf);bad.symbols[0]["st_size"]=8;bads.append(bad)
        bad=copy.deepcopy(elf);bad.segments[1]["p_filesz"]=0;bads.append(bad)
        bad=copy.deepcopy(elf);bad.symbols.pop();bads.append(bad)
        for bad in bads:
            with patch.object(audit,"ELFFile",return_value=bad),self.assertRaises(ValueError):audit.inspect(b"test")

    def test_generated_parameters_must_keep_current_256_512_configuration(self):
        values=dict(xlen="32",itcmSizeKBytes="256",dtcmSizeKBytes="512",axi2IdBits="6",
            rvvVlen="128",fetchDataBits="128",lsuDataBits="128",enableFetchL0="false",
            enableRvv="true",enableVme="true",enableFloat="true",enableZfbfmin="true",
            enableVectorBf16="true",enableAxiInstructionFetch="true",enableVerification="false")
        text="".join("#define KP_"+k+" "+v+"\n" for k,v in values.items())
        self.assertEqual(audit.checked_header(text),values)
        for field in ("itcmSizeKBytes","dtcmSizeKBytes","enableAxiInstructionFetch","enableRvv"):
            bad=text.replace("#define KP_"+field+" "+values[field],"#define KP_"+field+" wrong")
            with self.assertRaises(ValueError):audit.checked_header(bad)


if __name__ == "__main__":
    unittest.main()
