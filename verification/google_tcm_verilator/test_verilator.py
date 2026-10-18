"""Local tests: do not claim to compile or simulate the NPU on Windows."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "google_tcm_capacity")]
import verilator_workset as adapter
import prepare_workset
from test_workset import layout, log, synthetic_record
from workset_spec import STRATEGIES, REPEATS, vectors


def fake_bundle(root):
    manifest = dict(dtcm_kib=1024, hdl_top="VmeCoreMini_ITCM8KB_DTCM1024KBAxi",
                    defines=["USE_GENERIC", "TB_SUPPORT", "ZVE32F_ON", "VLEN_128", "ZVT_ON", "ZVTBF16FMM_ON"],
                    zip_include_dirs=[".", "verification/assert"], passed_workset_elf_sha256="a" * 64,
                    vector_sha256={str(t): vectors(t)[3] for t in adapter.TILES})
    return types.SimpleNamespace(root=root, manifest=manifest, checked_log=prepare_workset.checked_log)


def fake_env():
    entry, segments, symbols, _ = layout()
    return dict(elf_entry=entry, elf_load_segments=segments, symbols=symbols,
                tools={n: "/conda/bin/" + n for n in ("perl", "verilator", "make", "cxx", "cc", "ar")},
                libs="/conda/cocotb/libs", libpython="/conda/lib/libpython3.11.so",
                cpp="/conda/cocotb/share/lib/verilator/verilator.cpp", ldd={"lib": "random address"})


def records():
    return [synthetic_record(kib=1024, strategy=s, repeat=r) for s in STRATEGIES for r in range(REPEATS)]


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "package"
        self.root.mkdir()
        (self.root / "manifest.json").write_text("{}")
        self.bundle, self.env = fake_bundle(self.root), fake_env()

    def test_normalize_only_presentation_boundaries(self):
        original = log(records())
        colored = original.replace(adapter.MARKER, "\x1b[32m" + adapter.MARKER)
        colored = colored.replace("}\n", "}\x1b[49m\x1b[39m\n")
        self.assertEqual(adapter.normalize(colored), original)
        for bad in (original.replace('"PASS"', '"P\x1b[0mASS"'),
                    original.replace("}\n", "}\x1b[2K\n"),
                    original.replace(adapter.MARKER, "[GOOGLE_TCM_\x1b[0mWORKSET] ")):
            with self.assertRaises(ValueError):
                adapter.normalize(bad)

    def test_extra_json_or_suffix_is_not_repaired(self):
        for suffix in ("garbage", "{}"):
            path = self.root / (suffix + ".log")
            path.write_text(log(records()).replace("}\n", "}" + suffix + "\n"))
            with self.assertRaises(ValueError):
                adapter.checked_results(self.bundle, self.env, path, 12, 0)

    def test_real_strict_checker_accepts_complete_records(self):
        path = self.root / "test.log"
        path.write_text(log(records()))
        result = adapter.checked_results(self.bundle, self.env, path, 12, 0)
        self.assertEqual(len(result), 2)
        self.assertEqual([r["strategy"] for r in result], list(STRATEGIES))

    def test_partial_duplicate_failed_or_changed_records_rejected(self):
        rows = records()
        bad_rows = copy.deepcopy(rows)
        bad_rows[-1]["axi"]["weight_read_bytes"] += 16
        samples = (log(rows[:-1]), log(rows + rows), log(rows).replace("FAIL=0", "FAIL=1"),
                   log(rows).replace("SKIP=0", "SKIP=1"), log(bad_rows))
        path = self.root / "bad.log"
        for text in samples:
            path.write_text(text)
            with self.assertRaises(ValueError):
                adapter.checked_results(self.bundle, self.env, path, 12, 0)

    def test_real_elf_identity_including_tuple_list_representation(self):
        path = self.root / "test.log"
        path.write_text(log(records()))
        adapter.checked_results(self.bundle, self.env, path, 12, 0)
        for field in ("elf_entry", "elf_load_segments", "symbols"):
            bad = copy.deepcopy(self.env)
            bad[field] = "different"
            with self.assertRaises(ValueError):
                adapter.checked_results(self.bundle, bad, path, 12, 0)

    def test_reference_requires_exact_cycles_and_counters(self):
        path = self.root / "reference.log"
        rows = records()
        path.write_text(log(rows))
        checked = adapter.checked_results(self.bundle, self.env, path, 12, 0)
        reference = adapter.checked_reference(self.bundle, self.env, path, checked, 12, 0)
        self.assertEqual(reference["sha256"], adapter.sha(path))
        for key in ("wait_for_halt_cycles", "csr_counters"):
            changed = copy.deepcopy(rows)
            for row in changed:
                if key == "wait_for_halt_cycles":
                    row[key] += 1
                else:
                    row[key]["ws_compute_cycles"] += 1
            path.write_text(log(changed))
            with self.assertRaises(ValueError):
                adapter.checked_reference(self.bundle, self.env, path, checked, 12, 0)

    def test_xml_missing_extra_failed_skipped_are_not_pass(self):
        path = self.root / "results.xml"
        good = '<testsuites><testsuite><testcase name="tcm_workset_test"/></testsuite></testsuites>'
        path.write_text(good)
        adapter.check_xml(path)
        for bad in ("<testsuites/>", good.replace("tcm_workset_test", "other"),
                    good.replace('/>', '><failure/></testcase>'),
                    good.replace('/>', '><skipped/></testcase>'),
                    good.replace('/>', '/><testcase name="extra"/>')):
            path.write_text(bad)
            with self.assertRaises(ValueError):
                adapter.check_xml(path)

    def test_build_matches_original_visibility_dpi_and_optimization(self):
        build = self.root.parent / "build"
        build.mkdir()
        commands = adapter.build_commands(self.bundle, self.env, build, 2)
        verilate, make = commands
        self.assertIn(str(self.root / "dpi/sram_backdoor.cc"), verilate)
        self.assertEqual(sum(s.endswith(".sv") for s in verilate), 1)
        self.assertIn(self.env["cpp"], verilate)
        self.assertIn("--vpi", verilate)
        self.assertIn("-rdynamic", verilate[verilate.index("-LDFLAGS") + 1])
        self.assertIn("-std=c++17", verilate[verilate.index("-CFLAGS") + 1])
        self.assertIn("-DUSE_GENERIC=\"\"", verilate)
        for name in self.bundle.manifest["defines"][1:]:
            self.assertIn("-D" + name, verilate)
        for forbidden in ("--public-flat-rw", "--no-assert", "-DVCS", "-DSYNTHESIS", "--trace", "-Wno-fatal"):
            self.assertNotIn(forbidden, verilate)
        self.assertIn("OPT_FAST=-O3", make)
        self.assertIn("CXX=/conda/bin/cxx", make)
        self.assertEqual(make[make.index("-j") + 1], "2")
        visibility = (build / "visibility.vlt").read_text()
        self.assertIn('-var "io_*"', visibility)
        self.assertNotIn('-var "*"', visibility)

    def test_child_environment_does_not_switch_clock_or_modify_parent(self):
        parent = dict(COCOTB_TESTCASE="other", GPI_EXTRA="bad", MAKEFLAGS="-j144",
                      COCOTB_TRUST_INERTIAL_WRITES="1", COCOTB_ENABLE_PROFILING="1")
        with patch.dict(os.environ, parent):
            env = adapter.child_environment(self.bundle, self.env)
            self.assertEqual(os.environ["COCOTB_TRUST_INERTIAL_WRITES"], "1")
        self.assertEqual(env["COCOTB_TRUST_INERTIAL_WRITES"], "0")
        self.assertEqual(env["CLOCK_NS"], "1.25")
        self.assertEqual(env["TCM_VCS_PACKAGE"], str(self.root))
        self.assertEqual(env["CXX"], "/conda/bin/cxx")
        for name in ("COCOTB_TESTCASE", "GPI_EXTRA", "MAKEFLAGS", "COCOTB_ENABLE_PROFILING"):
            self.assertNotIn(name, env)

    def test_identity_changes_for_compiler_and_not_ldd_addresses(self):
        first = adapter.build_identity(self.bundle, self.env)
        changed = copy.deepcopy(self.env)
        changed["ldd"] = {"lib": "different random address"}
        self.assertEqual(adapter.build_identity(self.bundle, changed), first)
        changed["cxx_version"] = "changed compiler"
        self.assertNotEqual(adapter.build_identity(self.bundle, changed), first)

    def create_build_and_pilot(self):
        state = adapter.state_directory(self.root)
        build = state / "builds/original"
        build.mkdir(parents=True)
        for name in (self.bundle.manifest["hdl_top"], "visibility.vlt", "compile-commands.json"):
            (build / name).write_text("synthetic model, NOT real HDL")
        record = dict(identity="identity", directory=str(build), model_files=adapter.model_hashes(self.bundle, build))
        adapter.write_json(state / "current_build.json", record)
        pilot = state / "runs/t12_r0.synthetic"
        pilot.mkdir(parents=True)
        reference = self.root.parent / "reference.log"
        reference.write_text(log(records()))
        (pilot / "_test.log").write_text(log(records()))
        (pilot / "results.xml").write_text('<testsuite><testcase name="tcm_workset_test"/></testsuite>')
        summaries = adapter.checked_results(self.bundle, self.env, pilot / "_test.log", 12, 0)
        result = dict(status="PASS", simulator="verilator", build_identity=record["identity"],
                      model_files=record["model_files"], manifest_sha256=adapter.sha(self.root / "manifest.json"),
                      adapter_sha256=adapter.sha(adapter.__file__), tiles=12, delay=0,
                      reference=adapter.checked_reference(self.bundle, self.env, reference, summaries, 12, 0),
                      timing=dict(exit_code=0, timed_out=False), summaries=summaries,
                      log_sha256=adapter.sha(pilot / "_test.log"), xml_sha256=adapter.sha(pilot / "results.xml"))
        adapter.write_json(pilot / "result.json", result)
        adapter.write_json(pilot / "_test-status.json", result["timing"])
        return state, build, record, pilot

    def test_checked_build_detects_tampered_binary(self):
        state, build, record, _ = self.create_build_and_pilot()
        self.assertEqual(adapter.checked_build(self.bundle, state, "identity")[1], build)
        (build / self.bundle.manifest["hdl_top"]).write_text("changed")
        with self.assertRaises(ValueError):
            adapter.checked_build(self.bundle, state, "identity")

    def test_large_gate_requires_complete_reference_matched_pilot(self):
        state, _, record, pilot = self.create_build_and_pilot()
        adapter.check_pilot(self.bundle, self.env, state, record)
        data = json.loads((pilot / "result.json").read_text())
        data["reference"] = None
        (pilot / "result.json").write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            adapter.check_pilot(self.bundle, self.env, state, record)

    def test_large_gate_rejects_changed_log_or_reference(self):
        state, _, record, pilot = self.create_build_and_pilot()
        reference = self.root.parent / "reference.log"
        reference.write_text(reference.read_text() + "changed\n")
        with self.assertRaises(ValueError):
            adapter.check_pilot(self.bundle, self.env, state, record)

    def test_new_evidence_is_never_overwritten(self):
        path = self.root / "evidence.json"
        adapter.write_json(path, {"first": 1})
        with self.assertRaises(FileExistsError):
            adapter.write_json(path, {"second": 2})
        self.assertEqual(json.loads(path.read_text()), {"first": 1})

    def test_unknown_verifier_rejected_before_import(self):
        (self.root / "package_lib.py").write_text("raise RuntimeError('MUST NOT IMPORT')")
        with self.assertRaisesRegex(ValueError, "unknown package verifier"):
            adapter.load_package(self.root)

    def test_failed_child_preserves_status_and_log(self):
        directory = self.root.parent / "failed"
        directory.mkdir()
        process = Mock(pid=123, wait=Mock(return_value=2))
        with patch.object(adapter.subprocess, "Popen", return_value=process):
            with self.assertRaises(ValueError):
                adapter.execute(self.bundle, self.env, "_test", directory, 30)
        timing = json.loads((directory / "_test-status.json").read_text())
        self.assertEqual(timing["exit_code"], 2)
        self.assertFalse(timing["timed_out"])
        self.assertTrue((directory / "_test.log").exists())
        self.assertFalse((directory / "result.json").exists())

    def test_timeout_terminates_only_own_session_and_keeps_evidence(self):
        directory = self.root.parent / "timeout"
        directory.mkdir()
        process = Mock(pid=54321)
        process.wait.side_effect = [adapter.subprocess.TimeoutExpired("test", 1), -15, -15]
        with patch.object(adapter.subprocess, "Popen", return_value=process), \
                patch.object(adapter.os, "killpg", create=True) as kill, \
                patch.object(adapter.signal, "SIGKILL", 9, create=True):
            with self.assertRaises(ValueError):
                adapter.execute(self.bundle, self.env, "_test", directory, 1)
        self.assertTrue(all(call.args[0] == 54321 for call in kill.call_args_list))
        self.assertTrue(json.loads((directory / "_test-status.json").read_text())["timed_out"])

    def test_existing_export_package_verifies_without_writing_vcs_files(self):
        """Synthetic package, real immutable exporter/verifier and CLI."""
        sys.path.insert(0, str(HERE.parent / "google_tcm_vcs"))
        import test_vcs_package as fixtures
        fixture = fixtures.PackageTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.export()
        before = {str(p.relative_to(fixture.output)): adapter.sha(p)
                  for p in fixture.output.rglob("*") if p.is_file()}
        result = adapter.subprocess.run([sys.executable, "-B", str(HERE / "verilator_workset.py"),
                                         "--package", str(fixture.output), "verify"],
                                        capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[TCM_VERILATOR_PACKAGE_VERIFIED]", result.stdout)
        self.assertEqual(before, {str(p.relative_to(fixture.output)): adapter.sha(p)
                                  for p in fixture.output.rglob("*") if p.is_file()})


@unittest.skipUnless(os.environ.get("TCM_VERILATOR_REAL_DEPS_CHECK") == "1", "optional real cocotb2.0 API")
class RealDependencyTests(unittest.TestCase):
    def test_real_runner_keeps_explicit_original_clock_policy(self):
        from cocotb_tools.runner import get_runner
        with tempfile.TemporaryDirectory() as temp:
            runner = get_runner("verilator")
            with patch.object(runner, "_execute"), patch.dict(os.environ, COCOTB_TRUST_INERTIAL_WRITES="0"):
                path = runner.test(hdl_toplevel="Example", hdl_toplevel_lang="verilog",
                                   test_module="workset_bench", testcase="tcm_workset_test", seed=137,
                                   build_dir=temp, test_dir=temp, results_xml=str(Path(temp) / "results.xml"),
                                   waves=False, gui=False, extra_env=dict(COCOTB_TRUST_INERTIAL_WRITES="0"))
            self.assertEqual(runner.env["COCOTB_TRUST_INERTIAL_WRITES"], "0")
            self.assertEqual(Path(path), Path(temp) / "results.xml")
            self.assertEqual(runner._test_command(), [[str(Path(temp) / "Example")]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
