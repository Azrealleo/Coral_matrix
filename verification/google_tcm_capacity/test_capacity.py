"""Local synthetic/static tests ONLY: not a Chisel/Verilator RTL run."""
import ast
import asyncio
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from capacity_spec import CAPACITIES, CSR_BASE, DTCM_BASE, UPSTREAM, geometry, probes
from capacity_spec import checked_parameters
from prepare import build_text, checked_log, experiment_sources


class CapacityTests(unittest.TestCase):
    def test_geometry(self):
        for kib in CAPACITIES:
            g = geometry(kib)
            self.assertEqual(g["dtcm_banks"], kib // 8)
            self.assertLessEqual(DTCM_BASE + kib * 1024, CSR_BASE)
            self.assertEqual(g["itcm_kib"], 8)
        self.assertEqual(geometry(2048)["dtcm_banks"], 256)
        self.assertEqual(geometry(4096)["dtcm_banks"], 512)
        with self.assertRaises(ValueError):
            geometry(2000)

    def test_probe_coverage_and_distinct_words(self):
        for kib in CAPACITIES:
            words = probes(kib)
            self.assertEqual(len(words), 2 + 3 * kib // 8)
            self.assertEqual(len({a for a, _ in words}), len(words))
            self.assertEqual(len({b for _, b in words}), len(words))
            self.assertIn(DTCM_BASE + kib * 1024 - 16, dict(words))
            self.assertTrue(all(a % 16 == 0 and len(b) == 16 for a, b in words))

    def test_generated_build_syntax_and_identity(self):
        for kib in CAPACITIES:
            text = build_text(kib)
            ast.parse(text)
            self.assertIn(geometry(kib)["hdl_top"], text)
            self.assertIn(f"--dtcmSizeKBytes={kib}", text)
            self.assertIn("-DZVTBF16FMM_ON", text)
            self.assertNotIn("--enableVerification=True", text)
        ast.parse((HERE / "capacity_bench.py").read_text(encoding="utf-8"))

    def test_real_upstream_rewrite_is_generator_only(self):
        metadata = HERE.parent.parent / ".upstream-git/coralnpu-google.git"
        if not metadata.exists():
            self.skipTest("optional local upstream Git metadata is absent")
        def blob(path):
            return subprocess.check_output(["git", "--git-dir=" + str(metadata),
                                            "show", UPSTREAM + ":" + path]).decode()
        core = blob("hdl/chisel/src/coralnpu/Core.scala")
        linker = blob("rules/linker.bzl")
        changed, ld = experiment_sources(core, linker)
        self.assertEqual(core.split("object EmitCore")[0], changed.split("object EmitCore")[0])
        self.assertEqual(core.split("  // The core module must be created")[1],
                         changed.split("  // The core module must be created")[1])
        self.assertIn("0x01000000", changed)
        self.assertIn("0x02000000", changed)
        self.assertEqual(ld.count('= "0x01000000"'), 2)
        with self.assertRaises(ValueError):
            experiment_sources(changed, ld)

    def test_parameters_reject_wrong_capacity_and_verification(self):
        expected = dict(xlen="32", axi2IdBits="6", itcmSizeKBytes="8", dtcmSizeKBytes="2048",
                        enableVerification="false", enableRvv="true", enableVme="true",
                        rvvVlen="128", enableFloat="true", enableZfbfmin="true",
                        enableVectorBf16="true", enableAxiInstructionFetch="true",
                        enableFetchL0="false", fetchDataBits="128", lsuDataBits="128")
        text = "\n".join(f"#define KP_{k} {v}" for k, v in expected.items())
        self.assertEqual(checked_parameters(text, 2048), expected)
        for changed in (text.replace("2048", "32"), text.replace("false", "true")):
            with self.assertRaises(ValueError):
                checked_parameters(changed, 2048)

    def run_fake_bench(self, kib, alias=False):
        class Log:
            def __init__(self): self.lines = []
            def info(self, line): self.lines.append(line)
        dut = types.SimpleNamespace(_log=Log())
        class FakeFixture:
            def __init__(self): self.data = {}
            @classmethod
            async def Create(cls, dut, **kw):
                if kw["csr_base_addr"] != CSR_BASE:
                    raise AssertionError("wrong CSR")
                return cls()
            async def read_word(self, addr):
                if addr != CSR_BASE: raise AssertionError("wrong CSR")
                return 3
            def physical(self, addr):
                return DTCM_BASE + (addr - DTCM_BASE) % 32768 if alias and addr >= DTCM_BASE else addr
            async def write(self, addr, data):
                for i, value in enumerate(data): self.data[self.physical(addr + i)] = int(value)
            async def read(self, addr, size):
                return np.array([self.data[self.physical(addr + i)] for i in range(size)], dtype=np.uint8)
        c = types.ModuleType("cocotb")
        c.test = lambda **kw: (lambda fn: fn)
        package = types.ModuleType("coralnpu_test_utils")
        backend = types.ModuleType("coralnpu_test_utils.sim_backends")
        fixture_module = types.ModuleType("coralnpu_test_utils.sim_backends.verilator_test_fixture")
        fixture_module.VerilatorTestFixture = FakeFixture
        modules = {"cocotb": c, "coralnpu_test_utils": package,
                   "coralnpu_test_utils.sim_backends": backend,
                   "coralnpu_test_utils.sim_backends.verilator_test_fixture": fixture_module}
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {"TCM_DTCM_KIB": str(kib)}):
            spec = importlib.util.spec_from_file_location("capacity_test_fake", HERE / "capacity_bench.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            asyncio.run(module.tcm_capacity_test(dut))
        return dut._log.lines

    def test_fake_frontdoor_all_capacities(self):
        for kib in CAPACITIES:
            lines = self.run_fake_bench(kib)
            self.assertTrue(any("GOOGLE_TCM_CAPACITY_CHECK" in s for s in lines))

    def test_fake_frontdoor_rejects_high_address_alias(self):
        with self.assertRaisesRegex(AssertionError, "mismatch/alias"):
            self.run_fake_bench(128, alias=True)

    def test_strict_log_parser(self):
        import json
        good = "\n".join(self.run_fake_bench(2048)) + "\nTESTS=1 PASS=1 FAIL=0 SKIP=0\n"
        row = checked_log(good, 2048)
        self.assertEqual(row["checked_words"], 770)
        for bad in (good.replace("FAIL=0", "FAIL=1"),
                    good.replace("SKIP=0", "SKIP=1"),
                    good.replace("[GOOGLE_TCM_CAPACITY_CHECK] passed", ""), good + good):
            with self.assertRaises(ValueError): checked_log(bad, 2048)
        for key, value in (("dtcm_kib", 32), ("checked_words", 2),
                           ("byte_mask_cases", 0), ("schema", True),
                           ("scope", "performance")):
            changed = dict(row, **{key: value})
            bad = "[GOOGLE_TCM_CAPACITY] " + json.dumps(changed) + "\n[GOOGLE_TCM_CAPACITY_CHECK] passed\nTESTS=1 PASS=1 FAIL=0 SKIP=0"
            with self.assertRaises(ValueError): checked_log(bad, 2048)


if __name__ == "__main__":
    unittest.main(verbosity=2)
