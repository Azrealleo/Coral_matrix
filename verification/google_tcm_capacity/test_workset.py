"""Local synthetic/static workset tests, not actual RISC-V/RTL execution."""
import ast
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from capacity_spec import CAPACITIES, DTCM_BASE
import prepare_workset as installer
from workset_spec import (EXT_A, EXT_B, EXT_OUT, EXT_BYTES, K, LOW_DTCM_BYTES,
                          REPEATS, ROUNDS, SCOPE, STRATEGIES, SYMBOL_SIZES, TILE_CHOICES,
                          TrafficCounter, check_elf_layout, plan, vectors)
from resolve_bazel_elf import resolve_elf


def layout():
    symbols, cursor = {}, DTCM_BASE
    for name, size in SYMBOL_SIZES.items():
        symbols[name] = cursor
        cursor += (size + 15) // 16 * 16
    return 0, [[0, 8192], [DTCM_BASE, 16384]], symbols, dict(SYMBOL_SIZES)


def fake_traffic(config):
    c = TrafficCounter(config["tiles"])
    for prefix, base, max_bytes in (("input", EXT_A, ROUNDS * 4096),
                                     ("weight", EXT_B, config["tiles"] * 4096)):
        remaining = config[prefix + "_read_bytes"]
        address = base
        while remaining:
            size = min(4096, remaining, base + max_bytes - address)
            c.ar(address, 4, size // 16 - 1, 3)
            for beat in range(size // 16): c.r(3, beat == size // 16 - 1, 0)
            remaining -= size
            address = base if address + size == base + max_bytes else address + size
    remaining, address = config["output_write_bytes"], EXT_OUT
    while remaining:
        size = min(4096, remaining)
        c.aw(address, 4, size // 16 - 1, 7)
        for _ in range(size // 16): c.w(0xFFFF)
        c.b(7, 0)
        remaining -= size
        address += size
    return c.finish(config)


def synthetic_record(kib=32, tiles=12, strategy="stream", repeat=0, delay=0):
    config = plan(kib, tiles, strategy)
    entry, segments, symbols, _ = layout()
    # Chosen synthetic windows only, never real NPU performance numbers.
    counters = dict(ws_input_bytes=config["input_read_bytes"], ws_weight_bytes=config["weight_read_bytes"],
                    ws_output_bytes=config["output_write_bytes"], ws_input_cycles=10,
                    ws_weight_cycles=config["weight_read_bytes"]//16,
                    ws_compute_cycles=1000, ws_output_cycles=200, ws_total_cycles=20000)
    return dict(config, schema=1, status="PASS", repeat=repeat, itcm_kib=8,
                read_delay_cycles=delay, scope=SCOPE, elf_sha256="a"*64,
                vector_sha256=vectors(tiles)[3], elf_entry=entry, symbols=symbols,
                elf_load_segments=segments, wait_for_halt_cycles=21000,
                csr_counters=counters, round_cycles=[6000, 6000, 6000], axi=fake_traffic(config),
                external_memory_bytes=EXT_BYTES, elf_loading="frontdoor",
                input_schedule="round_outer_weight_tile_inner_outputs_external",
                timing="cold_start_copies_compute_output_included_host_init_excluded")


def rows():
    return [synthetic_record(strategy=s, repeat=r) for s in STRATEGIES for r in range(REPEATS)]


def log(records):
    return "\n".join("[GOOGLE_TCM_WORKSET] " + json.dumps(r) for r in records) + (
        "\n[GOOGLE_TCM_WORKSET_CHECK] tiles=12 strategies=2 repeats=3 passed\n"
        "TESTS=1 PASS=1 FAIL=0 SKIP=0\n")


class WorksetTests(unittest.TestCase):
    def compare_cli(self, other_records, duplicate=False):
        with tempfile.TemporaryDirectory() as temp:
            one, two = Path(temp) / "one.log", Path(temp) / "two.log"
            one.write_text(log(rows()))
            two.write_text(log(other_records))
            return subprocess.run([sys.executable, "-B", str(HERE / "prepare_workset.py"), "compare", "--logs",
                                   str(one), str(one if duplicate else two)], capture_output=True, text=True)

    def test_compare_cli_accepts_matching_workload(self):
        other = [synthetic_record(kib=128, strategy=s, repeat=r) for s in STRATEGIES for r in range(REPEATS)]
        result = self.compare_cli(other)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("[TCM_WORKSET_COMPARE]"), 2)

    def test_compare_cli_rejects_different_elf_and_delay(self):
        for key, value in (("elf_sha256", "b"*64), ("read_delay_cycles", 8)):
            other = [synthetic_record(kib=128, strategy=s, repeat=r) for s in STRATEGIES for r in range(REPEATS)]
            for row in other: row[key] = value
            self.assertNotEqual(self.compare_cli(other).returncode, 0)

    def test_compare_cli_rejects_duplicate_capacity(self):
        self.assertNotEqual(self.compare_cli(rows(), duplicate=True).returncode, 0)

    def fake_bench(self, corrupt=False):
        class Log:
            def __init__(self): self.lines = []
            def info(self, message): self.lines.append(message)
        dut = types.SimpleNamespace(_log=Log())
        class FakeFixture:
            def __init__(self):
                self.core_mini_axi = self
                self.data = {}
                self.symbols = dict(layout()[2], _sim_exit_code=DTCM_BASE+10000)
                self.symbol_sizes = dict(SYMBOL_SIZES, _sim_exit_code=4)
            @classmethod
            async def Create(cls, dut, **kwargs):
                assert kwargs["ext_mem_size"] == EXT_BYTES
                return cls()
            async def reset(self): pass
            async def load_elf_and_lookup_symbols(self, path, names, optional):
                self.data = {}
            async def write(self, symbol, data): self.data[symbol] = np.asarray(data).copy()
            async def write_word(self, symbol, value): self.data[symbol] = value
            async def read_word(self, symbol): return self.data[symbol]
            async def run_to_halt(self, **kwargs):
                strategy = "prefix_cache" if self.data["ws_cache"] else "stream"
                record = synthetic_record(strategy=strategy)
                a = self.data[EXT_A].view(np.int8).reshape(3, 256, 16).transpose(0, 2, 1)
                b = self.data[EXT_B].view(np.int8).reshape(12, 256, 16)
                expected = (a.astype(np.int64)[:, None] @ b.astype(np.int64)[None]).astype("<i4")
                if corrupt: expected[0, 0, 0, 0] ^= 1
                self.data[EXT_OUT] = expected
                self.data.update(record["csr_counters"])
                self.data["ws_round_cycles"] = np.array(record["round_cycles"], dtype="<u4")
                self.data["ws_status"] = 1
                return record["wait_for_halt_cycles"]
            async def read(self, symbol, **kwargs): return self.data[symbol]
            def fault(self): return False
        class FakeProbe:
            def __init__(self, dut, tiles): pass
            def start(self): pass
            def stop(self, config): return fake_traffic(config)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "synthetic.elf"
            path.write_bytes(b"synthetic; not RISC-V or RTL")
            names = ["cocotb", "bazel_tools", "bazel_tools.tools", "bazel_tools.tools.python",
                     "bazel_tools.tools.python.runfiles", "elftools", "elftools.elf", "elftools.elf.elffile",
                     "coralnpu_test_utils", "coralnpu_test_utils.sim_backends",
                     "coralnpu_test_utils.sim_backends.verilator_test_fixture", "workset_axi_probe"]
            modules = {n: types.ModuleType(n) for n in names}
            modules["cocotb"].test = lambda **kw: (lambda fn: fn)
            modules["bazel_tools.tools.python.runfiles"].runfiles = types.SimpleNamespace(
                Create=lambda: types.SimpleNamespace(Rlocation=lambda _: str(path)))
            modules["elftools.elf.elffile"].ELFFile = None
            modules["coralnpu_test_utils.sim_backends.verilator_test_fixture"].VerilatorTestFixture = FakeFixture
            modules["workset_axi_probe"].WorksetAxiProbe = FakeProbe
            env = dict(TCM_DTCM_KIB="32", TCM_WS_TILES="12", TCM_WS_READ_DELAY="0", COCOTB_USE_FRONTDOOR="1")
            with patch.dict(sys.modules, modules), patch.dict(os.environ, env):
                spec = importlib.util.spec_from_file_location("synthetic_workset_bench", HERE / "workset_bench.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.inspect_elf = lambda _: layout()
                asyncio.run(module.tcm_workset_test(dut))
        return "\n".join(dut._log.lines) + "\nTESTS=1 PASS=1 FAIL=0 SKIP=0\n"

    def test_synthetic_full_bench_and_log_roundtrip(self):
        result, _ = installer.checked_log(self.fake_bench(), 32, 12, 0)
        self.assertEqual(len(result), 2)

    def test_synthetic_full_bench_rejects_wrong_output(self):
        with self.assertRaises(AssertionError): self.fake_bench(corrupt=True)

    def test_probe_counts_only_accepting_edges(self):
        dut = types.SimpleNamespace(io_aclk=object())
        channels = dict(read_addr=("addr", "size", "len", "id"),
                        write_addr=("addr", "size", "len", "id"),
                        read_data=("id", "last", "resp"), write_data=("strb",),
                        write_resp=("id", "resp"))
        signals = {}
        for channel, fields in channels.items():
            prefix = "io_axi_master_" + channel
            for suffix in ("_valid", "_ready", *("_bits_" + f for f in fields)):
                name = prefix + suffix
                signals[name] = types.SimpleNamespace(value=0)
                setattr(dut, name, signals[name])
        def sample(channel, ready, **fields):
            prefix = "io_axi_master_" + channel
            return {prefix + "_valid": 1, prefix + "_ready": ready,
                    **{prefix + "_bits_" + key: value for key, value in fields.items()}}
        frames = iter([
            sample("read_addr", 0, addr=EXT_A, size=4, len=0, id=1),
            sample("read_addr", 1, addr=EXT_A, size=4, len=0, id=1),
            sample("read_data", 0, id=1, last=1, resp=0),
            {**sample("read_data", 1, id=1, last=1, resp=0),
             **sample("write_addr", 1, addr=EXT_OUT, size=4, len=0, id=2),
             **sample("write_data", 1, strb=0xFFFF)},
            sample("write_resp", 0, id=2, resp=0),
            sample("write_resp", 1, id=2, resp=0),
        ])
        async def falling(_):
            try: frame = next(frames)
            except StopIteration: raise asyncio.CancelledError()
            for signal in signals.values(): signal.value = 0
            for name, value in frame.items(): signals[name].value = value
        async def noop(*args): await asyncio.sleep(0)
        modules = {"cocotb": types.ModuleType("cocotb"), "cocotb.triggers": types.ModuleType("cocotb.triggers")}
        modules["cocotb.triggers"].FallingEdge = falling
        modules["cocotb.triggers"].ReadOnly = noop
        modules["cocotb.triggers"].RisingEdge = noop
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("synthetic_axi_probe", HERE / "workset_axi_probe.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            probe = module.WorksetAxiProbe(dut, 12)
            async def run():
                try: await probe._observe()
                except asyncio.CancelledError: pass
            asyncio.run(run())
            got = probe.stop(dict(input_read_bytes=16, weight_read_bytes=0, output_write_bytes=16))
            self.assertEqual(got["read_requests"], 1)
            self.assertEqual(got["read_beats"], 1)
            self.assertEqual(got["write_completed_transactions"], 1)

    def test_capacity_plans_and_pool_bounds(self):
        for kib in CAPACITIES:
            for tiles in TILE_CHOICES:
                for strategy in STRATEGIES:
                    p = plan(kib, tiles, strategy)
                    self.assertLessEqual(16384 + p["used_slots"] * 4096, kib * 1024)
                    self.assertEqual(p["output_write_bytes"], ROUNDS * tiles * 1024)
                    self.assertEqual(p["checked_elements"], ROUNDS * tiles * 256)
        self.assertEqual(plan(32, 12, "prefix_cache")["weight_read_bytes"], 122880)
        self.assertEqual(plan(128, 12, "prefix_cache")["weight_read_bytes"], 49152)
        self.assertEqual(plan(32, 12, "stream")["weight_read_bytes"], 147456)
        self.assertEqual(plan(4096, 768, "prefix_cache")["resident_tiles"], 768)
        self.assertLess(plan(2048, 768, "prefix_cache")["resident_tiles"], 768)

    def test_plan_matches_explicit_copy_schedule(self):
        for kib in CAPACITIES:
            for tiles in TILE_CHOICES:
                for strategy in STRATEGIES:
                    p = plan(kib, tiles, strategy)
                    pool, loads = {}, 0
                    for r in range(ROUNDS):
                        for t in range(tiles):
                            slot = t if t < p["resident_tiles"] else p["resident_tiles"]
                            if r == 0 or t >= p["resident_tiles"]:
                                pool[slot] = t
                                loads += 1
                            self.assertEqual(pool[slot], t)
                    self.assertEqual(loads * 4096, p["weight_read_bytes"])

    def test_vectors_signed_and_golden_widened(self):
        a, b, expected, sha = vectors(12)
        self.assertEqual(expected.shape, (3, 12, 16, 16))
        self.assertTrue(np.any(a == -128) and np.any(b == -128))
        self.assertEqual(len(sha), 64)
        for r, t in ((0, 0), (2, 11)):
            np.testing.assert_array_equal(expected[r, t], a[r].astype(np.int64) @ b[t].astype(np.int64))

    def test_axi_completions_and_expected_bytes(self):
        for strategy in STRATEGIES:
            p = plan(32, 12, strategy)
            traffic = fake_traffic(p)
            self.assertEqual(traffic["read_completed_bytes"], p["input_read_bytes"] + p["weight_read_bytes"])
            self.assertEqual(traffic["output_write_bytes"], p["output_write_bytes"])

    def test_axi_rejects_unexpected_addresses_and_bad_responses(self):
        for action in (lambda c: c.ar(0x80000000, 4, 0, 1),
                       lambda c: c.aw(EXT_B, 4, 0, 1),
                       lambda c: c.ar(EXT_A + 4090, 4, 0, 1),
                       lambda c: c.r(1, 1, 0), lambda c: c.b(1, 0)):
            with self.assertRaises(ValueError): action(TrafficCounter(12))
        c = TrafficCounter(12)
        c.ar(EXT_A, 4, 1, 1)
        with self.assertRaises(ValueError): c.r(1, 1, 0)
        c = TrafficCounter(12)
        c.ar(EXT_A, 4, 0, 1)
        with self.assertRaises(ValueError): c.r(1, 1, 2)
        with self.assertRaises(ValueError): c.finish(plan(32, 12, "stream"))

    def test_elf_layout_reserves_separate_pool(self):
        entry, segments, symbols, sizes = layout()
        check_elf_layout(entry, segments, symbols, sizes)
        for wrong in (segments + [[EXT_B, 4096]], [[0, 8192], [DTCM_BASE, 32768]]):
            with self.assertRaises(ValueError): check_elf_layout(entry, wrong, symbols, sizes)
        symbols["ws_a"] = DTCM_BASE + LOW_DTCM_BYTES
        with self.assertRaises(ValueError): check_elf_layout(entry, segments, symbols, sizes)

    def test_build_syntax_and_configuration(self):
        for kib in CAPACITIES:
            text = installer.workset_build(kib)
            ast.parse(text)
            for required in ('testcases = ["tcm_workset_test"]', '"COCOTB_USE_FRONTDOOR=1"',
                             '"workset_axi_probe.py"', '-DZVTBF16FMM_ON', '"timeout": "eternal"',
                             f'--dtcmSizeKBytes={kib}', '//tests/cocotb/tcm_workset:workset_program.elf'):
                self.assertIn(required, text)
        for name in ("workset_bench.py", "workset_axi_probe.py"):
            ast.parse((HERE / name).read_text())

    def test_strict_workset_log_rejects_bad_counts_and_repeats(self):
        result, _ = installer.checked_log(log(rows()), 32, 12, 0)
        self.assertEqual(len(result), 2)
        self.assertLess(result[1]["weight_read_bytes"], result[0]["weight_read_bytes"])
        for mutate in (lambda r: r[0].update(elf_sha256="b"*64),
                       lambda r: r[0].update(wait_for_halt_cycles=True),
                       lambda r: r[0].update(vector_sha256="b"*64),
                       lambda r: r[0]["axi"].update(weight_read_bytes=1),
                       lambda r: r[0]["csr_counters"].update(ws_weight_bytes=1),
                       lambda r: r[0]["axi"].update(read_completed_bytes=1),
                       lambda r: r[0]["csr_counters"].update(ws_total_cycles=5),
                       lambda r: r[0].update(repeat=1)):
            wrong = rows()
            mutate(wrong)
            with self.assertRaises(ValueError): installer.checked_log(log(wrong), 32, 12, 0)
        with self.assertRaises(ValueError): installer.checked_log(log(rows()[:-1]), 32, 12, 0)

    def test_install_preserves_both_baselines_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "tcm_control_manifest.json"
            base.write_text('{"control": 1}')
            with patch.object(installer, "verify_control"), patch.object(installer, "git", return_value=b"header"), \
                    patch.object(installer, "control_evidence", return_value={}):
                first = installer.prepare(root)
                self.assertEqual(installer.prepare(root), first)
                self.assertEqual(base.read_text(), '{"control": 1}')
                self.assertEqual(len(first["files"]), 33)
                build = (root / installer.PACKAGE / "BUILD").read_text()
                ast.parse(build)
                self.assertIn('dtcm_size_kbytes = 16', build)
                self.assertIn('stack_size_bytes = 1024', build)
                (root / installer.PACKAGE / "workset_program.cc").write_text("tamper")
                with self.assertRaises(ValueError): installer.verify(root)

    def test_runner_and_workset_firmware_resolver(self):
        script = (HERE / "run_workset.sh").read_text()
        for required in ('set -euo pipefail', '--noshow_progress', '--basename workset_program.elf',
                         'cquery "${tcm_flags[@]}"', '--test_env=TCM_WS_TILES=', '--test_env=TCM_WS_READ_DELAY='):
            self.assertIn(required, script)
        self.assertNotIn("git clone", script)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            relative = "bazel-out/config-ST-riscv/bin/pkg/workset_program.elf"
            path = root / relative
            path.parent.mkdir(parents=True)
            header = bytearray(52)
            header[:6], header[18:20] = b"\x7fELF\x01\x01", (243).to_bytes(2, "little")
            path.write_bytes(header)
            self.assertEqual(resolve_elf(root, relative, "workset_program.elf"), path.resolve())
            with self.assertRaises(ValueError): resolve_elf(root, relative)


if __name__ == "__main__":
    unittest.main(verbosity=2)
