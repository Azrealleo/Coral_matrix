"""Stage2a local synthetic/static checks; no claim of RTL or RISC-V compile."""
import ast
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from capacity_spec import CAPACITIES, DTCM_BASE
from control_spec import REPEATS, SCOPE, SYMBOL_SIZES, cases, check_layout, reference, vector_hash
import prepare_control as control


def symbols():
    result, cursor = {}, DTCM_BASE
    for name, size in SYMBOL_SIZES.items():
        result[name] = cursor
        cursor += (size + 15) // 16 * 16
    return result


def synthetic_rows(kib=32):
    rows = []
    for name, a, b in cases():
        k = a.shape[1]
        for repeat in range(REPEATS):
            rows.append(dict(schema=1, status="PASS", dtcm_kib=kib, itcm_kib=8,
                             case=name, K=k, M=16, N=16, repeat=repeat, checked_elements=256,
                             useful_macs=k*256, active_matrix_bytes=k*32+1024,
                             reserved_buffer_bytes=9344, vector_sha256=vector_hash(a, b),
                             elf_sha256="a"*64, symbols=symbols(), elf_entry=0,
                             elf_load_segments=[[0, 8192], [DTCM_BASE, 32768]],
                             wait_for_halt_cycles=1000+k, scope=SCOPE,
                             input_schedule="host_frontdoor_preloaded_low_dtcm32k",
                             elf_loading="frontdoor", itcm_tail="full_8k_nop_before_elf"))
    return rows


def as_log(rows, skip=0):
    return "\n".join("[GOOGLE_TCM_CONTROL] " + json.dumps(row) for row in rows) + (
        f"\n[GOOGLE_TCM_CONTROL_CHECK] cases=4 repeats=3 passed\n"
        f"TESTS=1 PASS=1 FAIL=0 SKIP={skip}\n")


