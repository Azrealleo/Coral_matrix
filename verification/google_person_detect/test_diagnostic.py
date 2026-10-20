"""Local diagnostic contract tests, not a DM/RTL execution result."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import diagnose_person as diag


class DiagnosticChecks(unittest.TestCase):
    def test_symbol_ranges_do_not_turn_nearest_into_evidence(self):
        table = [(100, 20, "function_a"), (200, 16, "function_b")]
        self.assertEqual(diag.symbolize(table, 108)["symbol"], "function_a")
        self.assertEqual(diag.symbolize(table, 108)["offset"], 8)
        self.assertFalse(diag.symbolize(table, 120)["contains_address"])
        self.assertNotIn("symbol", diag.symbolize(table, 120))
        self.assertFalse(diag.symbolize(table, 0)["contains_address"])

    def test_original_runner_and_bench_are_unchanged(self):
        base = diag.base_tools()
        self.assertEqual(diag.sha(Path(base.__file__)), diag.BASE_SHA)
        self.assertEqual(diag.sha(Path(base.__file__).with_name("person_bench.py")), diag.BENCH_SHA)

    def test_capture_is_diagnostic_not_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            xml = Path(directory) / "results.xml"
            xml.write_text('<testsuites><testcase name="person_diagnostic_test"/></testsuites>')
            bundle = SimpleNamespace(manifest=dict(elf_sha256="a" * 64))
            rows = [dict(schema=1, sample=i, initial_window_cycles=200000, elf_sha256="a" * 64,
                         scope="intrusive_DM_debug_NOT_inference_or_performance", firmware_changed=False,
                         core_reset_before_capture=False, registers=dict(dpc=128), dcsr_cause=3,
                         fault_before_pause=False, natural_halt_before_pause=False) for i in range(3)]
            text = lambda r: "\n".join(diag.MARKER + json.dumps(row) for row in r)
            self.assertEqual(diag.checked_capture(text(rows), xml, bundle, 200000, 3), rows)
            for key, value in (("core_reset_before_capture", True), ("firmware_changed", True),
                               ("elf_sha256", "b" * 64), ("dcsr_cause", 0), ("registers", {})):
                bad = copy.deepcopy(rows)
                bad[1][key] = value
                with self.assertRaises(ValueError):
                    diag.checked_capture(text(bad), xml, bundle, 200000, 3)
            with self.assertRaises(ValueError):
                diag.checked_capture(text(rows[:1]), xml, bundle, 200000, 3)
            fault = copy.deepcopy(rows[:1])
            fault[0]["fault_before_pause"] = True
            self.assertEqual(len(diag.checked_capture(text(fault), xml, bundle, 200000, 3)), 1)
            xml.write_text('<testsuites><testcase name="person_diagnostic_test"><failure/></testcase></testsuites>')
            with self.assertRaises(ValueError):
                diag.checked_capture(text(rows), xml, bundle, 200000, 3)

    def test_existing_model_reuse_requires_full_original_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory).resolve()
            model = state / "builds/model"
            model.mkdir(parents=True)
            record = dict(directory=str(model), identity="same", model_files={"executable": "digest"},
                          timing=dict(exit_code=0, timed_out=False))
            pointer = state / "current_build.json"
            pointer.write_text(json.dumps(record))
            (model / "build-record.json").write_text(json.dumps(record))
            base = SimpleNamespace(identity=lambda *a: "same")
            common = SimpleNamespace(model_hashes=lambda *a: {"executable": "digest"})
            self.assertEqual(diag.checked_build(base, common, None, None, state), (record, model))
            for key, value in (("identity", "different"), ("model_files", {"executable": "changed"}),
                               ("timing", dict(exit_code=1, timed_out=False))):
                bad = dict(record, **{key: value})
                pointer.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    diag.checked_build(base, common, None, None, state)

    def test_diagnostic_does_not_reset_core_before_pc_capture(self):
        text = Path(diag.__file__).with_name("person_diag_bench.py").read_text()
        self.assertIn("dm_request_halt()", text)
        self.assertIn("dm_read_reg(address)", text)
        self.assertIn('("dpc", 0x7B1)', text)
        self.assertNotIn("core.halt()", text)
        self.assertNotIn("fixture.core_mini_axi.halt()", text)
        self.assertIn("dm_request_resume()", text)


if __name__ == "__main__":
    unittest.main()
