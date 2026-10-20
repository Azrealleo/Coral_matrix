"""Local generator/identity tests; not native TFLM execution or NPU RTL."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("_person_vme_prepare", HERE / "prepare.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
audit_spec = importlib.util.spec_from_file_location("_person_vme_audit", HERE / "audit.py")
audit = importlib.util.module_from_spec(audit_spec)
audit_spec.loader.exec_module(audit)


class CandidateContracts(unittest.TestCase):
    @staticmethod
    def symbol_table(names, **overrides):
        class Symbol(dict):
            def __init__(self, name):
                super().__init__(st_value=0x01010000, st_size=4, st_shndx=2)
                self.name = name
                self.update(overrides.get(name, {}))
        return SimpleNamespace(iter_symbols=lambda: [Symbol(n) for n in names])

    def test_fast_accepts_only_validation_symbol_garbage_collection(self):
        table = self.symbol_table(audit.COMMON_COUNTERS)
        found = audit.diagnostic_symbols(table, "fast", 0x01070000)
        self.assertEqual(set(found), audit.COMMON_COUNTERS)
        with self.assertRaisesRegex(ValueError, "pd_vme_first_bad_index"):
            audit.diagnostic_symbols(table, "validate", 0x01070000)

    def test_all_common_counters_remain_mandatory_in_both_modes(self):
        known = audit.COMMON_COUNTERS | audit.VALIDATION_COUNTERS
        for name in audit.COMMON_COUNTERS:
            for mode in ("fast", "validate"):
                with self.subTest(counter=name, mode=mode):
                    with self.assertRaisesRegex(ValueError, name):
                        audit.diagnostic_symbols(self.symbol_table(known - {name}), mode, 0x01070000)

    def test_retained_optional_symbols_still_have_to_be_valid(self):
        known = audit.COMMON_COUNTERS | audit.VALIDATION_COUNTERS
        for change in ({"st_size": 8}, {"st_value": 0x01070000}, {"st_value": 0}):
            table = self.symbol_table(known, pd_vme_first_bad_index=change)
            with self.assertRaisesRegex(ValueError, "invalid=.*pd_vme_first_bad_index"):
                audit.diagnostic_symbols(table, "fast", 0x01070000)

    def test_undefined_common_symbol_does_not_satisfy_audit(self):
        known = audit.COMMON_COUNTERS | audit.VALIDATION_COUNTERS
        table = self.symbol_table(known, pd_vme_commands={"st_shndx": "SHN_UNDEF"})
        with self.assertRaisesRegex(ValueError, "missing=.*pd_vme_commands"):
            audit.diagnostic_symbols(table, "fast", 0x01070000)

    def test_resource_audit_distinguishes_candidate_and_rejects_oversized_itcm(self):
        class Symbol(dict):
            def __init__(self, name):
                super().__init__(st_value=0x01010000,st_size=4,st_shndx=2)
                self.name=name
        names=("pd_vme_conv_calls","pd_vme_fallback_calls","pd_vme_commands",
               "pd_vme_validated_layers","pd_vme_mismatches","pd_vme_first_bad_index")
        table=SimpleNamespace(iter_symbols=lambda:[Symbol(n) for n in names])
        elf=SimpleNamespace(get_section_by_name=lambda _:table)
        report={"segments":[{"address":0,"bytes":136080}],
                "symbols":{"__heap_start__":{"address":0x01070000}}}
        with patch.object(audit.firmware_report,"inspect_elf",return_value=report), \
                patch.object(audit,"ELFFile",return_value=elf):
            result=audit.inspect(b"synthetic","validate")
            self.assertTrue(result["validation_executes_reference"])
            self.assertEqual(result["NPU_RTL"],"NOT_RUN")
            self.assertIn("VME_pointwise",result["kernel_backend"])
            report["segments"][0]["bytes"]=256*1024+1
            with self.assertRaisesRegex(ValueError,"does not fit"):
                audit.inspect(b"synthetic","fast")

    def test_registration_is_explicit_and_baseline_is_not_edited(self):
        old = (prepare.BASE / "person_program.cc").read_bytes()
        new = prepare.program_source().decode()
        self.assertIn("person_vme::RegisterPointwise()", new)
        self.assertNotIn("AddConv2D(tflite::Register_CONV_2D_INT8())", new)
        self.assertIn("pd_vme_conv_calls != 14", new)
        self.assertIn("pd_vme_validated_layers != 14", new)
        self.assertEqual((prepare.BASE / "person_program.cc").read_bytes(), old)

    def test_distinct_validation_speed_and_emulated_targets(self):
        text = prepare.build_text().decode()
        for name in ("person_vme_validate", "person_vme_fast", "host_model_test", "host_core_test"):
            self.assertIn('name = "' + name + '"', text)
        self.assertIn("-DPD_VME_VALIDATE=1", text)
        self.assertIn("-DPD_VME_VALIDATE=0", text)
        self.assertEqual(text.count("-DPD_VME_EMULATE=1"), 1)
        self.assertEqual(text.count("itcm_size_kbytes = 256"), 2)
        self.assertEqual(text.count("dtcm_size_kbytes = 512"), 2)
        self.assertIn("-fno-tree-vectorize", text)
        self.assertIn("-fno-lto", text)

    def test_instruction_words_match_official_encoding(self):
        word = lambda f, v2, r1, f3, rd, op: (f<<26)|(1<<25)|(v2<<20)|(r1<<15)|(f3<<12)|(rd<<7)|op
        text = (HERE / "vme_tile.h").read_text()
        for value in (word(0x17,4,10,6,0,0x57), word(0x10,31,10,6,4,0x57), word(0x3c,8,16,0,1,0x77)):
            self.assertIn("0x%08x" % value, text)

    def test_real_and_emulated_counters_are_not_conflated(self):
        text = (HERE / "conv_vme.cc").read_text()
        self.assertIn("++pd_vme_emulated_tiles", text)
        self.assertIn("HardwareTile backend(&pd_vme_commands)", text)
        self.assertIn("if (saved[i] != y[i])", text)  # Full byte comparison, not top-1/hash.
        self.assertIn("Register_CONV_2D().invoke", text)
        self.assertIn("data.per_channel_output_multiplier[channel]", text)

    def test_installer_is_idempotent_and_preserves_both_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_file = root / "baseline.cc"
            baseline_file.write_bytes(b"original")
            old = {"upstream": prepare.UPSTREAM, "model_sha256": prepare.MODEL_SHA256,
                   "files": {"baseline.cc": prepare.sha(b"original")}}
            (root / prepare.baseline.MANIFEST).write_text(json.dumps(old))
            files = {prepare.PACKAGE+"/BUILD": b"candidate"}
            with patch.object(prepare.baseline.capacity,"verify"), patch.object(prepare,"expected_files",return_value=files):
                first=prepare.prepare(root,root)
                self.assertEqual(first,prepare.prepare(root,root))
                self.assertEqual(baseline_file.read_bytes(),b"original")
                self.assertEqual(first["status"],"CANDIDATE_NOT_VALIDATED")
                (root / prepare.PACKAGE / "BUILD").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError,"Candidate file changed"):
                    prepare.prepare(root,root)
                self.assertEqual((root / prepare.PACKAGE / "BUILD").read_bytes(),b"changed")

    def test_changed_baseline_rejected_before_candidate_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root / "baseline.cc").write_bytes(b"changed")
            (root / prepare.baseline.MANIFEST).write_text(json.dumps({
                "upstream":prepare.UPSTREAM,"model_sha256":prepare.MODEL_SHA256,
                "files":{"baseline.cc":prepare.sha(b"original")}}))
            with patch.object(prepare.baseline.capacity,"verify"):
                with self.assertRaisesRegex(ValueError,"Baseline file changed"):
                    prepare.prepare(root,root)
            self.assertFalse((root / prepare.PACKAGE).exists())


if __name__ == "__main__":
    unittest.main()