class ControlTests(unittest.TestCase):
    def fake_bench(self, corrupt=False):
        class Log:
            def __init__(self): self.lines = []
            def info(self, message): self.lines.append(message)
        dut = types.SimpleNamespace(_log=Log())
        class FakeFixture:
            def __init__(self):
                self.core_mini_axi = self
                self.symbols, self.symbol_sizes = symbols(), dict(SYMBOL_SIZES)
                self.data = {}
            @classmethod
            async def Create(cls, dut, **kwargs): return cls()
            async def reset(self): pass
            async def load_elf_and_lookup_symbols(self, path, names, optional):
                assert not optional and set(names) == set(SYMBOL_SIZES)
            async def write(self, symbol, data): self.data[symbol] = np.asarray(data).copy()
            async def write_word(self, symbol, data): self.data[symbol] = data
            async def read_word(self, symbol): return self.data[symbol]
            async def run_to_halt(self, **kwargs):
                k = self.data["ctrl_k"]
                a = self.data["ctrl_a"].view(np.int8).reshape(260, 16)[:k].T
                b = self.data["ctrl_b"].view(np.int8).reshape(260, 16)[:k]
                self.data["ctrl_out"] = reference(a, b).copy()
                if corrupt: self.data["ctrl_out"][0, 0] ^= 1
                self.data.update(ctrl_status=1, ctrl_mtype=(16 << 10) | (4 << 5) | 3, ctrl_vtype=0x1C0)
                return 1000 + k
            async def read(self, symbol, **kwargs): return self.data[symbol]
            def fault(self): return False
        with tempfile.TemporaryDirectory() as temp:
            elf_path = Path(temp) / "synthetic.elf"
            elf_path.write_bytes(b"synthetic; not an actual ELF")
            names = ["cocotb", "bazel_tools", "bazel_tools.tools", "bazel_tools.tools.python",
                     "bazel_tools.tools.python.runfiles", "elftools", "elftools.elf", "elftools.elf.elffile",
                     "coralnpu_test_utils", "coralnpu_test_utils.sim_backends",
                     "coralnpu_test_utils.sim_backends.verilator_test_fixture"]
            modules = {name: types.ModuleType(name) for name in names}
            modules["cocotb"].test = lambda **kw: (lambda fn: fn)
            modules["bazel_tools.tools.python.runfiles"].runfiles = types.SimpleNamespace(
                Create=lambda: types.SimpleNamespace(Rlocation=lambda _: str(elf_path)))
            modules["elftools.elf.elffile"].ELFFile = None
            modules["coralnpu_test_utils.sim_backends.verilator_test_fixture"].VerilatorTestFixture = FakeFixture
            with patch.dict(sys.modules, modules), patch.dict(os.environ, {"TCM_DTCM_KIB": "32", "COCOTB_USE_FRONTDOOR": "1"}):
                spec = importlib.util.spec_from_file_location("control_fake_bench", HERE / "control_bench.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.elf_layout = lambda _: (0, [(0, 8192), (DTCM_BASE, 32768)])
                asyncio.run(module.tcm_control_test(dut))
        return "\n".join(dut._log.lines) + "\nTESTS=1 PASS=1 FAIL=0 SKIP=0\n"

    def test_synthetic_bench_emits_strictly_parseable_results(self):
        rows, _ = control.checked_control_log(self.fake_bench(), 32)
        self.assertEqual(len(rows), 4)

    def test_synthetic_bench_rejects_corrupted_output(self):
        with self.assertRaises(AssertionError):
            self.fake_bench(corrupt=True)

    def test_vectors_are_signed_and_widened(self):
        self.assertEqual(len(cases()), 4)
        for name, a, b in cases():
            self.assertTrue(np.any(a < 0) and np.any(a > 0), name)
            self.assertTrue(np.any(b < 0) and np.any(b > 0), name)
            self.assertEqual(reference(a, b).shape, (16, 16))
            self.assertEqual(len(vector_hash(a, b)), 64)
        a = np.full((16, 256), -128, dtype=np.int8)
        np.testing.assert_array_equal(reference(a, a.T), np.full((16, 16), 4194304))

    def test_builds_use_same_program_and_generator(self):
        for kib in CAPACITIES:
            text = control.control_build(kib)
            ast.parse(text)
            self.assertIn(f"--dtcmSizeKBytes={kib}", text)
            self.assertIn('"COCOTB_USE_FRONTDOOR=1"', text)
            self.assertIn('//tests/cocotb/tcm_control:control_program.elf', text)
            self.assertIn('testcases = ["tcm_control_test"]', text)
            self.assertIn('"control_spec.py"', text)
            self.assertNotIn('"capacity_bench.py"', text)
            self.assertIn('-DZVTBF16FMM_ON', text)
        ast.parse((HERE / "control_bench.py").read_text())

    def test_layout_rejects_external_or_large_residency(self):
        segments = [(0, 8192), (DTCM_BASE, 32768)]
        check_layout(segments, 0, symbols(), SYMBOL_SIZES, DTCM_BASE)
        for bad in (segments + [(0x20000000, 16)], [(0, 8192), (DTCM_BASE, 32769)], []):
            with self.assertRaises(ValueError):
                check_layout(bad, 0, symbols(), SYMBOL_SIZES, DTCM_BASE)
        for entry in (8192, 0x20000000):
            with self.assertRaises(ValueError):
                check_layout(segments, entry, symbols(), SYMBOL_SIZES, DTCM_BASE)

    def test_layout_rejects_overlap_and_unaligned_symbols(self):
        segments = [(0, 8192), (DTCM_BASE, 32768)]
        wrong = symbols()
        wrong["ctrl_b"] = wrong["ctrl_a"]
        with self.assertRaises(ValueError):
            check_layout(segments, 0, wrong, SYMBOL_SIZES, DTCM_BASE)
        wrong = symbols()
        wrong["ctrl_a"] += 1
        with self.assertRaises(ValueError):
            check_layout(segments, 0, wrong, SYMBOL_SIZES, DTCM_BASE)

    def test_log_requires_full_correct_repeatable_control(self):
        for kib in CAPACITIES:
            rows, _ = control.checked_control_log(as_log(synthetic_rows(kib)), kib)
            self.assertEqual(len(rows), 4)
        for key, value in (("vector_sha256", "b"*64), ("scope", "capacity_benefit"),
                           ("wait_for_halt_cycles", True), ("elf_sha256", "b"*64),
                           ("wait_for_halt_cycles", 5), ("elf_loading", "backdoor"),
                           ("repeat", 1), ("dtcm_kib", 4096)):
            wrong = synthetic_rows()
            wrong[0][key] = value
            with self.assertRaises(ValueError, msg=key):
                control.checked_control_log(as_log(wrong), 32)
        for text in (as_log(synthetic_rows()[:-1]), as_log(synthetic_rows(), skip=1),
                     as_log(synthetic_rows()) + as_log(synthetic_rows())):
            with self.assertRaises(ValueError):
                control.checked_control_log(text, 32)

    def test_install_is_separate_idempotent_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            root.mkdir()
            (root / "tcm_capacity_manifest.json").write_text('{"stage1": 1}\n')
            base = (root / "tcm_capacity_manifest.json").read_bytes()
            with patch.object(control, "verify_capacity"), patch.object(control, "git", return_value=b"pinned header"), \
                    patch.object(control, "stage1_evidence", return_value={"directory": "synthetic-not-rtl"}):
                first = control.prepare(root)
                self.assertEqual(control.prepare(root), first)
                self.assertEqual((root / "tcm_capacity_manifest.json").read_bytes(), base)
                self.assertEqual(len(first["files"]), 27)
                ast.parse((root / control.PACKAGE / "BUILD").read_text())
                (root / control.PACKAGE / "control_program.cc").write_text("tamper")
                with self.assertRaises(ValueError):
                    control.verify(root)

    def test_install_refuses_partial_or_missing_stage1_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            root.mkdir()
            (root / "tcm_capacity_manifest.json").write_text('{}')
            with self.assertRaises(ValueError):
                control.stage1_evidence(root, 32)
            with patch.object(control, "verify_capacity"), patch.object(control, "git", return_value=b"header"), \
                    patch.object(control, "stage1_evidence", return_value={}):
                path = root / control.PACKAGE / "BUILD"
                path.parent.mkdir(parents=True)
                path.write_text("user file")
                with self.assertRaises(ValueError):
                    control.prepare(root)
                self.assertEqual(path.read_text(), "user file")

    def test_runner_preserves_quiet_and_strict_mode(self):
        script = (HERE / "run_control.sh").read_text()
        self.assertIn("set -euo pipefail", script)
        self.assertIn("--noshow_progress", script)
        self.assertIn("--cache_test_results=no --test_output=errors", script)
        self.assertNotIn("git clone", script)
        self.assertNotRegex(script, r"(?m)^\s*(?:sudo[ \t]+)?rm(?:[ \t]|$)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
