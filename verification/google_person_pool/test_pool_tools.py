"""Generator/audit tests only. No TFLM native model or NPU RTL execution."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
import prepare_pool as prepare
import audit_pool as audit


class PoolToolTests(unittest.TestCase):
    def test_only_pool_registration_changes_vs_vme_parent(self):
        text=prepare.program_source().decode();old=prepare.parent.program_source().decode()
        registration='resolver.AddDepthwiseConv2D(tflite::Register_DEPTHWISE_CONV_2D_INT8())'
        self.assertEqual(text.count(registration),1);self.assertEqual(old.count(registration),1)
        self.assertIn('resolver.AddAveragePool2D(person_pool::RegisterAveragePool())',text)
        self.assertIn('resolver.AddConv2D(person_vme::RegisterPointwise())',text)
        self.assertIn('pd_pool_calls != 1',text)
        self.assertIn('pd_pool_validated != 1',text)
        self.assertIn('resolver.AddSoftmax(tflite::Register_SOFTMAX_INT8())',text)
        self.assertNotIn('coralnpu_v2::opt::litert_micro',text)

    def test_builds_separate_hardware_and_host_emulation(self):
        text=prepare.build_text().decode()
        self.assertEqual(text.count('name = "person_vme_pool_validate"'),1)
        self.assertEqual(text.count('name = "person_vme_pool_fast"'),1)
        self.assertEqual(text.count('"-DPD_POOL_EMULATE=1"'),1)
        self.assertEqual(text.count('"-DPD_POOL_VALIDATE=1"'),2)
        self.assertEqual(text.count('"-DPD_POOL_VALIDATE=0"'),1)
        self.assertEqual(text.count('"pool_op.cc"'),3)
        self.assertIn('"-DPD_POOL_TFLM_REFERENCE=1"',text)
        self.assertIn('pool_core_test.cc',text)
        self.assertNotIn('//sw/opt/litert-micro:depthwise_conv',text)

    def test_full_host_model_compares_pool_and_conv_but_not_hardware(self):
        text=prepare.host_source().decode()
        self.assertIn('pd_pool_validated==pd_pool_calls',text)
        self.assertIn('pd_pool_vector_blocks==0',text)
        self.assertIn('compared_layers=30',text)
        self.assertIn('scores[][2]={{-113,113},{57,-57}}',text)
        self.assertIn('Register_DEPTHWISE_CONV_2D_INT8()',text)

    def test_install_is_separate_idempotent_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            parent_manifest=root/prepare.parent.MANIFEST;parent_manifest.write_bytes(b"original parent identity")
            files={prepare.PACKAGE+"/BUILD":b"synthetic new build"}
            with patch.object(prepare.parent,"prepare"),patch.object(prepare,"expected_files",return_value=files):
                first=prepare.prepare(root,root);second=prepare.prepare(root,root)
                self.assertEqual(first,second)
                self.assertEqual(parent_manifest.read_bytes(),b"original parent identity")
                self.assertEqual(first["depthwise"],"official_default_registration_unchanged")
                (root/prepare.PACKAGE/"BUILD").write_bytes(b"user change")
                with self.assertRaisesRegex(ValueError,"nothing overwritten"):prepare.prepare(root,root)
                self.assertEqual((root/prepare.PACKAGE/"BUILD").read_bytes(),b"user change")

    def test_missing_parent_is_not_created_implicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaisesRegex(ValueError,"existing VME v1 first"):prepare.prepare(root,root)
            self.assertEqual(list(root.iterdir()),[])

    def test_fast_audit_keeps_common_pool_symbols_mandatory(self):
        class Symbol(dict):
            def __init__(self,name):
                super().__init__(st_value=0x01010000,st_size=4,st_shndx=2);self.name=name
        base=dict(symbols={"__heap_start__":{"address":0x01070000}})
        common={"pd_pool_calls","pd_pool_fallbacks","pd_pool_vector_blocks","pd_pool_mismatches"}
        names=set(common)
        elf=SimpleNamespace(get_section_by_name=lambda _:SimpleNamespace(iter_symbols=lambda:[Symbol(n) for n in names]))
        with patch.object(audit.vme,"inspect",side_effect=lambda *_:copy.deepcopy(base)),patch.object(audit,"ELFFile",return_value=elf):
            self.assertEqual(set(audit.inspect(b"synthetic","fast")["pool_symbols"]),common)
            with self.assertRaisesRegex(ValueError,"pd_pool_validated"):audit.inspect(b"synthetic","validate")
            names.remove("pd_pool_vector_blocks")
            with self.assertRaisesRegex(ValueError,"pd_pool_vector_blocks"):audit.inspect(b"synthetic","fast")

    def test_configured_elf_paths_reject_other_variant_and_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/"bazel-out/test/person_vme_pool_fast.elf"
            target.parent.mkdir(parents=True);target.write_bytes(b"synthetic")
            self.assertEqual(audit.configured(root,"bazel-out/test/person_vme_pool_fast.elf","fast"),target.resolve())
            for path in ("../person_vme_pool_fast.elf","/tmp/person_vme_pool_fast.elf","bazel-out/test/person_vme_fast.elf"):
                with self.assertRaises(ValueError):audit.configured(root,path,"fast")


if __name__=="__main__":unittest.main()
