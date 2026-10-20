"""Launcher/acceptance tests; no Verilator model compilation or NPU simulation."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import person_runner as runner


class RunnerChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "inputs").mkdir()
        (self.root / "inputs/person.int8.bin").write_bytes(bytes(9216))
        self.bundle = SimpleNamespace(root=self.root, manifest=dict(elf_sha256="a" * 64, model_sha256="b" * 64,
                         hdl_top="VmeCoreMini_ITCM256KB_DTCM512KBAxi", defines=["USE_GENERIC", "ZVT_ON"],
                         zip_include_dirs=["."], reference_scores_no_person_then_person={"person": [-113, 113]}))
        self.xml = self.root / "results.xml"
        self.xml.write_text('<testsuites><testsuite><testcase name="person_model_test"/></testsuite></testsuites>')
        self.row = dict(schema=1, case="person", mode="smoke", requested_cycles=200000, fault=False,
                        itcm_kib=256, dtcm_kib=512, elf_sha256="a" * 64, model_sha256="b" * 64,
                        input_sha256=runner.sha(self.root / "inputs/person.int8.bin"),
                        model_readback_equal=True, input_readback_equal=True, stack_low_canary_intact=True,
                        firmware_status=1, arena_used_bytes=0, inference_complete=False, natural_halt=False,
                        observation_elapsed_cycles=200000, kernel_backend="pinned_TFLM_INT8_not_VME_offload")

    def check(self, row=None, mode="smoke", suffix=""):
        return runner.checked_results(runner.MARKER + json.dumps(self.row if row is None else row) + suffix,
                                      self.xml, self.bundle, "person", mode, 200000)

    def test_partial_window_is_observation_not_inference(self):
        row = self.check()
        self.assertFalse(row["inference_complete"])
        self.assertEqual(row["firmware_status"], 1)
        row = dict(self.row, firmware_status=0)
        self.assertFalse(self.check(row)["inference_complete"])  # Still CRT, no startup PASS claim.

    def test_fault_arena_stack_premature_halt_and_identity_rejected(self):
        for update in (dict(fault=True), dict(arena_used_bytes=163841), dict(stack_low_canary_intact=False),
                       dict(firmware_status=103), dict(firmware_status=2), dict(firmware_status=3),
                       dict(natural_halt=True), dict(elf_sha256="c" * 64), dict(inference_complete=1),
                       dict(observation_elapsed_cycles=12)):
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.check(dict(self.row, **update))

    def test_complete_inference_requires_exact_scores_and_halt(self):
        complete = dict(self.row, firmware_status=3, arena_used_bytes=136000, invoke_cycles=12345,
                        natural_halt=True, inference_complete=True, scores_no_person_then_person=[-113, 113],
                        observation_elapsed_cycles=190000)
        self.assertTrue(self.check(complete)["inference_complete"])
        pending_return = dict(complete, natural_halt=False, inference_complete=False,
                              observation_elapsed_cycles=200000)
        self.assertFalse(self.check(pending_return)["inference_complete"])
        for update in (dict(scores_no_person_then_person=[113, -113]), dict(natural_halt=False),
                       dict(invoke_cycles=0), dict(firmware_status=2)):
            with self.assertRaises(ValueError):
                self.check(dict(complete, **update))
        complete["mode"] = "infer"
        self.assertTrue(self.check(complete, mode="infer")["inference_complete"])
        with self.assertRaises(ValueError):
            self.check(dict(self.row, mode="infer"), mode="infer")

    def test_xml_and_json_failures_rejected(self):
        with self.assertRaises(ValueError):
            self.check(suffix="\x1b[0m")  # Never silently repair structured data.
        with self.assertRaises(ValueError):
            runner.checked_results("", self.xml, self.bundle, "person", "smoke", 200000)
        for text in ('<testsuites><testcase name="person_model_test"><failure/></testcase></testsuites>',
                     '<testsuites><testcase name="person_model_test"><skipped/></testcase></testsuites>',
                     '<testsuites><testcase name="wrong"/></testsuites>'):
            self.xml.write_text(text)
            with self.assertRaises(ValueError):
                self.check()

    def test_child_clears_wave_profile_overrides_and_uses_new_bench(self):
        env = dict(libpython="/conda/lib/libpython3.11.so", libs="/conda/cocotb/libs",
                   tools=dict(cc="/conda/bin/gcc", cxx="/conda/bin/g++"))
        with patch.dict(os.environ, {"WAVES": "0", "GUI": "0", "COCOTB_ENABLE_PROFILING": "0",
                                     "COCOTB_TEST_MODULES": "workset_bench", "COCOTB_TIMEOUT_CYCLES": "1"}):
            child = runner.child_environment(self.bundle, env)
        for name in ("WAVES", "GUI", "COCOTB_ENABLE_PROFILING", "COCOTB_TIMEOUT_CYCLES", "COCOTB_TEST_MODULES"):
            self.assertNotIn(name, child)
        self.assertEqual(child["COCOTB_USE_FRONTDOOR"], "1")
        self.assertEqual(child["COCOTB_TRUST_INERTIAL_WRITES"], "0")
        self.assertEqual(child["CC"], "/conda/bin/gcc")
        self.assertNotEqual(child["PERSON_PACKAGE"], child["PYTHONPATH"])

    def test_qualified_helper_and_original_package_utilities_pinned(self):
        common = runner.helpers()
        for name, digest in runner.PACKAGE_TOOLS.items():
            self.assertEqual(runner.sha(Path(runner.__file__).parent / name), digest)
        self.assertEqual(runner.sha(Path(common.__file__)), runner.COMMON_SHA)
        env = dict(cpp="/cocotb/share/verilator.cpp", libs="/cocotb/libs",
                   tools={n: "/conda/bin/" + n for n in ("perl", "verilator", "make", "cc", "cxx", "ar")})
        commands = common.build_commands(self.bundle, env, self.root, 2)
        self.assertIn(str(self.bundle.root / "dpi/sram_backdoor.cc"), commands[0])
        self.assertNotIn("--trace", commands[0])
        self.assertIn("OPT_FAST=-O3", commands[1])
        self.assertEqual(commands[0].count(str(self.bundle.root / "rtl" / (self.bundle.manifest["hdl_top"] + ".sv"))), 1)

    def test_bundle_loader_reaudits_original_model_in_synthetic_elf(self):
        import export_person
        import firmware_report
        import spec
        from test_person import synthetic_elf
        assets = Path(runner.__file__).resolve().parents[2] / ".upstream-git/model-cache/person_detect_b75c6ff4"
        if not (assets / spec.MODEL_NAME).exists():
            self.skipTest("Pinned model assets not downloaded")
        root = self.root / "bundle"
        for name in ("assets", "inputs", "evidence", "firmware", "rtl"):
            (root / name).mkdir(parents=True)
        elf = synthetic_elf(model=spec.checked_asset(assets, spec.MODEL_NAME))
        (root / "firmware/person_program.elf").write_bytes(elf)
        report = firmware_report.inspect_elf(elf)
        (root / "evidence/resources.json").write_text(json.dumps(report))
        for name in spec.ASSETS:
            data = spec.checked_asset(assets, name)
            (root / "assets" / name).write_bytes(data)
            if name.endswith(".bmp"):
                (root / "inputs" / (Path(name).stem + ".int8.bin")).write_bytes(export_person.fixture_bytes(data))
        for name in runner.PACKAGE_TOOLS:
            shutil.copy2(Path(runner.__file__).parent / name, root / name)
        rtl = root / "rtl" / (export_person.TOP + ".sv")
        rtl.write_bytes(b"SYNTHETIC NOT GENERATED RTL")
        export_person.seal(root, dict(schema=1, upstream=spec.UPSTREAM, hdl_top=export_person.TOP,
            itcm_kib=256, dtcm_kib=512, validation="export_integrity_only_NOT_NPU_RTL_PASS",
            model_sha256=spec.MODEL_SHA256, elf_sha256=report["elf_sha256"], rtl_sha256=runner.sha(rtl),
            memory_map=dict(itcm=0, dtcm=spec.DTCM_BASE, csr=0x02000000, external=0x20000000)))
        paths = list(sys.path)
        try:
            with patch.dict(sys.modules):
                bundle = runner.load_bundle(root)
                self.assertEqual(bundle.report, report)
                (root / "inputs/person.int8.bin").write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    runner.load_bundle(root)
        finally:
            sys.path[:] = paths


if __name__ == "__main__":
    unittest.main()
