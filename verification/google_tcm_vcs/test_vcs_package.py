"""Synthetic package/launcher tests. These do not compile or simulate an NPU."""
import argparse
import ast
from contextlib import ExitStack
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "google_tcm_capacity"))
import package_lib as lib
import export as exporter
import runtime
import upgrade_svaext
from test_control import as_log, synthetic_rows
from test_workset import log, synthetic_record
from workset_spec import REPEATS, STRATEGIES


def header(kib):
    expected = dict(xlen="32", itcmSizeKBytes="8", dtcmSizeKBytes=str(kib), axi2IdBits="6", rvvVlen="128",
                    fetchDataBits="128", lsuDataBits="128", enableFetchL0="false", enableRvv="true",
                    enableVme="true", enableFloat="true", enableZfbfmin="true", enableVectorBf16="true",
                    enableAxiInstructionFetch="true", enableVerification="false")
    return "".join(f"#define KP_{k} {v}\n" for k, v in expected.items()).encode()


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.base = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root, self.job = self.base / "source", self.base / "job"
        self.root.mkdir()
        self.job.mkdir()
        self.top = "VmeCoreMini_ITCM8KB_DTCM1024KBAxi"
        self.generated = self.root / "bazel-bin/tests/cocotb/tcm_workset/d1024"
        self.generated.mkdir(parents=True)
        self.sv = b"module " + self.top.encode() + b"; endmodule\nmodule Sram; endmodule\n"
        (self.generated / (self.top + ".sv")).write_bytes(self.sv)
        (self.generated / ("V" + self.top + "_parameters.h")).write_bytes(header(1024))
        self.contents = {self.top + ".sv": b"module " + self.top.encode() + b"; endmodule\n",
                         "Sram.v": b"module Sram; endmodule\n",
                         "filelist.f": ("+incdir+.\n" + "".join("+define+" + n + "\n" for n in sorted(lib.ZIP_DEFINES)) +
                                        self.top + ".sv\nSram.v\n").encode()}
        with zipfile.ZipFile(self.generated / (self.top + ".zip"), "w") as z:
            for name, data in self.contents.items(): z.writestr(name, data)
        self.elf = self.base / "workset_program.elf"
        elf = bytearray(52)
        elf[:6], elf[18:20] = b"\x7fELF\x01\x01", (243).to_bytes(2, "little")
        self.elf.write_bytes(elf)
        for name in ("tcm_capacity_manifest.json", "tcm_control_manifest.json", "tcm_workset_manifest.json"):
            (self.root / name).write_text('{"synthetic": true}')
        for name in ("build.log", "build-command.txt", "export.sh", "elf-outputs.txt", "execution-root.txt"):
            (self.job / name).write_text("synthetic evidence\n")
        self.control = self.base / "control_d1024.synthetic"
        self.pilot = self.base / "workset_d128_t12_r0.synthetic"
        self.capacity = self.base / "run_d1024.synthetic"
        for run in (self.control, self.pilot, self.capacity):
            run.mkdir()
            (run / "manifest.json").write_text('{"synthetic": true}')
        (self.control / "test.log").write_text(as_log(synthetic_rows(1024)))
        (self.control / "parameters.h").write_bytes(header(1024))
        (self.control / "artifacts.sha256").write_text(lib.digest(self.sv) + "  bazel-bin/tests/fake/" + self.top + ".sv\n")
        records = [synthetic_record(kib=128, strategy=s, repeat=r) for s in STRATEGIES for r in range(REPEATS)]
        for row in records: row["elf_sha256"] = lib.sha(self.elf)
        (self.pilot / "test.log").write_text(log(records))
        (self.capacity / "test.log").write_text("synthetic capacity log\n")
        self.stack.enter_context(patch.object(exporter.workset, "verify"))
        self.stack.enter_context(patch.object(exporter.workset, "git", return_value=b"# synthetic upstream resource\n"))
        self.stack.enter_context(patch.object(exporter, "stage1_evidence", return_value={"directory": str(self.capacity)}))
        self.output = self.base / "package"

    def export(self):
        with patch("sys.stdout", new=io.StringIO()):
            return exporter.export(self.root, 1024, self.elf, self.output, self.job)

    def test_complete_export_preserves_original_bytes_and_evidence(self):
        self.export()
        result = lib.verify(self.output)
        self.assertEqual(result["vcs_simulation"], "NOT_RUN")
        self.assertEqual((self.output / "rtl" / (self.top + ".sv")).read_bytes(), self.sv)
        self.assertEqual((self.output / "firmware/workset_program.elf").read_bytes(), self.elf.read_bytes())
        for name in exporter.SUPPORT:
            self.assertEqual((self.output / "support" / name).read_bytes(), (exporter.TOOLS / name).read_bytes())
        for name, data in self.contents.items():
            self.assertEqual((self.output / "rtl_dependencies" / name).read_bytes(), data)
        with tarfile.open(self.base / "package.tar.gz") as archive:
            self.assertTrue(all(n.startswith("package/") or n == "package" for n in archive.getnames()))
            self.assertEqual(archive.extractfile("package/rtl/" + self.top + ".sv").read(), self.sv)
        result = subprocess.run([sys.executable, "-B", str(self.output / "runtime.py"), "verify"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[TCM_VCS_PACKAGE_VERIFIED]", result.stdout)

    def test_no_overwrite(self):
        self.export()
        before = lib.sha(self.output / "manifest.json")
        with self.assertRaises(ValueError): self.export()
        self.assertEqual(lib.sha(self.output / "manifest.json"), before)

    def test_changed_rtl_is_not_exported(self):
        (self.generated / (self.top + ".sv")).write_bytes(self.sv + b"// changed\n")
        with self.assertRaises(ValueError): self.export()
        self.assertFalse(self.output.exists())

    def test_wrong_parameter_not_exported(self):
        (self.generated / ("V" + self.top + "_parameters.h")).write_bytes(header(2048))
        with self.assertRaises(ValueError): self.export()
        self.assertFalse(self.output.exists())

    def test_partial_pilot_not_exported(self):
        text = (self.pilot / "test.log").read_text().splitlines()
        (self.pilot / "test.log").write_text("\n".join(text[:2]) + "\nTIMEOUT\n")
        with self.assertRaises(ValueError): self.export()
        self.assertFalse(self.output.exists())

    def test_changed_elf_not_exported(self):
        self.elf.write_bytes(self.elf.read_bytes() + b"changed")
        with self.assertRaises(ValueError): self.export()
        self.assertFalse(self.output.exists())

    def test_manifest_and_artifact_tampering_rejected(self):
        self.export()
        path = self.output / "firmware/workset_program.elf"
        original = path.read_bytes()
        path.write_bytes(original + b"tampered")
        with self.assertRaises(ValueError): lib.verify(self.output)
        path.write_bytes(original)
        (self.output / "extra.txt").write_bytes(b"unlisted")
        with self.assertRaises(ValueError): lib.verify(self.output)

    def test_zip_path_and_case_collision_rejected(self):
        for names in (("../escape.sv",), ("/escape.sv",), ("a.sv", "A.sv")):
            path = self.base / "bad.zip"
            with zipfile.ZipFile(path, "w") as z:
                for name in names: z.writestr(name, b"bad")
            with self.assertRaises(ValueError): lib.zip_contents(path)
        for name in ("a\\b", "a//b", "a b.sv", "a:$bad.sv"):
            with self.assertRaises(ValueError): lib.relative(name)

    def test_wrong_macros_or_missing_sram_rejected(self):
        wrong = dict(self.contents)
        wrong["filelist.f"] += b"+define+SYNTHESIS\n"
        with self.assertRaises(ValueError): lib.compilation_inputs(wrong, self.top)
        wrong = dict(self.contents)
        del wrong["Sram.v"]
        with self.assertRaises(ValueError): lib.compilation_inputs(wrong, self.top)

    def test_runfiles_adapter_resolves_only_packaged_firmware(self):
        self.export()
        adapter = self.output / "python/bazel_tools/tools/python/runfiles/runfiles.py"
        spec = importlib.util.spec_from_file_location("synthetic_runfiles", adapter)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.dict(os.environ, TCM_VCS_PACKAGE=str(self.output)):
            self.assertEqual(module.Create().Rlocation("coralnpu_hw/tests/cocotb/tcm_workset/workset_program.elf"),
                             str(self.output / "firmware/workset_program.elf"))
            self.assertIsNone(module.Create().Rlocation("../not_the_firmware"))

    def original_v1_package(self):
        self.export()
        # Reconstruct the exact LF-encoded v1 files, independent of Windows
        # checkout EOL conversion. Upgrade accepts only their pinned byte hashes.
        original_runtime = (HERE / "runtime.py").read_bytes().replace(b"\r\n", b"\n").replace(
            upgrade_svaext.NEW_ARGS, upgrade_svaext.OLD_ARGS)
        original_library = (HERE / "package_lib.py").read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(lib.digest(original_runtime), upgrade_svaext.ORIGINAL_RUNTIME_SHA256)
        self.assertEqual(lib.digest(original_library), upgrade_svaext.ORIGINAL_LIBRARY_SHA256)
        (self.output / "runtime.py").write_bytes(original_runtime)
        (self.output / "package_lib.py").write_bytes(original_library)
        lib.seal(self.output, json.loads((self.output / "manifest.json").read_text()))
        return lib.verify(self.output)

    def test_svaext_upgrade_preserves_original_and_all_payload_bytes(self):
        parent = self.original_v1_package()
        before = {p.relative_to(self.output).as_posix(): p.read_bytes()
                  for p in self.output.rglob("*") if p.is_file()}
        with patch("sys.stdout", new=io.StringIO()):
            destination = upgrade_svaext.upgrade(self.output)
        updated = lib.verify(destination)
        self.assertEqual(updated["passed_control_rtl_sha256"], parent["passed_control_rtl_sha256"])
        self.assertEqual(updated["passed_workset_elf_sha256"], parent["passed_workset_elf_sha256"])
        for name, data in before.items():
            self.assertEqual((self.output / name).read_bytes(), data)
            if name not in ("runtime.py", "manifest.json", "SHA256SUMS"):
                self.assertEqual((destination / name).read_bytes(), data)
        self.assertEqual((destination / "runtime.py").read_bytes(),
                         before["runtime.py"].replace(upgrade_svaext.OLD_ARGS, upgrade_svaext.NEW_ARGS))
        self.assertEqual(updated["vcs_launcher_upgrade"]["parent_manifest_sha256"], lib.digest(before["manifest.json"]))
        self.assertEqual(updated["vcs_simulation"], "NOT_RUN")
        result = subprocess.run([sys.executable, "-B", str(destination / "runtime.py"), "verify"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_svaext_upgrade_refuses_overwrite(self):
        self.original_v1_package()
        destination = self.output.with_name(self.output.name + "_svaext_v1")
        destination.mkdir()
        with self.assertRaisesRegex(ValueError, "destination exists"):
            upgrade_svaext.upgrade(self.output)
        self.assertEqual(list(destination.iterdir()), [])

    def test_svaext_upgrade_rejects_unknown_runtime_even_when_resealed(self):
        manifest = self.original_v1_package()
        with (self.output / "runtime.py").open("ab") as stream:
            stream.write(b"# unreviewed change\n")
        lib.seal(self.output, manifest)
        with self.assertRaisesRegex(ValueError, "exact original v1 runtime"):
            upgrade_svaext.upgrade(self.output)
        self.assertFalse(self.output.with_name(self.output.name + "_svaext_v1").exists())

    def test_svaext_upgrade_rejects_unknown_verifier_before_import(self):
        self.original_v1_package()
        (self.output / "package_lib.py").write_bytes(b"raise RuntimeError('must not execute')\n")
        with self.assertRaisesRegex(ValueError, "unknown package_lib"):
            upgrade_svaext.upgrade(self.output)

    def test_svaext_upgrade_rejects_payload_tampering(self):
        self.original_v1_package()
        (self.output / "firmware/workset_program.elf").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "immutable package files"):
            upgrade_svaext.upgrade(self.output)

    def test_large_run_blocked_until_same_model_pilot_and_tamper_rejected(self):
        self.export()
        state = self.base / "runtime"
        build = state / "builds/fake_model"
        (build / "simv.daidir").mkdir(parents=True)
        (build / "simv").write_bytes(b"synthetic")
        (build / "libsram_backdoor.so").write_bytes(b"synthetic original DPI")
        manifest = lib.verify(self.output)
        identity = runtime.build_identity(self.output, manifest, {"synthetic": True})
        lib.write_json(state / "current_build.json", dict(identity=identity, directory=str(build), model_files=runtime.model_hashes(build)))
        def run_phase(root, command, directory, timeout, extra):
            records = [synthetic_record(kib=1024, strategy=s, repeat=r) for s in STRATEGIES for r in range(REPEATS)]
            (directory / "_test.log").write_text(log(records))
            (directory / "results.xml").write_text('<testsuite><testcase name="tcm_workset_test"/></testsuite>')
            return dict(elapsed_seconds=0.01, exit_code=0, timed_out=False)
        with patch.object(runtime, "ROOT", self.output), patch.object(runtime, "environment", return_value={"synthetic": True}), \
                patch.object(sys, "path", list(sys.path)), patch("sys.stdout", new=io.StringIO()), \
                patch.object(runtime, "execute_phase", side_effect=run_phase) as execute:
            with patch.object(sys, "argv", ["runtime.py", "run", "--tiles", "384", "--state-dir", str(state)]):
                with self.assertRaisesRegex(ValueError, "large run blocked"): runtime.main()
            execute.assert_not_called()
            with patch.object(sys, "argv", ["runtime.py", "run", "--state-dir", str(state)]):
                runtime.main()
            self.assertEqual(execute.call_count, 1)
            pilot = next((state / "runs").glob("t12_r0.*"))
            runtime.checked_run(pilot, manifest, identity, runtime.model_hashes(build))
            with (pilot / "_test.log").open("a") as stream: stream.write("changed\n")
            with patch.object(sys, "argv", ["runtime.py", "run", "--tiles", "384", "--state-dir", str(state)]):
                with self.assertRaisesRegex(ValueError, "large run blocked"): runtime.main()
            self.assertEqual(execute.call_count, 1)

    def test_successful_model_is_reused_without_recompiling(self):
        self.export()
        state = self.base / "runtime"
        def build_phase(root, command, directory, timeout):
            (directory / "simv").write_bytes(b"synthetic")
            (directory / "simv.daidir").mkdir()
            (directory / "libsram_backdoor.so").write_bytes(b"synthetic original DPI")
            return dict(elapsed_seconds=0.01)
        with patch.object(runtime, "ROOT", self.output), patch.object(runtime, "environment", return_value={"synthetic": True}), \
                patch.object(runtime, "execute_phase", side_effect=build_phase) as execute, \
                patch.object(sys, "argv", ["runtime.py", "build", "--state-dir", str(state)]), \
                patch("sys.stdout", new=io.StringIO()):
            runtime.main()
            runtime.main()
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(len(list((state / "builds").iterdir())), 1)


class RuntimeTests(unittest.TestCase):
    def test_cache_identity_ignores_banner_time_and_aslr_but_not_versions(self):
        manifest = dict(hdl_top="Top", files={"rtl/Top.sv": "a" * 64})
        one = dict(vcs_release="Q-2020.03-SP2-7", vcs_version="banner at 10:00", ldd={"a": "(0x1000)"})
        two = dict(one, vcs_version="banner at 11:00", ldd={"a": "(0x2000)"})
        self.assertEqual(runtime.build_identity(Path("/pkg"), manifest, one), runtime.build_identity(Path("/pkg"), manifest, two))
        two["vcs_release"] = "V-2023.12"
        self.assertNotEqual(runtime.build_identity(Path("/pkg"), manifest, one), runtime.build_identity(Path("/pkg"), manifest, two))
    def test_build_uses_monolithic_rtl_and_same_macros(self):
        fake = Mock()
        module = types.ModuleType("cocotb_tools.runner")
        module.get_runner = Mock(return_value=fake)
        root = Path("/synthetic/package")
        args = argparse.Namespace(command="_build", build_dir=Path("/synthetic/build"))
        manifest = dict(hdl_top="ExampleTop", zip_include_dirs=[".", "headers"])
        with patch.dict(sys.modules, {"cocotb_tools.runner": module}), patch.dict(os.environ, TCM_VCS_CHILD="1"), \
                patch.object(runtime, "paths"), patch.object(runtime, "build_dpi", return_value=dict(vcs_cc="/bin/gcc", vcs_cpp="/bin/g++")):
            runtime.phase(args, root, manifest)
        kw = fake.build.call_args.kwargs
        self.assertEqual(kw["sources"], [root / "rtl/ExampleTop.sv"])
        self.assertEqual(set(a[8:] for a in kw["build_args"] if a.startswith("+define+")), set(lib.DEFINES) | {"VCS"})
        self.assertNotIn("SYNTHESIS", str(kw))
        self.assertEqual(kw["build_args"][2:4], ["-assert", "svaext"])
        self.assertFalse(kw["waves"])
        self.assertFalse(kw["clean"])

    def test_svaext_option_changes_model_identity(self):
        manifest = dict(hdl_top="Top", files={"rtl/Top.sv": "a" * 64})
        updated = runtime.build_identity(Path("/pkg"), manifest, {})
        previous_args = [a for a in runtime.BUILD_ARGS if a not in ("-assert", "svaext")]
        with patch.object(runtime, "BUILD_ARGS", previous_args):
            self.assertNotEqual(updated, runtime.build_identity(Path("/pkg"), manifest, {}))

    def test_test_phase_reuses_original_bench_seed_frontdoor(self):
        fake = Mock()
        module = types.ModuleType("cocotb_tools.runner")
        module.get_runner = Mock(return_value=fake)
        args = argparse.Namespace(command="_test", build_dir=Path("/run"), model_dir=Path("/model"), tiles=384, delay=0)
        with patch.dict(sys.modules, {"cocotb_tools.runner": module}), patch.dict(os.environ, TCM_VCS_CHILD="1"), \
                patch.object(runtime, "paths"):
            runtime.phase(args, Path("/pkg"), dict(hdl_top="Top", dtcm_kib=1024))
        kw = fake.test.call_args.kwargs
        self.assertEqual((kw["test_module"], kw["testcase"], kw["seed"]), ("workset_bench", "tcm_workset_test", 137))
        self.assertEqual(kw["extra_env"]["COCOTB_USE_FRONTDOOR"], "1")
        self.assertEqual(kw["extra_env"]["TCM_WS_TILES"], "384")
        self.assertEqual(kw["build_dir"], Path("/model"))
        self.assertEqual(kw["test_args"], ["-sv_lib", str(Path("/model/libsram_backdoor"))])
        self.assertFalse(kw["waves"])

    def test_xml_failure_skip_missing_or_extra_test_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "results.xml"
            path.write_text('<testsuites><testsuite><testcase name="tcm_workset_test"/></testsuite></testsuites>')
            runtime.check_xml(path)
            for xml in ('<testsuite/>', '<testsuite><testcase name="other"/></testsuite>',
                        '<testsuite><testcase name="tcm_workset_test"><failure/></testcase></testsuite>',
                        '<testsuite><testcase name="tcm_workset_test"><skipped/></testcase></testsuite>',
                        '<testsuite><testcase name="tcm_workset_test"/><testcase name="extra"/></testsuite>'):
                path.write_text(xml)
                with self.assertRaises(ValueError): runtime.check_xml(path)

    def test_model_hash_guard_detects_changed_model(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            build = state / "builds/unique"
            (build / "simv.daidir").mkdir(parents=True)
            (build / "simv").write_bytes(b"synthetic simv")
            (build / "libsram_backdoor.so").write_bytes(b"synthetic original DPI")
            (build / "simv.daidir/model.so").write_bytes(b"synthetic library")
            lib.write_json(state / "current_build.json", dict(identity="id", directory=str(build), model_files=runtime.model_hashes(build)))
            runtime.checked_build(state, "id")
            with self.assertRaises(ValueError): runtime.checked_build(state, "different-environment")
            (build / "simv").write_bytes(b"changed")
            with self.assertRaises(ValueError): runtime.checked_build(state, "id")

    def test_runtime_outputs_cannot_pollute_package(self):
        root = Path(tempfile.gettempdir()) / "synthetic_immutable_package"
        self.assertEqual(runtime.state_directory(root, None), root.with_name(root.name + "_runtime").resolve())
        with self.assertRaises(ValueError): runtime.state_directory(root, root / "build")

    def test_child_environment_keeps_semantics_and_disables_waves(self):
        with patch.dict(os.environ, WAVES="1", CLOCK_NS="99", COCOTB_TEST_FILTER="wrong", GPI_EXTRA="wrong"):
            env = runtime.child_env(Path("/pkg"))
        self.assertEqual((env["WAVES"], env["GUI"], env["CLOCK_NS"], env["TEST_XLEN"]), ("0", "0", "1.25", "32"))
        self.assertNotIn("COCOTB_TEST_FILTER", env)
        self.assertNotIn("GPI_EXTRA", env)

    def test_phase_timeout_is_incomplete_and_keeps_status(self):
        fake = Mock(pid=123456)
        fake.wait.side_effect = [subprocess.TimeoutExpired("synthetic", 1), -15, -15]
        with tempfile.TemporaryDirectory() as temp, patch.object(runtime.subprocess, "Popen", return_value=fake), \
                patch.object(runtime.signal, "SIGKILL", 9, create=True), \
                patch.object(runtime.os, "killpg", create=True) as killpg:
            directory = Path(temp)
            with self.assertRaises(RuntimeError): runtime.execute_phase(Path("/pkg"), "_test", directory, 1)
            status = json.loads((directory / "_test-status.json").read_text())
            self.assertTrue(status["timed_out"])
            self.assertNotEqual(status["exit_code"], 0)
            self.assertTrue((directory / "_test.log").is_file())
            self.assertEqual(killpg.call_count, 2)

    def test_scripts_do_not_build_verilator_model_or_run_tests_on_export(self):
        script = (HERE / "export.sh").read_text()
        self.assertIn('"//$tcm_package:rtl_emit_verilog"', script)
        self.assertIn('cquery "${tcm_flags[@]}"', script)
        self.assertIn("--noshow_progress", script)
        self.assertIn("--noblock_for_lock", script)
        self.assertNotIn("--cache_test_results", script)
        self.assertNotIn(":model", script)
        for p in HERE.glob("*.py"):
            ast.parse(p.read_text())

    def test_original_dpi_is_compiled_separately_with_private_cpp_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            config = dict(dpi_cxx="/private/g++", vcs_include="/vcs/include", vcs_cc="/bin/gcc", vcs_cpp="/bin/g++")
            def run(argv, **kwargs):
                if argv[0] != "ldd":
                    Path(argv[-1]).write_bytes(b"synthetic DPI SO")
                return types.SimpleNamespace(returncode=0, stdout="libc.so.6 => /lib64/libc.so.6\n", stderr="")
            with patch.object(runtime, "compiler_configuration", return_value=config), \
                    patch.object(runtime.subprocess, "run", side_effect=run) as compile_run, \
                    patch.object(runtime, "dpi_selftest") as selftest, patch("sys.stdout", new=io.StringIO()):
                runtime.build_dpi(Path("/pkg"), build)
            argv = compile_run.call_args_list[0].args[0]
            for flag in ("-std=c++17", "-static-libstdc++", "-static-libgcc", "-I/vcs/include"):
                self.assertIn(flag, argv)
            self.assertIn(str(Path("/pkg/dpi/sram_backdoor.cc")), argv)
            selftest.assert_called_once_with(build / "libsram_backdoor.so")

    def test_gcc48_is_rejected_before_vcs_compilation(self):
        with patch.dict(os.environ, TCM_DPI_CXX=sys.executable), \
                patch.object(runtime.subprocess, "run", return_value=types.SimpleNamespace(returncode=1, stdout="", stderr="")):
            with self.assertRaisesRegex(ValueError, "C\\+\\+17"):
                runtime.compiler_configuration()

    def test_pinned_upstream_python_imports_are_closed(self):
        bare = HERE.parent.parent / ".upstream-git/coralnpu-google.git"
        if not bare.is_dir():
            self.skipTest("local pinned Git objects unavailable")
        allowed = set(sys.stdlib_module_names) | {"numpy", "cocotb", "elftools", "bazel_tools", "coralnpu_test_utils"}
        for name in exporter.UPSTREAM_PY:
            data = subprocess.check_output(["git", "--git-dir=" + str(bare), "show", lib.UPSTREAM + ":" + name])
            tree = ast.parse(data)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names: self.assertIn(alias.name.split(".")[0], allowed)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertIn(node.module.split(".")[0], allowed)


@unittest.skipUnless(os.environ.get("TCM_VCS_REAL_DEPS_CHECK") == "1", "optional real cocotb2.0 dependency check")
class RealDependencyTests(unittest.TestCase):
    def test_real_cocotb_vcs_public_api_accepts_launcher_keywords(self):
        import inspect
        from cocotb_tools.runner import Vcs
        for key in ("sources", "includes", "hdl_toplevel", "build_args", "build_dir", "always", "clean", "waves"):
            self.assertIn(key, inspect.signature(Vcs.build).parameters)
        for key in ("test_module", "testcase", "seed", "build_dir", "test_dir", "results_xml", "extra_env", "waves", "gui", "test_args"):
            self.assertIn(key, inspect.signature(Vcs.test).parameters)

    def test_real_pinned_fixture_imports_without_bazel(self):
        bare = HERE.parent.parent / ".upstream-git/coralnpu-google.git"
        if not bare.is_dir(): self.skipTest("pinned Git objects unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in exporter.UPSTREAM_PY:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(subprocess.check_output(["git", "--git-dir=" + str(bare), "show", lib.UPSTREAM + ":" + name]))
            adapter = root / "bazel_tools/tools/python/runfiles/runfiles.py"
            adapter.parent.mkdir(parents=True)
            adapter.write_bytes((HERE / "runfiles.py.template").read_bytes())
            with patch.object(sys, "path", [str(root)] + sys.path), patch.dict(sys.modules), \
                    patch.dict(os.environ, TCM_VCS_PACKAGE=str(root)):
                for name in list(sys.modules):
                    if name.startswith(("coralnpu_test_utils", "bazel_tools", "workset_bench", "workset_axi_probe")):
                        sys.modules.pop(name)
                import workset_bench
                from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture
                self.assertTrue(callable(workset_bench.inspect_elf))
                self.assertTrue(callable(VerilatorTestFixture.Create))


if __name__ == "__main__":
    unittest.main(verbosity=2)
