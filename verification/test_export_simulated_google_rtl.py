"""Tests for preserving existing simulation outputs; not circuit simulation."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile


spec = importlib.util.spec_from_file_location(
    "sim_export", Path(__file__).with_name("export_simulated_google_rtl.py"))
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class ExportSimulatedTests(unittest.TestCase):
    def fixture(self, root):
        repo = root / "core"
        generated = repo / "bazel-bin/hdl/chisel/src/coralnpu"
        generated.mkdir(parents=True)
        top = b"module VmeCoreMiniAxi; endmodule\n"
        (generated / exporter.OUTPUT_NAMES[0]).write_bytes(top)
        header = "\n".join("#define KP_{} {}".format(key, value)
                           for key, value in exporter.EXPECTED_PARAMETERS.items()) + "\n"
        (generated / exporter.OUTPUT_NAMES[2]).write_text(header)
        with zipfile.ZipFile(generated / exporter.OUTPUT_NAMES[1], "w") as stream:
            stream.writestr("filelist.f", "+incdir+.\n"
                            + "\n".join("+define+" + value for value in sorted(exporter.EXPECTED_DEFINES))
                            + "\npkg.sv\nregisters.svh\nSram.v\nVmeCoreMiniAxi.sv\n")
            stream.writestr("pkg.sv", "package fixture; endpackage\n")
            stream.writestr("registers.svh", "// global fixture header\n")
            stream.writestr("Sram.v", "module Sram; endmodule\n")
            stream.writestr("VmeCoreMiniAxi.sv", top)
        (repo / "tests/cocotb").mkdir(parents=True)
        (repo / "tests/cocotb/BUILD").write_text(
            'verilator_cocotb_model(\n    name = "vme_core_mini_axi_model",\n'
            '    verilog_source = "//hdl/chisel/src/coralnpu:VmeCoreMiniAxi.sv",\n)\n')
        (repo / "hdl/chisel/src/coralnpu").mkdir(parents=True)
        (repo / "hdl/chisel/src/coralnpu/BUILD").write_text("# synthetic BUILD fixture\n")
        (repo / "LICENSE").write_text("fixture license\n")
        log = repo / exporter.DEFAULT_LOG
        log.parent.mkdir(parents=True)
        log.write_text("TESTS=1 PASS=1 FAIL=0 SKIP=0\n")
        return argparse.Namespace(repo=str(repo), output=str(root / "package"), test_log=None), generated

    def export_fixture(self, args):
        def git(command, **kwargs):
            return "a" * 40 + "\n" if "rev-parse" in command else ""
        with patch.object(subprocess, "check_output", side_effect=git):
            exporter.export(args)
        return Path(args.output)

    def test_prod_parameters_rejected(self):
        text = "\n".join("#define KP_{} {}".format(key, value)
                         for key, value in exporter.EXPECTED_PARAMETERS.items())
        with self.assertRaisesRegex(ValueError, "enableAxiInstructionFetch"):
            exporter.checked_parameters(text.replace("KP_enableAxiInstructionFetch true",
                                                       "KP_enableAxiInstructionFetch false"))

    def test_missing_or_failed_log_rejected(self):
        for value in ["no summary", "TESTS=1 PASS=0 FAIL=1", "TESTS=0 PASS=0 FAIL=0",
                      "TESTS=1 PASS=0 FAIL=1\nTESTS=1 PASS=1 FAIL=0"]:
            with self.assertRaises(ValueError):
                exporter.passing_log(value)
        self.assertEqual(exporter.passing_log("TESTS=1 PASS=1 FAIL=0 SKIP=0")['pass'], 1)

    def test_export_preserves_bytes_and_headers(self):
        with tempfile.TemporaryDirectory() as temporary:
            args, generated = self.fixture(Path(temporary))
            original = {name: (generated / name).read_bytes() for name in exporter.OUTPUT_NAMES}
            package = self.export_fixture(args)
            for name, data in original.items():
                self.assertEqual((package / "original" / name).read_bytes(), data)
                self.assertEqual((generated / name).read_bytes(), data)
            wrapper = (package / "compile_units/all.sv").read_text()
            self.assertLess(wrapper.index("registers.svh"), wrapper.index("Sram.v"))
            self.assertEqual(exporter.verify(package)["original_rtl_unchanged"], True)
            manifest = json.loads((package / "manifest.json").read_text())
            self.assertFalse(manifest["functional_tests_rerun"])
            self.assertEqual(manifest["generated_parameters"]["enableAxiInstructionFetch"], "true")
            self.assertTrue(package.with_name("package.tar.gz").is_file())

    def test_existing_directory_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            args, _ = self.fixture(Path(temporary))
            output = Path(args.output)
            output.mkdir()
            (output / "user_file").write_text("keep\n")
            with self.assertRaisesRegex(ValueError, "already exists"):
                self.export_fixture(args)
            self.assertEqual((output / "user_file").read_text(), "keep\n")

    def test_tampered_extracted_rtl_rejected_even_after_rehash(self):
        with tempfile.TemporaryDirectory() as temporary:
            args, _ = self.fixture(Path(temporary))
            package = self.export_fixture(args)
            (package / "rtl/Sram.v").write_text("changed\n")
            exporter.write_checksums(package)
            with self.assertRaisesRegex(ValueError, "differs from original ZIP"):
                exporter.verify(package)

    def test_no_bazel_subprocess_is_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            args, _ = self.fixture(Path(temporary))
            commands = []
            def git(command, **kwargs):
                commands.append(command)
                return "a" * 40 if "rev-parse" in command else ""
            with patch.object(subprocess, "check_output", side_effect=git):
                exporter.export(args)
            self.assertTrue(commands)
            self.assertTrue(all(command[0] == "git" for command in commands))

    def test_unsafe_or_case_colliding_zip_rejected(self):
        for names in [("../escape.sv",), ("Top.sv", "top.sv")]:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root / "rtl.zip"
                with zipfile.ZipFile(archive, "w") as stream:
                    for name in names:
                        stream.writestr(name, "")
                with self.assertRaises(ValueError):
                    exporter.unpack_zip(archive, root / "out")

    def test_changed_compile_wrapper_rejected_even_after_rehash(self):
        with tempfile.TemporaryDirectory() as temporary:
            args, _ = self.fixture(Path(temporary))
            package = self.export_fixture(args)
            wrapper = package / "compile_units/all.sv"
            wrapper.write_text(wrapper.read_text().replace('`include "rtl/registers.svh"\n', ""))
            exporter.write_checksums(package)
            with self.assertRaisesRegex(ValueError, "upstream order"):
                exporter.verify(package)


if __name__ == "__main__":
    unittest.main()
