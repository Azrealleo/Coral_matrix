"""No RTL claims: native math, actual RV32 compilation, and acceptance tools."""
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import tx_spec as spec
import tx_prepare as prepare
import tx_audit as audit

HERE=Path(__file__).resolve().parent


def observation(index=2):
    item=spec.fixture(index)
    return dict(schema=1,scope=spec.SCOPE,case_id=index,case=item["name"],kind=item["kind"],shape=item["shape"],
        itcm_kib=256,dtcm_kib=512,fault=False,natural_halt=True,firmware_status=3,mismatches=0,
        guard_ok=True,stack_low_canary_intact=True,input_readback_equal=True,independent_output_check=True,
        checked_elements=4*len(item["y"]),rvv_calls=4,vector_sha256=item["vector_sha256"],atol=spec.ATOL,rtol=spec.RTOL,
        elf_sha256="a"*64,rtl_sha256="b"*64,scalar_max_abs_error=0.000001,rvv_max_abs_error=0.000002,
        scalar_cycles=[800]*4,rvv_cycles=[200]*4,empty_boundary_cycles=3,observation_elapsed_cycles=10000)


class Checks(unittest.TestCase):
    def test_all_fixtures_finite_deterministic_and_fit(self):
        for i in range(len(spec.CASES)):
            item=spec.fixture(i);self.assertEqual(item,spec.fixture(i))
            for n in ("x","w","v","y"):
                self.assertLessEqual(len(item[n]),1024)
                self.assertTrue(all(math.isfinite(x) for x in item[n]))
        source=prepare.fixtures().decode();self.assertNotIn("reinterpret_cast",source)
        self.assertEqual(source.count("extern const Case kCases[]"),1)

    def test_causal_future_poison_is_invisible_and_unmasked_would_fail(self):
        first,poison=spec.fixture(15),spec.fixture(16)
        self.assertEqual(first["x"],poison["x"]);self.assertNotEqual(first["v"],poison["v"])
        self.assertEqual(first["y"],poison["y"])
        self.assertEqual(first["y"],first["v"][:16]*2)
        unmasked=spec.golden("ATTENTION",(2,1,4,16,3),poison["x"],poison["w"],poison["v"])
        self.assertTrue(any(abs(x-y)>1 for x,y in zip(unmasked,first["y"])))

    def test_softmax_extreme_is_stable_and_rows_sum_one(self):
        item=spec.fixture(6);cols=item["shape"][1]
        self.assertTrue(max(item["x"])>1000 and min(item["x"])<-1000)
        for at in range(0,len(item["y"]),cols):
            self.assertAlmostEqual(sum(item["y"][at:at+cols]),1,places=6)

    def test_rope_preserves_norm_and_kv_preserves_prefix(self):
        item=spec.fixture(8)
        self.assertAlmostEqual(sum(x*x for x in item["x"]),sum(y*y for y in item["y"]),places=3)
        item=spec.fixture(12)
        old,added=4*16,2*16
        self.assertEqual(item["y"][:old],item["x"][:old])
        self.assertEqual(item["y"][old+added:2*old+added],item["x"][old:])
        self.assertEqual(item["y"][old:old+added],item["w"][:added])

    def test_accept_rejects_fault_wrong_mask_tolerance_or_no_real_calls(self):
        row=observation();spec.accept(row,2)
        for key,value in dict(fault=True,natural_halt=False,firmware_status=2,mismatches=1,
            independent_output_check=False,guard_ok=False,atol=1.0,rtol=1.0,rvv_calls=0,
            rvv_max_abs_error=float("nan"),scalar_max_abs_error=1000.0,rvv_cycles=[0]*4,checked_elements=0,
            observation_elapsed_cycles=100,shape=[1,32,0,0,0]).items():
            bad=copy.deepcopy(row);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):spec.accept(bad,2)
        row["rvv_cycles"]=[900]*4
        self.assertLess(spec.accept(row,2)["steady_scalar_over_rvv"],1)

    def test_raw_log_requires_complete_single_pass(self):
        text=spec.MARKER+json.dumps(observation())+"\x1b[39m\nTESTS=1 PASS=1 FAIL=0 SKIP=0\n"
        spec.checked_log(text,2)
        for bad in (text*2,text.splitlines()[0],text.replace("PASS=1 FAIL=0","PASS=0 FAIL=1")):
            with self.assertRaises(ValueError):spec.checked_log(bad,2)

    def test_source_has_causal_mask_tail_checks_and_explicit_hybrid_math(self):
        raw=(HERE/"kernels.cc").read_text()
        self.assertEqual(raw.count("std::min(t.c,t.p+q+1)"),2)
        self.assertIn("This is scalar exp",raw)
        self.assertIn("1.0f+w[c]",raw)
        self.assertIn("verilator_model=\"//tests/cocotb/llm_linear_v1:model\"",prepare.build_text())
        for case,_,_ in spec.CASES:
            self.assertIn("async def tx_"+case+"_test",(HERE/"tx_bench.py").read_text())

    def test_native_all_17_against_independent_fp64_gold_not_rvv(self):
        compiler=os.environ.get("LLM_TEST_CXX")
        if not compiler:self.skipTest("Set LLM_TEST_CXX")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/"fixtures.cc").write_bytes(prepare.fixtures())
            executable=root/("test.exe" if os.name=="nt" else "test")
            argv=[compiler,"-std=c++17","-O2","-Wall","-Wextra","-Werror","-ffp-contract=off","-DTX_HOST=1",
                "-I"+str(HERE),str(HERE/"bench.cc"),str(HERE/"kernels.cc"),str(root/"fixtures.cc"),"-o",str(executable)]
            built=subprocess.run(argv,capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(executable)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            audit.checked_host(result.stdout)

    def test_rv32_actual_objects_and_no_dynamic_fixture_initialization(self):
        compiler=os.environ.get("LLM_TEST_CROSS");objdump=os.environ.get("LLM_TEST_OBJDUMP")
        if not compiler or not objdump:self.skipTest("Set target compiler/objdump")
        bare=HERE.parent.parent.parent/".upstream-git/coralnpu-google.git"
        official=subprocess.check_output(["git","--git-dir="+str(bare),"show",spec.UPSTREAM+":"+prepare.OFFICIAL])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,raw in (("bench.cc",(HERE/"bench.cc").read_bytes()),("kernels.cc",(HERE/"kernels.cc").read_bytes()),
                             ("fixtures.cc",prepare.fixtures()),("rvv_matmul.cc",official)):
                source=root/name;source.write_bytes(raw)
                result=subprocess.run([compiler,"-std=c++17","-march=rv32imafcv_zicsr","-mabi=ilp32f","-O2",
                    "-fno-tree-vectorize","-fno-tree-slp-vectorize","-fno-lto","-ffp-contract=off","-I"+str(HERE),
                    "-c",str(source),"-o",str(source.with_suffix(".o"))],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            disasm=subprocess.check_output([objdump,"-d","-C",str(root/"kernels.o")],text=True)
            self.assertIn("vfredusum",disasm);self.assertIn("vfmacc",disasm)
            symbols=subprocess.check_output([objdump,"-t",str(root/"fixtures.o")],text=True)
            self.assertNotIn("_GLOBAL__sub_I",symbols)
            from elftools.elf.elffile import ELFFile
            with (root/"fixtures.o").open("rb") as stream:
                elf=ELFFile(stream)
                table=elf.get_section_by_name(".symtab")
                item=next(s for s in table.iter_symbols() if s.name=="kCases")
                self.assertEqual(item["st_size"],60*len(spec.CASES))

    def test_independent_install_refuses_changed_or_unowned_package(self):
        files={"rvv_matmul.cc":b"official","bench.cc":b"bench"}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            first=prepare.install(root,files);self.assertEqual(first,prepare.install(root,files))
            path=root/spec.PACKAGE/"bench.cc";path.write_bytes(b"user edit")
            with self.assertRaises(ValueError):prepare.install(root,files)
            self.assertEqual(path.read_bytes(),b"user edit")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/spec.PACKAGE).mkdir(parents=True)
            with self.assertRaises(ValueError):prepare.install(root,files)

    def test_suite_has_serial_fixed_plan_no_fake_all_pass_for_partial_or_empty(self):
        import suite
        self.assertEqual(len(suite.plan("all")),21)
        self.assertEqual(suite.plan("all")[:4],[("int8",i) for i in range(4)])
        self.assertEqual(len(set(suite.plan("all"))),21)
        with tempfile.TemporaryDirectory() as directory:
            job=Path(directory);state=dict(mode="all",plan=[["fp32",2],["fp32",3]],cases={})
            self.assertEqual(suite.collect(job,state)["status"],"INCOMPLETE")
            record=dict(status="PASS",family="fp32",index=2)
            state["cases"]["fp32_2"]=record
            with patch.object(suite,"accepted",return_value=spec.accept(observation(),2)):
                report=suite.collect(job,state)
                self.assertEqual(report["status"],"INCOMPLETE");self.assertEqual(report["passed"],1)
                self.assertIn("INCOMPLETE",(job/"summary.md").read_text())
                state["cases"]["fp32_16"]=dict(record,index=16)
                with self.assertRaises(ValueError):suite.collect(job,state)
            for plan in ([],[["fp32",2],["fp32",2]]):
                with self.assertRaises(ValueError):suite.collect(job,dict(mode="all",plan=plan,cases={}))

    def test_resume_revalidates_raw_log_hash_before_skipping(self):
        import suite
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);log=root/"test.log";log.write_text("original raw evidence")
            record=dict(status="PASS",run=str(root),test_log_sha256=suite.sha(log),family="fp32",index=2,
                        comparison=spec.accept(observation(),2))
            with patch.object(suite.tx_summary,"summarize",return_value=record["comparison"]):
                self.assertEqual(suite.accepted(record),record["comparison"])
                log.write_text("changed")
                with self.assertRaises(ValueError):suite.accepted(record)

    def test_new_elf_audit_does_not_accept_wrong_map_or_bss_selector(self):
        class Segment(dict):
            def data(self):return b"\xfe\xff\xff\xff"
        class Symbol(dict):
            def __init__(self,name,address,size):
                super().__init__(st_value=address,st_size=size,st_shndx=1);self.name=name
        class FakeElf:
            elfclass=32;little_endian=True;header=dict(e_machine="EM_RISCV",e_entry=0)
            def __init__(self):
                self.segments=[Segment(p_type="PT_LOAD",p_paddr=0,p_vaddr=0,p_memsz=4096,p_filesz=4096,p_flags=5),
                    Segment(p_type="PT_LOAD",p_paddr=0x01000000,p_vaddr=0x01000000,p_memsz=65536,p_filesz=4,p_flags=6)]
                self.symbols=[];address=0x01000000
                for name,size in audit.SIZES.items():
                    self.symbols.append(Symbol(name,address,size));address+=size
                for name,address in zip(audit.LINKER,(0x0107c000,0x01080000,0x01010000,0x0107c000)):
                    self.symbols.append(Symbol(name,address,0))
            def iter_segments(self):return iter(self.segments)
            def get_section_by_name(self,name):return self
            def iter_symbols(self):return iter(self.symbols)
        elf=FakeElf()
        with patch.object(audit,"ELFFile",return_value=elf):self.assertEqual(audit.inspect(b"test")["NPU_RTL"],"NOT_RUN")
        for edit in ("size","address","selector"):
            bad=copy.deepcopy(elf)
            if edit=="size":bad.symbols[0]["st_size"]=8
            elif edit=="address":bad.segments[1]["p_paddr"]=0x00100000
            else:bad.segments[1]["p_filesz"]=0
            with patch.object(audit,"ELFFile",return_value=bad),self.assertRaises(ValueError):audit.inspect(b"test")

    def test_runtime_parameter_gate_rejects_other_ram_or_isa_configuration(self):
        # Compare against the independent existing parameter contract too.
        import importlib.util
        sys_path=__import__("sys").path
        sys_path.insert(0,str(HERE.parent))
        module_spec=importlib.util.spec_from_file_location("_tx_test_original_audit",HERE.parent/"audit.py")
        original=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(original)
        expected=dict(xlen="32",itcmSizeKBytes="256",dtcmSizeKBytes="512",axi2IdBits="6",
            rvvVlen="128",fetchDataBits="128",lsuDataBits="128",enableFetchL0="false",enableRvv="true",
            enableVme="true",enableFloat="true",enableZfbfmin="true",enableVectorBf16="true",
            enableAxiInstructionFetch="true",enableVerification="false")
        text="".join("#define KP_"+k+" "+v+"\n" for k,v in expected.items())
        self.assertEqual(audit.checked_header(text),original.checked_header(text))
        for name in ("itcmSizeKBytes","dtcmSizeKBytes","enableFloat","enableRvv"):
            with self.assertRaises(ValueError):audit.checked_header(text.replace("KP_"+name+" "+expected[name],"KP_"+name+" invalid"))

    def test_generated_build_and_all_python_sources_parse(self):
        import ast
        tree=ast.parse(prepare.build_text())
        for path in HERE.glob("*.py"):ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
        self.assertNotIn("chisel_cc_library",prepare.build_text()) # Reuse original model, not another elaboration.
        call=next(node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
                  and node.func.id=="cocotb_test_suite")
        cases=ast.literal_eval(next(keyword.value for keyword in call.keywords if keyword.arg=="testcases"))
        self.assertEqual(cases,["tx_"+case[0]+"_test" for case in spec.CASES])

    def test_native_cc_test_has_no_hdrs_and_declares_header_in_srcs(self):
        import ast
        tree=ast.parse(prepare.build_text())
        host=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="cc_test")
        attributes={kw.arg:ast.literal_eval(kw.value) for kw in host.keywords}
        self.assertNotIn("hdrs",attributes)
        self.assertIn("kernels.h",attributes["srcs"])
        self.assertEqual(set(attributes),{"name","srcs","copts"})
        # The custom firmware rule DOES accept hdrs; leave its recipe intact.
        firmware=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="coralnpu_v2_binary")
        self.assertEqual(ast.literal_eval(next(k.value for k in firmware.keywords if k.arg=="hdrs")),["kernels.h"])

    def test_explicit_known_build_repair_backups_and_is_idempotent(self):
        import repair_host_build as repair
        files={"rvv_matmul.cc":b"official", "bench.cc":b"unchanged benchmark", "BUILD":prepare.build_text().encode()}
        old_files=dict(files,BUILD=files["BUILD"].replace(repair.NEW,repair.OLD))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/"source";root.mkdir()
            legacy=prepare.install(root,old_files);legacy["generator_sha256"]=repair.LEGACY_GENERATOR_SHA
            marker=root/prepare.MANIFEST;marker.write_text(json.dumps(legacy))
            repair.repair(root,files)
            self.assertEqual((root/spec.PACKAGE/"BUILD").read_bytes(),files["BUILD"])
            self.assertEqual((root/spec.PACKAGE/"bench.cc").read_bytes(),files["bench.cc"])
            backup=next(Path(temporary).glob("llm_tx_host_hdrs_repair.*"))
            self.assertEqual((backup/"BUILD.before").read_bytes(),old_files["BUILD"])
            self.assertEqual(json.loads((backup/"manifest.before.json").read_text()),legacy)
            after=marker.read_bytes();repair.repair(root,files);self.assertEqual(marker.read_bytes(),after)
            self.assertEqual(len(list(Path(temporary).glob("llm_tx_host_hdrs_repair.*"))),1)

    def test_repair_refuses_unknown_manifest_or_user_edit_without_overwrite(self):
        import repair_host_build as repair
        files={"rvv_matmul.cc":b"official","bench.cc":b"bench","BUILD":prepare.build_text().encode()}
        old_files=dict(files,BUILD=files["BUILD"].replace(repair.NEW,repair.OLD))
        for edit in ("manifest","bench.cc","BUILD"):
            with self.subTest(edit=edit),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)/"source";root.mkdir()
                m=prepare.install(root,old_files);m["generator_sha256"]=repair.LEGACY_GENERATOR_SHA
                if edit=="manifest":m["generator_sha256"]="unknown"
                marker=root/prepare.MANIFEST;marker.write_text(json.dumps(m))
                if edit!="manifest":(root/spec.PACKAGE/edit).write_bytes(b"user change")
                before={p:p.read_bytes() for p in root.rglob("*") if p.is_file()}
                with self.assertRaises(ValueError):repair.repair(root,files)
                self.assertEqual(before,{p:p.read_bytes() for p in root.rglob("*") if p.is_file()})
                self.assertFalse(list(Path(temporary).glob("llm_tx_host_hdrs_repair.*")))

    def test_repair_can_complete_interrupted_build_before_manifest_update(self):
        import repair_host_build as repair
        files={"rvv_matmul.cc":b"official","BUILD":prepare.build_text().encode()}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/"source";root.mkdir()
            old_files=dict(files,BUILD=files["BUILD"].replace(repair.NEW,repair.OLD))
            m=prepare.install(root,old_files);m["generator_sha256"]=repair.LEGACY_GENERATOR_SHA
            (root/prepare.MANIFEST).write_text(json.dumps(m))
            (root/spec.PACKAGE/"BUILD").write_bytes(files["BUILD"])
            repair.repair(root,files);self.assertEqual(json.loads((root/prepare.MANIFEST).read_text()),prepare.install(root,files))

    def test_repair_accepts_manifest_from_actual_committed_legacy_generator(self):
        import repair_host_build as repair
        import importlib.util
        repo=HERE.parent.parent.parent
        raw=subprocess.check_output(["git","-C",str(repo),"show",
            "7bb95c5:verification/google_llm_ops/transformer/tx_prepare.py"])
        self.assertEqual(prepare.digest(raw),repair.LEGACY_GENERATOR_SHA)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/"source";root.mkdir();path=Path(temporary)/"old_prepare.py";path.write_bytes(raw)
            ms=importlib.util.spec_from_file_location("_actual_legacy_tx",path)
            old=importlib.util.module_from_spec(ms);ms.loader.exec_module(old)
            files={"rvv_matmul.cc":b"official", "bench.cc":b"bench", "BUILD":prepare.build_text().encode()}
            previous=old.install(root,dict(files,BUILD=old.build_text().encode()))
            repair.repair(root,files)
            now=json.loads((root/prepare.MANIFEST).read_text())
            changed={k for k in now if now[k]!=previous[k]}
            self.assertEqual(changed,{"generator_sha256","files"})
            self.assertEqual({n for n in now['files'] if now['files'][n]!=previous['files'][n]},
                {spec.PACKAGE+'/BUILD'})

    def test_synthetic_prepare_only_then_resume_driver_full_21_plan(self):
        # Driver control-flow test ONLY: no compiler, firmware or simulator here.
        import suite
        import types
        import sys
        import contextlib
        import io
        fake_fcntl=types.SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *args:None)
        with tempfile.TemporaryDirectory() as directory:
            study=Path(directory);(study/"source").mkdir()
            def fake_prepare(argv,cwd,log,timeout=7200):
                prep=Path(tempfile.mkdtemp(prefix="llm_tx_prepare.",dir=study))
                for n in ("probe_program.elf","resources.json","rtl-identity.json"):(prep/n).write_bytes(b"synthetic")
                log.write_text("[LLM_TX_BUILD_READY] RTL=NOT_RUN results="+str(prep)+"\n")
                return 0.0
            def fake_case(job,state,family,index):
                return dict(family=family,index=index,status="PASS",run=str(job),test_log_sha256="fake",
                    comparison=dict(case=family+str(index),scalar_cycles=[100]*4,rvv_cycles=[50]*4,steady_scalar_over_rvv=2.0))
            output=io.StringIO()
            with patch.dict(sys.modules,{"fcntl":fake_fcntl}),patch.object(suite,"preflight"),\
                 patch.object(suite,"run_process",side_effect=fake_prepare),patch.object(suite,"execute_case",side_effect=fake_case),\
                 patch.object(suite,"accepted",side_effect=lambda record:record["comparison"]),contextlib.redirect_stdout(output):
                with patch.object(sys,"argv",["suite.py","--study",str(study),"--prepare-only"]):self.assertEqual(suite.main(),0)
                jobs=list(study.glob("llm_suite.*"));self.assertEqual(len(jobs),1);job=jobs[0]
                state=json.loads((job/"state.json").read_text());self.assertEqual(state["status"],"BUILD_READY")
                self.assertEqual(state["cases"],{})
                with patch.object(sys,"argv",["suite.py","--study",str(study),"--resume",str(job)]):self.assertEqual(suite.main(),0)
            state=json.loads((job/"state.json").read_text());self.assertEqual(state["status"],"ALL_PASS")
            self.assertEqual(len(state["cases"]),21);self.assertNotIn("active_case",state)
            self.assertEqual(json.loads((job/"summary.json").read_text())["passed"],21)
            self.assertIn("[LLM_SUITE_ALL_PASS] cases=21",output.getvalue())


if __name__=="__main__":unittest.main()
