"""Local static/synthetic checks; NOT actual Chisel/Verilator simulation."""
import ast
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import itcm_spec as spec
import prepare_itcm as installer


def result(kib=8):
    row = dict(spec.geometry(kib), schema=1, scope=spec.SCOPE, status="PASS",
               core_started=False, checked_words=len(spec.probes(kib)),
               checked_bytes=16 * len(spec.probes(kib)), byte_mask_cases=4)
    return row


def log(row):
    return ("[GOOGLE_ITCM_GEOMETRY] " + json.dumps(row) +
            "\n[GOOGLE_ITCM_GEOMETRY_CHECK] passed\nTESTS=1 PASS=1 FAIL=0 SKIP=0\n")


class ItcmTests(unittest.TestCase):
    def test_geometry_only_itcm_varies(self):
        for kib in spec.CAPACITIES:
            g = spec.geometry(kib)
            self.assertEqual(g["itcm_bytes"], kib * 1024)
            self.assertEqual(g["dtcm_kib"], 2048)
            self.assertEqual(g["dtcm_base"], 0x01000000)
            self.assertEqual(g["csr_base"], 0x02000000)
            self.assertLess(g["itcm_bytes"], g["dtcm_base"])
        for bad in (True, 0, 4, 12, 256, "8"):
            with self.assertRaises(ValueError):
                spec.geometry(bad)

    def test_probes_cover_every_slice_and_dtcm_guards(self):
        for kib in spec.CAPACITIES:
            words = spec.probes(kib)
            addresses = dict(words)
            self.assertEqual(len(words), 3 * (kib // 8) + 2)
            self.assertEqual(len(addresses), len(words))
            self.assertEqual(len({data for _, data in words}), len(words))
            for start in range(0, kib * 1024, 8192):
                for addr in (start, start + 4096, start + 8176):
                    self.assertIn(addr, addresses)
            for addr in spec.mask_addresses(kib):
                self.assertIn(addr, addresses)
            self.assertTrue(all(a % 16 == 0 and len(b) == 16 for a, b in words))

    def test_header_checks_all_existing_settings(self):
        for kib in spec.CAPACITIES:
            expected = dict(xlen="32", axi2IdBits="6", itcmSizeKBytes=str(kib),
                            dtcmSizeKBytes="2048", enableVerification="false",
                            enableRvv="true", enableVme="true", rvvVlen="128",
                            enableFloat="true", enableZfbfmin="true", enableVectorBf16="true",
                            enableAxiInstructionFetch="true", enableFetchL0="false",
                            fetchDataBits="128", lsuDataBits="128")
            header = "\n".join(f"#define KP_{k} {v}" for k, v in expected.items())
            self.assertEqual(spec.checked_parameters(header, kib), expected)
            for key, value in expected.items():
                with self.assertRaises(ValueError):
                    spec.checked_parameters(header.replace(f"KP_{key} {value}", f"KP_{key} WRONG"), kib)

    def test_generated_build_is_valid_and_keeps_common_configuration(self):
        for kib in spec.CAPACITIES:
            text = installer.itcm_build(kib)
            ast.parse(text)
            self.assertIn(f"--itcmSizeKBytes={kib}", text)
            self.assertIn("--dtcmSizeKBytes=2048", text)
            self.assertIn(spec.geometry(kib)["hdl_top"], text)
            self.assertIn('testcases = ["itcm_geometry_test"]', text)
            self.assertIn(f"TCM_ITCM_KIB={kib}", text)
            self.assertIn('srcs = ["itcm_spec.py"]', text)
            self.assertIn("VME_CORE_MINI_AXI_COMMON_GEN_FLAGS", text)
            self.assertIn("-DZVTBF16FMM_ON", text)
            self.assertNotIn("capacity_spec.py", text)
            self.assertNotIn("TCM_DTCM_KIB=", text)
            if kib != 8:
                self.assertNotIn("VmeCoreMini_ITCM8KB", text)

    def test_result_requires_exact_configuration_and_checks(self):
        for kib in spec.CAPACITIES:
            row = result(kib)
            self.assertEqual(installer.checked_log(log(row), kib), row)
            for key in row:
                bad = copy.deepcopy(row)
                bad[key] = "wrong"
                with self.assertRaises(ValueError):
                    installer.checked_log(log(bad), kib)

    def test_result_rejects_missing_failed_skipped_extra_and_colored_data(self):
        good = log(result())
        samples = ("", good + good, good.replace("FAIL=0", "FAIL=1"),
                   good.replace("SKIP=0", "SKIP=1"), good.replace("TESTS=1", "TESTS=2"),
                   good.replace("[GOOGLE_ITCM_GEOMETRY_CHECK] passed", ""),
                   good.replace('"core_started": false', '"core_started": 0'),
                   good.replace('"schema": 1', '"schema": true'),
                   good.replace('\n[GOOGLE_ITCM_GEOMETRY_CHECK]', 'garbage\n[GOOGLE_ITCM_GEOMETRY_CHECK]'))
        for text in samples:
            with self.assertRaises(ValueError):
                installer.checked_log(text, 8)
        line = good.splitlines()[0] + "\x1b[0m\n" + "\n".join(good.splitlines()[1:])
        with self.assertRaises(ValueError):
            installer.checked_log(line, 8)

    def test_prepare_preserves_existing_files_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            root.mkdir()
            old = root / "Core.scala"
            old.write_bytes(b"unchanged RTL")
            evidence_dir = root.parent / "run_d2048.original"
            evidence_dir.mkdir()
            evidence_log = b"original passed evidence"
            (evidence_dir / "test.log").write_bytes(evidence_log)
            evidence = dict(directory=str(evidence_dir), test_log_sha256=installer.digest(evidence_log))
            with patch.object(installer, "base_identity", return_value="base"), \
                    patch.object(installer, "stage1_evidence", return_value=evidence), \
                    patch("prepare.checked_log"):
                manifest = installer.prepare(root)
                before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
                self.assertEqual(installer.prepare(root), manifest)
                self.assertEqual(before, {p: p.read_bytes() for p in root.rglob("*") if p.is_file()})
                self.assertEqual(old.read_bytes(), b"unchanged RTL")
                target = root / spec.geometry(16)["package"] / "BUILD"
                target.write_bytes(target.read_bytes() + b"# changed")
                with self.assertRaises(ValueError):
                    installer.verify(root)
                self.assertTrue(target.read_bytes().endswith(b"# changed"))

    def test_partial_install_is_preserved_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / spec.geometry(8)["package"]
            target.mkdir(parents=True)
            sentinel = target / "old.txt"
            sentinel.write_bytes(b"user data")
            with patch.object(installer, "base_identity", return_value="base"), \
                    patch.object(installer, "stage1_evidence", return_value={}):
                with self.assertRaises(ValueError):
                    installer.prepare(root)
            self.assertEqual(sentinel.read_bytes(), b"user data")
            self.assertFalse((root / installer.MANIFEST).exists())

    def test_runner_has_reuse_failfast_and_failure_evidence(self):
        text = (HERE / "run.sh").read_text()
        for required in ("--noblock_for_lock", "--noshow_progress", "--jobs=2",
                         "--cache_test_results=no", "--test_timeout=21600", "PIPESTATUS",
                         "test-exit-status.txt", "[ITCM_INCOMPLETE]", "[ITCM_GEOMETRY_PASS]"):
            self.assertIn(required, text)
        for forbidden in ("git pull", "git checkout", "git reset", "rm -rf", "--quiet"):
            self.assertNotIn(forbidden, text)

    def test_original_generator_supports_size_and_dynamic_memory_region(self):
        bare = HERE.parent.parent / ".upstream-git/coralnpu-google.git"
        if not bare.exists():
            self.skipTest("optional local upstream metadata absent")
        core = subprocess.check_output(["git", "--git-dir=" + str(bare), "show",
                                        spec.UPSTREAM + ":hdl/chisel/src/coralnpu/Core.scala"]).decode()
        self.assertIn('arg.startsWith("--itcmSizeKBytes")', core)
        from prepare import experiment_sources
        linker = subprocess.check_output(["git", "--git-dir=" + str(bare), "show",
                                          spec.UPSTREAM + ":rules/linker.bzl"]).decode()
        modified, _ = experiment_sources(core, linker)
        self.assertIn("p.itcmSizeKBytes * 1024", modified)

    def test_bench_is_geometry_not_execution(self):
        text = (HERE / "itcm_bench.py").read_text()
        ast.parse(text)
        self.assertNotIn("run_to_halt(", text)
        self.assertNotIn("backdoor_load(", text)
        self.assertIn("core_started=False", text)
        self.assertLess(text.index("for addr, data in expected.items():"),
                        text.index("actual = await fixture.read"))

    def run_synthetic_bench(self, kib, alias=False, corrupt_mask=False):
        """Exercise the actual coroutine against a byte-addressed fake, not RTL."""
        class Memory:
            def __init__(self):
                self.data = {}

            def address(self, addr):
                return addr % 8192 if alias and addr < spec.DTCM_BASE else addr

            async def write(self, addr, data):
                for i, value in enumerate(bytes(data)):
                    self.data[self.address(addr + i)] = value
                if corrupt_mask and len(data) == 7:
                    previous = self.address(addr - 1)
                    self.data[previous] ^= 1

            async def read(self, addr, size):
                return bytes(self.data.get(self.address(addr + i), 0) for i in range(size))

            async def read_word(self, addr):
                return 3

        memory = Memory()

        class Factory:
            @staticmethod
            async def Create(dut, csr_base_addr):
                return memory

        fake_cocotb = types.ModuleType("cocotb")
        fake_cocotb.test = lambda **kwargs: lambda function: function
        fixture_name = "coralnpu_test_utils.sim_backends.verilator_test_fixture"
        fixture = types.ModuleType(fixture_name)
        fixture.VerilatorTestFixture = Factory
        modules = {"cocotb": fake_cocotb, fixture_name: fixture}
        messages = []
        module_spec = importlib.util.spec_from_file_location("itcm_synthetic_bench", HERE / "itcm_bench.py")
        module = importlib.util.module_from_spec(module_spec)
        with patch.dict(sys.modules, modules), patch.dict("os.environ", TCM_ITCM_KIB=str(kib)):
            module_spec.loader.exec_module(module)
            asyncio.run(module.itcm_geometry_test(types.SimpleNamespace(
                _log=types.SimpleNamespace(info=messages.append))))
        return installer.checked_log("\n".join(messages) + "\nTESTS=1 PASS=1 FAIL=0 SKIP=0", kib)

    def test_actual_bench_coroutine_synthetic_passes_all_sizes(self):
        for kib in spec.CAPACITIES:
            self.assertEqual(self.run_synthetic_bench(kib), result(kib))

    def test_actual_bench_coroutine_detects_address_alias(self):
        with self.assertRaises(AssertionError):
            self.run_synthetic_bench(16, alias=True)

    def test_actual_bench_coroutine_detects_bad_byte_mask(self):
        with self.assertRaises(AssertionError):
            self.run_synthetic_bench(8, corrupt_mask=True)


if __name__ == "__main__":
    unittest.main()
