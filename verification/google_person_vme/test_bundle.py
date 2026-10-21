"""Synthetic package/RTL-probe acceptance tests. NO actual RTL execution."""
import importlib.util
import json
from pathlib import Path
import tempfile
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
import portable_vme
import server_probe
import export_bundle
import probe_audit


class BundleChecks(unittest.TestCase):
    def test_pinned_generic_runtime_imports_without_workset_execution(self):
        base=server_probe.runtime()
        common=base.helpers()
        self.assertEqual(common.sha(common.__file__),base.COMMON_SHA)
        self.assertEqual(base.VERSIONS["cocotb"],"2.0.0")
        path=Path(tempfile.gettempdir())/"synthetic_vme_package"
        self.assertEqual(common.state_directory(path).name,"synthetic_vme_package_verilator_runtime")

    def test_probe_elf_audit_rejects_out_of_range_diagnostics(self):
        class Symbol(dict):
            def __init__(self,name,address,size=4):
                super().__init__(st_value=address,st_size=size,st_shndx=2);self.name=name
        symbols=[Symbol(n,0x01000000+i*4) for i,n in enumerate(probe_audit.PROBE_SYMBOLS)]
        symbols += [Symbol("__heap_start__",0x01010000,0),Symbol("__heap_end__",0x0107c000,0),
                    Symbol("__stack_start__",0x0107c000,0),Symbol("__stack_end__",0x01080000,0)]
        segment=dict(p_type="PT_LOAD",p_memsz=256,p_filesz=256,p_paddr=0,p_vaddr=0,p_flags=5)
        data_segment=dict(p_type="PT_LOAD",p_memsz=65536,p_filesz=0,p_paddr=0x01000000,p_vaddr=0x01000000,p_flags=6)
        elf=SimpleNamespace(elfclass=32,little_endian=True,header=dict(e_machine="EM_RISCV",e_entry=0),
            iter_segments=lambda:[segment,data_segment],get_section_by_name=lambda _:SimpleNamespace(iter_symbols=lambda:symbols))
        with patch.object(probe_audit,"ELFFile",return_value=elf):
            self.assertEqual(probe_audit.inspect(b"synthetic")["scope"],"short_VME_arithmetic_not_model_inference")
            symbols[0]["st_value"]=0
            with self.assertRaisesRegex(ValueError,"diagnostic outside"):probe_audit.inspect(b"synthetic")

    def test_complete_synthetic_export_preserves_baseline_and_packages_three_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory);root=parent/"source";root.mkdir()
            baseline=parent/"baseline";baseline.mkdir();run=parent/"run";run.mkdir();job=parent/"job";job.mkdir()
            def put(base,name,data):
                path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            for name in ("rtl","rtl_dependencies","original","dpi","python","assets","inputs"):
                (baseline/name).mkdir()
            put(baseline,"rtl/"+portable_vme.TOP+".sv",b"synthetic RTL, NOT SIMULATION")
            put(baseline,"assets/person_detect.tflite",b"synthetic model")
            for case in ("person","no_person"):put(baseline,"inputs/"+case+".int8.bin",bytes(9216))
            for name in ("LICENSE","SOURCE-NOTICES.txt","spec.py","firmware_report.py"):
                put(baseline,name,b"synthetic fixture")
            base_manifest=dict(upstream=portable_vme.UPSTREAM,hdl_top=portable_vme.TOP,itcm_kib=256,dtcm_kib=512,
                defines=["USE_GENERIC","ZVT_ON"],zip_include_dirs=["."],
                rtl_sha256=portable_vme.sha(baseline/"rtl"/(portable_vme.TOP+".sv")),
                model_sha256=portable_vme.sha(baseline/"assets/person_detect.tflite"),
                memory_map=dict(itcm=0,dtcm=0x01000000,csr=0x02000000,external=0x20000000),
                reference_scores_no_person_then_person={"person":[-113,113],"no_person":[57,-57]})
            base_manifest["files"]=portable_vme.inventory(baseline)
            put(baseline,"manifest.json",json.dumps(base_manifest).encode())
            reports={}
            for mode in ("validate","fast"):
                put(run,mode+"/person_program.elf",("synthetic "+mode+" ELF").encode())
                reports[mode]=dict(elf_sha256=portable_vme.sha(run/mode/"person_program.elf"),NPU_RTL="NOT_RUN")
            for name in ("manifest.json","host-test.log","validate-build.log","fast-build.log"):
                put(run,name,b"synthetic evidence, NOT a real PASS")
            identity={"files":{}}
            for name in ("pointwise_core.h","vme_tile.h"):
                relative=export_bundle.candidate.PACKAGE+"/"+name
                put(root,relative,(HERE/name).read_bytes());identity["files"][relative]=portable_vme.sha(root/relative)
            put(root,export_bundle.candidate.MANIFEST,json.dumps(identity).encode())
            put(job,"execution-root.txt",(str(root.resolve())+"\n").encode())
            put(root,"bazel-out/test/probe_program.elf",b"synthetic probe ELF")
            put(job,"probe-outputs.txt",b"bazel-out/test/probe_program.elf\n")
            put(job,"probe-build.log",b"synthetic build, NOT an actual link")
            base=SimpleNamespace(root=baseline,manifest=base_manifest,library=SimpleNamespace(verify=lambda _:None))
            before=portable_vme.inventory(baseline)
            probe_report=dict(elf_sha256=portable_vme.sha(root/"bazel-out/test/probe_program.elf"),NPU_RTL="NOT_RUN")
            with patch.object(export_bundle,"evidence",return_value=(identity,{},reports,base)), \
                    patch.object(export_bundle.probe_audit,"inspect",return_value=probe_report), \
                    patch.object(portable_vme,"MODEL_SHA",base_manifest["model_sha256"]):
                export_bundle.export(root,parent,run,baseline,job)
                package=job/"coral_person_vme_i256_d512_v1"
                self.assertEqual(set(portable_vme.verify(package)["firmwares"]),{"probe","validate","fast"})
                self.assertEqual(portable_vme.inventory(baseline),before)
                self.assertEqual((root/export_bundle.candidate.MANIFEST).read_bytes(),json.dumps(identity).encode())
                archive=job/(package.name+".tar.gz")
                with tarfile.open(archive) as stream:
                    names=stream.getnames()
                    self.assertIn(package.name+"/server_probe.py",names)
                    self.assertIn(package.name+"/firmware/fast/person_program.elf",names)

    def test_host_layer_evidence_requires_both_exact_cases_and_one_completion(self):
        lines=("[PERSON_VME_HOST_MODEL_CASE] case=person layers=14 byte_exact=true scores=-113,113\n"
               "[PERSON_VME_HOST_MODEL_CASE] case=no_person layers=14 byte_exact=true scores=57,-57\n"
               "[PERSON_VME_HOST_MODEL_PASS] cases=2 compared_layers=28 arena_used=122000 hardware=NOT_RUN\n")
        self.assertEqual(export_bundle.checked_host(lines)["arena_used_bytes"],122000)
        for text in (lines*2,lines.replace("-113,113","113,-113"),lines.replace("122000","0"),
                     lines+"FAILED\n",lines.replace("case=no_person","case=other")):
            with self.assertRaises(ValueError): export_bundle.checked_host(text)

    def test_probe_source_is_separate_and_same_measured_core(self):
        files=export_bundle.probe_files()
        self.assertNotEqual(export_bundle.PROBE_PACKAGE,export_bundle.candidate.PACKAGE)
        for name in ("pointwise_core.h","vme_tile.h"):
            self.assertEqual(files[export_bundle.PROBE_PACKAGE+"/"+name],(HERE/name).read_bytes())

    def test_probe_acceptance_never_accepts_partial_model_or_bad_arithmetic(self):
        with tempfile.TemporaryDirectory() as directory:
            xml=Path(directory)/"results.xml"
            xml.write_text('<testsuites><testsuite><testcase name="person_vme_probe_test"/></testsuite></testsuites>')
            bundle=SimpleNamespace(manifest={"firmwares":{"probe":{"sha256":"a"*64}},"rtl_sha256":"b"*64})
            row=dict(schema=1,scope="short_VME_arithmetic_not_model_inference",fault=False,natural_halt=True,
                firmware_status=3,requested_cycles=2000000,itcm_kib=256,dtcm_kib=512,
                elf_sha256="a"*64,rtl_sha256="b"*64,stack_low_canary_intact=True,cases=8,checked=840,
                mismatches=0,commands=233,signature=3016346044,observation_elapsed_cycles=150000)
            check=lambda r:server_probe.checked_results(server_probe.MARKER+json.dumps(r),xml,bundle,2000000)
            self.assertEqual(check(row),row)
            for change in (dict(natural_halt=False),dict(fault=True),dict(mismatches=1),dict(checked=839),
                           dict(commands=0),dict(signature=0),dict(firmware_status=2),dict(firmware_status=True),
                           dict(elf_sha256="c"*64),dict(observation_elapsed_cycles=2000002),
                           dict(scope="model_inference"),dict(stack_low_canary_intact=False)):
                with self.subTest(change=change),self.assertRaises(ValueError): check(dict(row,**change))
            xml.write_text('<testsuites><testcase name="person_vme_probe_test"><failure/></testcase></testsuites>')
            with self.assertRaises(ValueError): check(row)

    def test_package_inventory_detects_tampering_and_all_variant_elves(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def put(name,data):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            put("rtl/"+portable_vme.TOP+".sv",b"synthetic RTL, not simulation")
            put("assets/person_detect.tflite",b"synthetic model")
            for c in ("person","no_person"): put("inputs/"+c+".int8.bin",bytes(9216))
            variants={}
            for v in ("probe","validate","fast"):
                name="firmware/"+v+"/person_program.elf";put(name,v.encode())
                variants[v]=dict(file=name,sha256=portable_vme.sha(root/name))
            model=portable_vme.sha(root/"assets/person_detect.tflite")
            m=dict(schema=1,kind="person_vme_bundle_v1",upstream=portable_vme.UPSTREAM,
                hdl_top=portable_vme.TOP,itcm_kib=256,dtcm_kib=512,model_sha256=model,simulation="NOT_RUN",
                reference_scores_no_person_then_person={"person":[-113,113],"no_person":[57,-57]},
                memory_map=dict(itcm=0,dtcm=0x01000000,csr=0x02000000,external=0x20000000),
                probe_expected=dict(cases=8,checked=840,commands=233,signature=3016346044),
                rtl_sha256=portable_vme.sha(root/"rtl"/(portable_vme.TOP+".sv")),firmwares=variants,
                input_sha256={c:portable_vme.sha(root/"inputs"/(c+".int8.bin")) for c in ("person","no_person")},
                files=portable_vme.inventory(root))
            put("manifest.json",json.dumps(m).encode())
            checks=dict(m["files"],**{"manifest.json":portable_vme.sha(root/"manifest.json")})
            put("SHA256SUMS",''.join(h+"  "+n+"\n" for n,h in checks.items()).encode())
            with patch.object(portable_vme,"MODEL_SHA",model):
                self.assertEqual(portable_vme.verify(root),m)
                put("firmware/fast/person_program.elf",b"changed")
                with self.assertRaisesRegex(ValueError,"files missing/extra/changed"): portable_vme.verify(root)


if __name__=="__main__": unittest.main()
