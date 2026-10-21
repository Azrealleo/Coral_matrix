"""Synthetic complete-model acceptance/reuse tests, NOT RTL inference."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import model_runner as runner
import export_pool


class ModelChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.package=self.root/"package";self.package.mkdir()
        (self.package/"inputs").mkdir()
        for case in ("person","no_person"):(self.package/"inputs"/(case+".int8.bin")).write_bytes(case.encode())
        self.bundle=SimpleNamespace(root=self.package,manifest=dict(
            firmwares={n:{"sha256":h} for n,h in runner.FIRMWARE_SHA.items()},
            model_sha256="m"*64,rtl_sha256="r"*64,hdl_top="synthetic_top",
            reference_scores_no_person_then_person={"person":[-113,113],"no_person":[57,-57]}))
        (self.package/"manifest.json").write_text(json.dumps(self.bundle.manifest))
        self.xml=self.root/"results.xml"
        self.xml.write_text('<testsuites><testcase name="person_pool_model_test"/></testsuites>')
        self.row=dict(schema=1,variant="validate",case="person",scope="complete_original_model_single_image",
            requested_cycles=400000000,itcm_kib=256,dtcm_kib=512,fault=False,natural_halt=True,
            firmware_status=3,inference_complete=True,model_readback_equal=True,input_readback_equal=True,
            stack_low_canary_intact=True,elf_sha256=runner.FIRMWARE_SHA["validate"],
            model_sha256="m"*64,rtl_sha256="r"*64,input_sha256=runner.sha(self.package/"inputs/person.int8.bin"),
            kernel_backend=runner.BACKEND,depthwise="official_default_registration_unchanged",
            validation_executes_reference=True,performance_eligible=False,
            scores_no_person_then_person=[-113,113],arena_used_bytes=122256,
            invoke_cycles=210000000,observation_elapsed_cycles=214000000,
            counters=dict(pd_vme_conv_calls=14,pd_vme_fallback_calls=0,pd_vme_mismatches=0,pd_pool_calls=1,
                pd_pool_fallbacks=0,pd_pool_mismatches=0,pd_pool_vector_blocks=16,pd_vme_commands=100,
                pd_vme_validated_layers=14,pd_pool_validated=1,pd_vme_first_bad_index=0xffffffff))

    def check(self,row=None,variant="validate",case="person"):
        value=self.row if row is None else row
        return runner.checked_results(runner.MARKER+json.dumps(value),self.xml,self.bundle,variant,case,400000000)

    def test_full_validation_requires_every_byte_comparison_gates(self):
        self.assertEqual(self.check(),self.row)
        for changes in (dict(fault=True),dict(natural_halt=False),dict(inference_complete=False),
                        dict(firmware_status=2),dict(firmware_status=True),dict(arena_used_bytes=0),
                        dict(arena_used_bytes=163841),dict(invoke_cycles=0),dict(observation_elapsed_cycles=200000000),
                        dict(scores_no_person_then_person=[113,-113]),dict(model_readback_equal=False),
                        dict(stack_low_canary_intact=False),dict(elf_sha256="a"*64),dict(performance_eligible=True)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.check(dict(self.row,**changes))
        for n,v in ( ("pd_vme_conv_calls",13),("pd_vme_fallback_calls",1),("pd_vme_mismatches",1),
                     ("pd_pool_vector_blocks",0),("pd_pool_vector_blocks",15),("pd_vme_commands",0),
                     ("pd_pool_validated",0),("pd_vme_validated_layers",13),("pd_pool_calls",2),
                     ("pd_vme_first_bad_index",0)):
            bad=copy.deepcopy(self.row);bad["counters"][n]=v
            with self.subTest(counter=n),self.assertRaises(ValueError):self.check(bad)

    def test_fast_has_separate_elf_and_never_reference_validation_cycles(self):
        row=copy.deepcopy(self.row)
        row.update(variant="fast",elf_sha256=runner.FIRMWARE_SHA["fast"],validation_executes_reference=False,
            performance_eligible=True)
        for n in ("pd_vme_validated_layers","pd_pool_validated","pd_vme_first_bad_index"):row["counters"].pop(n)
        self.assertTrue(self.check(row,"fast")["performance_eligible"])
        row["counters"]["pd_pool_validated"]=1
        with self.assertRaises(ValueError):self.check(row,"fast")
        with self.assertRaises(ValueError):self.check(self.row,"fast")

    def test_wrong_image_and_xml_or_duplicate_records_fail(self):
        with self.assertRaises(ValueError):self.check(self.row,case="no_person")
        text=runner.MARKER+json.dumps(self.row)
        with self.assertRaises(ValueError):runner.checked_results(text+"\n"+text,self.xml,self.bundle,"validate","person",400000000)
        self.assertEqual(runner.json_row(text+"\x1b[49m\x1b[39m",runner.MARKER),self.row)
        with self.assertRaises(ValueError):runner.json_row(text+"garbage",runner.MARKER)
        self.xml.write_text('<testsuites><testcase name="person_pool_model_test"><failure/></testcase></testsuites>')
        with self.assertRaises(ValueError):self.check()

    def test_producer_hashes_exactly_match_sealed_pool_runtime(self):
        import hashlib
        files=export_pool.runtime_files()
        self.assertEqual(hashlib.sha256(files["server_probe.py"]).hexdigest(),runner.PRODUCER_SHA)
        self.assertEqual(hashlib.sha256(files["probe_bench.py"]).hexdigest(),runner.PROBE_BENCH_SHA)

    def test_validation_prerequisite_uses_raw_evidence_same_image_and_build(self):
        directory=Path(str(self.package)+"_model_runtime")/"runs/validate_person.synthetic";directory.mkdir(parents=True)
        (directory/"_test.log").write_text(runner.MARKER+json.dumps(self.row))
        (directory/"results.xml").write_bytes(self.xml.read_bytes());build={"identity":"original producer"}
        result=dict(observation=self.row,timing={"exit_code":0,"timed_out":False},producer_build=build,
            manifest_sha256=runner.sha(self.package/"manifest.json"),raw_log_sha256=runner.sha(directory/"_test.log"),
            xml_sha256=runner.sha(directory/"results.xml"))
        (directory/"result.json").write_text(json.dumps(result))
        before={p.name:runner.sha(p) for p in directory.iterdir()}
        self.assertEqual(runner.checked_validation(directory,self.bundle,"person",build)["observation"],self.row)
        self.assertEqual(before,{p.name:runner.sha(p) for p in directory.iterdir()})
        with self.assertRaises(ValueError):runner.checked_validation(directory,self.bundle,"no_person",build)
        with self.assertRaises(ValueError):runner.checked_validation(directory,self.bundle,"person",{"identity":"different"})
        (directory/"_test.log").write_text("changed")
        with self.assertRaises(ValueError):runner.checked_validation(directory,self.bundle,"person",build)

    def test_original_build_checked_without_relabel_or_file_writes(self):
        state=self.root/"producer_state";model=state/"builds/original";model.mkdir(parents=True)
        env={"tools":"synthetic","libc":("glibc","2.17")};recipe=[["synthetic verilator"],["make","-j","2","original recipe"]]
        (model/"environment.json").write_text(json.dumps(env))
        (model/"compile-commands.json").write_text(json.dumps(recipe))
        (model/"visibility.vlt").write_text("visibility synthetic_top")
        record=dict(directory=str(model),identity="original_identity",timing={"exit_code":0,"timed_out":False},
            model_files={"exe":"synthetic digest"})
        for p in (state/"current_build.json",model/"build-record.json"):p.write_text(json.dumps(record))
        common=SimpleNamespace(state_directory=lambda _:state,digest=lambda _:"original_identity",WARNINGS=[],
            VISIBILITY="visibility {top}",model_hashes=lambda *_:dict(record["model_files"]),
            build_commands=lambda *_,**kw:copy.deepcopy(recipe))
        before={str(p):runner.sha(p) for p in state.rglob("*") if p.is_file()}
        self.assertEqual(runner.checked_build(self.bundle,env,common),(record,model))
        self.assertEqual(before,{str(p):runner.sha(p) for p in state.rglob("*") if p.is_file()})
        with self.assertRaises(ValueError):runner.checked_build(self.bundle,{"tools":"changed"},common)
        (model/"visibility.vlt").write_text("changed visibility")
        with self.assertRaises(ValueError):runner.checked_build(self.bundle,env,common)

    def test_probe_prerequisite_is_from_same_package_and_record(self):
        state=self.root/"producer";directory=state/"runs/probe.synthetic";directory.mkdir(parents=True)
        row={"requested_cycles":2000000,"cases":8,"checked":659}
        build={"identity":"original"}
        (directory/"_test.log").write_text("synthetic probe raw")
        (directory/"results.xml").write_text("synthetic XML")
        result=dict(timing={"exit_code":0,"timed_out":False},observation=row,build=build,
            manifest_sha256=runner.sha(self.package/"manifest.json"),raw_log_sha256=runner.sha(directory/"_test.log"),
            xml_sha256=runner.sha(directory/"results.xml"))
        (directory/"result.json").write_text(json.dumps(result))
        common=SimpleNamespace(state_directory=lambda _:state)
        producer=SimpleNamespace(checked_results=lambda *_:dict(row))
        self.assertEqual(runner.checked_probe(directory,producer,self.bundle,build,common)["observation"],row)
        with self.assertRaises(ValueError):runner.checked_probe(directory,producer,self.bundle,{"identity":"other"},common)
        result["timing"]["timed_out"]=True;(directory/"result.json").write_text(json.dumps(result))
        with self.assertRaises(ValueError):runner.checked_probe(directory,producer,self.bundle,build,common)


if __name__=="__main__":unittest.main()
