"""Synthetic packaging and strict probe-acceptance tests, NOT RTL execution."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import export_pool as exporter
import portable_pool
import portable_vme


def generated_server():
    code=exporter.runtime_files()["server_probe.py"]
    module=SimpleNamespace(__file__=str(exporter.HERE/"_synthetic_server_probe.py"),__name__="synthetic_pool_server")
    exec(compile(code,module.__file__,"exec"),module.__dict__)
    return module


class PoolBundleTests(unittest.TestCase):
    def test_host_evidence_requires_pool_and_conv_both_images_and_core(self):
        text=("[PERSON_POOL_CORE_HOST_PASS] cases=2160 checked=1291923 rounding_counts=49 RVV=NOT_RUN\n"
              "[PERSON_POOL_HOST_MODEL_CASE] case=person conv_layers=14 pool_layers=1 byte_exact=true scores=-113,113\n"
              "[PERSON_POOL_HOST_MODEL_CASE] case=no_person conv_layers=14 pool_layers=1 byte_exact=true scores=57,-57\n"
              "[PERSON_POOL_HOST_MODEL_PASS] cases=2 compared_layers=30 arena_used=122256 hardware=NOT_RUN\n")
        self.assertEqual(exporter.checked_host(text)["compared_layers"],30)
        for bad in (text*2,text.replace("1291923","1291922"),text.replace("pool_layers=1","pool_layers=0"),
                    text.replace("-113,113","113,-113"),text+"FAILED\n"):
            with self.assertRaises(ValueError):exporter.checked_host(bad)

    def test_runtime_is_new_pool_identity_and_never_full_inference_pass(self):
        files=exporter.runtime_files()
        server=files["server_probe.py"].decode();bench=files["probe_bench.py"].decode()
        self.assertIn("import portable_pool as portable_vme",server)
        self.assertIn("import pool_probe_audit as probe_audit",server)
        self.assertIn('root/"audit_pool.py"',server)
        self.assertNotIn("PERSON_VME",server+bench)
        self.assertNotIn("checked=840",server)
        self.assertIn("checked=659",server)
        self.assertIn("commands=62,signature=642806987",server)
        self.assertIn("full_model_inference=NOT_RUN",server)
        self.assertIn('from server_probe import load_bundle, MARKER',bench)
        self.assertIn("person_pool_probe_test",server+bench)
        compile(files["server_probe.py"],"server_probe.py","exec")
        compile(files["probe_bench.py"],"probe_bench.py","exec")

    def test_probe_acceptance_rejects_vme_record_and_partial_pool(self):
        server=generated_server()
        with tempfile.TemporaryDirectory() as directory:
            xml=Path(directory)/"results.xml"
            xml.write_text('<testsuites><testcase name="person_pool_probe_test"/></testsuites>')
            bundle=SimpleNamespace(manifest={"firmwares":{"probe":{"sha256":"a"*64}},"rtl_sha256":"b"*64})
            row=dict(schema=1,scope=portable_pool.SCOPE,fault=False,natural_halt=True,firmware_status=3,
                requested_cycles=2000000,itcm_kib=256,dtcm_kib=512,elf_sha256="a"*64,rtl_sha256="b"*64,
                stack_low_canary_intact=True,mismatches=0,observation_elapsed_cycles=100000,**portable_pool.EXPECTED)
            check=lambda r:server.checked_results(server.MARKER+json.dumps(r),xml,bundle,2000000)
            self.assertEqual(check(row),row)
            for change in (dict(scope="short_VME_arithmetic_not_model_inference"),dict(checked=840),
                           dict(commands=233),dict(signature=0),dict(mismatches=1),dict(fault=True),
                           dict(natural_halt=False),dict(firmware_status=2),dict(firmware_status=True),
                           dict(stack_low_canary_intact=False),dict(observation_elapsed_cycles=2000002)):
                with self.subTest(change=change),self.assertRaises(ValueError):check(dict(row,**change))
            with self.assertRaises(ValueError):server.checked_results(server.MARKER+json.dumps(row)+"\n"+
                server.MARKER+json.dumps(row),xml,bundle,2000000)
            xml.write_text('<testsuites><testcase name="person_pool_probe_test"><failure/></testcase></testsuites>')
            with self.assertRaises(ValueError):check(row)

    def test_probe_source_install_separate_and_refuses_changed_owned_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);marker=root/exporter.candidate.MANIFEST;marker.write_bytes(b"measured pool identity")
            identity={"files":{exporter.candidate.PACKAGE+"/"+n:portable_vme.sha(exporter.HERE/n)
                for n in ("pool_core.h","pool_rvv.h")}}
            before=marker.read_bytes()
            exporter.prepare_probe(root,identity);exporter.prepare_probe(root,identity)
            self.assertEqual(marker.read_bytes(),before)
            source=root/exporter.PROBE_PACKAGE/"hardware_probe.cc";source.write_bytes(b"user change")
            with self.assertRaisesRegex(ValueError,"nothing overwritten"):exporter.prepare_probe(root,identity)
            self.assertEqual(source.read_bytes(),b"user change")

    def test_complete_synthetic_export_integrity_and_old_parent_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            top=Path(directory);root=top/"source";root.mkdir();parent=top/"parent";parent.mkdir()
            run=top/"run";run.mkdir();job=top/"job";job.mkdir()
            def put(base,name,data):
                p=base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            for n in ("rtl","rtl_dependencies","original","dpi","python","assets","inputs"):(parent/n).mkdir()
            put(parent,"rtl/"+portable_vme.TOP+".sv",b"synthetic RTL, NOT a real model")
            put(parent,"assets/person_detect.tflite",b"synthetic model")
            for c in ("person","no_person"):put(parent,"inputs/"+c+".int8.bin",bytes(9216))
            for n in ("LICENSE","SOURCE-NOTICES.txt","VME-NOTICES.txt","spec.py","firmware_report.py",
                      "_baseline_runner.py","verilator_common.py","vme_audit.py","probe_audit.py","portable_vme.py"):
                put(parent,n,b"synthetic copied helper")
            m=dict(upstream=portable_vme.UPSTREAM,hdl_top=portable_vme.TOP,itcm_kib=256,dtcm_kib=512,
                defines=["USE_GENERIC","ZVT_ON"],zip_include_dirs=["."],
                rtl_sha256=portable_vme.sha(parent/"rtl"/(portable_vme.TOP+".sv")),
                model_sha256=portable_vme.sha(parent/"assets/person_detect.tflite"),
                memory_map=dict(itcm=0,dtcm=0x01000000,csr=0x02000000,external=0x20000000),
                reference_scores_no_person_then_person={"person":[-113,113],"no_person":[57,-57]},
                input_sha256={c:portable_vme.sha(parent/"inputs"/(c+".int8.bin")) for c in ("person","no_person")})
            m["files"]=portable_vme.inventory(parent);put(parent,"manifest.json",json.dumps(m).encode())
            identity={"files":{exporter.candidate.PACKAGE+"/"+n:portable_vme.sha(exporter.HERE/n)
                for n in ("pool_core.h","pool_rvv.h")}}
            for n in identity["files"]:put(root,n,(exporter.HERE/Path(n).name).read_bytes())
            put(root,exporter.candidate.MANIFEST,json.dumps(identity).encode())
            reports={}
            for mode in ("validate","fast"):
                put(run,mode+"/person_program.elf",("synthetic "+mode).encode())
                reports[mode]=dict(elf_sha256=portable_vme.sha(run/mode/"person_program.elf"))
            for n in ("manifest.json","host-test.log","validate-build.log","fast-build.log"):put(run,n,b"synthetic evidence")
            put(root,"bazel-out/test/probe_program.elf",b"synthetic probe")
            put(job,"execution-root.txt",(str(root.resolve())+"\n").encode())
            put(job,"probe-outputs.txt",b"bazel-out/test/probe_program.elf\n");put(job,"probe-build.log",b"synthetic link")
            probe_report=dict(elf_sha256=portable_vme.sha(root/"bazel-out/test/probe_program.elf"))
            before=portable_vme.inventory(parent)
            with patch.object(exporter,"evidence",return_value=(identity,{},reports,m)), \
                    patch.object(exporter.pool_probe_audit,"inspect",return_value=probe_report), \
                    patch.object(portable_vme,"MODEL_SHA",m["model_sha256"]):
                exporter.export(root,top,run,parent,job)
                pkg=job/"coral_person_vme_pool_i256_d512_v1"
                checked=portable_pool.verify(pkg)
                self.assertEqual(checked["probe_expected"],portable_pool.EXPECTED)
                self.assertEqual(portable_vme.inventory(parent),before)
                self.assertTrue((job/(pkg.name+".tar.gz.sha256")).is_file())
                (pkg/"firmware/fast/person_program.elf").write_bytes(b"replaced ELF")
                with self.assertRaisesRegex(ValueError,"changed package files"):portable_pool.verify(pkg)


if __name__=="__main__":unittest.main()
