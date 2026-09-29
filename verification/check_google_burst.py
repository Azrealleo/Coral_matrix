#!/usr/bin/env python3
"""Local vector, harness and log-parser checks. NOT C++/RTL simulation."""

import ast
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "coralnpu-google/tests/cocotb/vme_test"
sys.path.insert(0, str(PACKAGE))
sys.dont_write_bytecode = True
from vme_matrix_burst_vectors import INPUT_SCHEDULE, burst_cases, validate_reuse_case


def harness_functions():
    # Load just the pure/reference and async harness functions; no Cocotb or
    # simulator is installed on this host. Exercise them with a fake fixture.
    path = PACKAGE / "vme_matrix_perf_bench.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {"_common_cases", "_reference", "_vector_hash", "_run_case"}
    selected = [node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert len(selected) == len(names)

    class FakeLog:
        def __init__(self):
            self.messages = []

        def info(self, message):
            self.messages.append(message)

    class FakeCocotb:
        log = FakeLog()

    namespace = dict(np=np, hashlib=hashlib, json=json, TE=16, MAX_K=256,
                     SYMBOLS=["perf_a", "perf_b", "perf_out", "perf_k", "perf_tk",
                              "perf_signed_b", "perf_status", "perf_mtype", "perf_vtype"],
                     cocotb=FakeCocotb)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace, FakeCocotb.log


class FakeFixture:
    """Emulate the upload contract and ONLY the reused-first-chunk arithmetic."""
    def __init__(self, corrupt=False):
        self.values = {}
        self.corrupt = corrupt

    async def load_elf_and_lookup_symbols(self, elf, symbols, optional):
        assert elf == "fake.elf" and len(symbols) == 9 and optional is False
        self.values = {}

    async def write(self, name, value):
        self.values[name] = value.copy()

    async def write_word(self, name, value):
        self.values[name] = int(value)

    async def run_to_halt(self, timeout_cycles):
        assert timeout_cycles == 200000
        assert np.all(self.values["perf_out"] == 0xDEADBEEF)
        k = self.values["perf_k"]
        assert self.values["perf_tk"] == 4
        a = self.values["perf_a"].view(np.int8).reshape(260, 16)[:4].T.astype(np.int64)
        b = self.values["perf_b"].view(np.int8).reshape(260, 16)[:4].astype(np.int64)
        self.output = ((a @ b) * (k // 4)).astype("<i4")
        if self.corrupt:
            self.output[7, 11] += 1
        self.values.update(perf_status=1, perf_mtype=(16 << 10) | (4 << 5) | 3,
                           perf_vtype=0xC0 | (self.values["perf_signed_b"] << 8))
        return 999  # Synthetic, intentionally not a predicted RTL cycle count.

    def fault(self):
        return False

    async def read_word(self, name):
        return self.values[name]

    async def read(self, name, dtype, shape):
        assert name == "perf_out" and shape == (16, 16) and dtype == np.dtype("<i4")
        return self.output.copy()


class FakeObserver:
    def __init__(self):
        self.events = []

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")


class BurstTests(unittest.TestCase):
    def setUp(self):
        self.ns, self.log = harness_functions()

    def test_reuse_and_independent_scalar_references(self):
        cases = burst_cases()
        self.assertEqual(len(cases), 4)
        for case in cases:
            name, a, b, _, signed_b = case
            validate_reuse_case(case)
            k = a.shape[1]
            scalar = [[sum(int(a[i, p]) * int(b[p, j]) for p in range(k))
                       for j in range(16)] for i in range(16)]
            ref = self.ns["_reference"](a, b)
            np.testing.assert_array_equal(ref, scalar)
            self.assertGreater(np.count_nonzero(ref), 240, name)
            self.assertLess(int(np.abs(ref.astype(np.int64)).max()), 2**31)
            if signed_b:
                self.assertTrue(np.any(a == -128) and np.any(b == -128))
                self.assertTrue(np.any(a < 0) and np.any(b < 0) and np.any(b > 0))
            print(f"[BURST_VECTOR] case={name} K={k} sha256={self.ns['_vector_hash'](a, b)}")

    def test_non_reused_vectors_rejected(self):
        name, a, b, tk, signed_b = burst_cases()[0]
        a = a.copy()
        a[0, 4] = 3
        with self.assertRaises(AssertionError):
            validate_reuse_case((name, a, b, tk, signed_b))

    def test_upload_transpose_golden_and_observer_lifetime(self):
        for case in burst_cases():
            for repeat in range(3):
                observer = FakeObserver()
                cycles = asyncio.run(self.ns["_run_case"](
                    FakeFixture(), "fake.elf", case, repeat=repeat,
                    observer=observer, input_schedule=INPUT_SCHEDULE))
                self.assertEqual(cycles, 999)
                self.assertEqual(observer.events, ["start", "stop"])
        self.assertEqual(len(self.log.messages), 12)
        for message in self.log.messages:
            record = json.loads(message.split("[GOOGLE_MATRIX_PERF] ")[1])
            self.assertEqual(record["input_schedule"], INPUT_SCHEDULE)
            self.assertEqual(record["checked_elements"], 256)

    def test_wrong_result_rejected_before_performance_record(self):
        observer = FakeObserver()
        with self.assertRaises(AssertionError):
            asyncio.run(self.ns["_run_case"](FakeFixture(corrupt=True), "fake.elf",
                                           burst_cases()[0], observer=observer,
                                           input_schedule=INPUT_SCHEDULE))
        self.assertEqual(observer.events, ["start", "stop"])
        self.assertEqual(self.log.messages, [])

    def test_changed_common_functions_still_match_hashes(self):
        from summarize_google_array import HASHES
        for name, a, b, _, _ in self.ns["_common_cases"]():
            self.assertEqual(self.ns["_vector_hash"](a, b), HASHES[name])

    def test_burst_hashes_and_summary_parser(self):
        from check_google_array_counter import run, synthetic_trace
        from summarize_google_array import BURST_HASHES, BURST_SCHEDULE, summarize
        self.assertEqual(INPUT_SCHEDULE, BURST_SCHEDULE)
        records = []
        for name, a, b, _, _ in burst_cases():
            fingerprint = self.ns["_vector_hash"](a, b)
            self.assertEqual(fingerprint, BURST_HASHES[name])
            k = a.shape[1]
            for repeat in range(3):
                row = run(synthetic_trace([4 * i for i in range(k // 4)]), k)
                row.update(case=name, K=k, repeat=repeat, vector_sha256=fingerprint,
                           launch_wait_to_halt_cycles=999, input_schedule=INPUT_SCHEDULE,
                           command_pc_offsets_bytes=[4 * i for i in range(k // 4)])
                records.append(row)
        rows = summarize(records, BURST_HASHES, BURST_SCHEDULE)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["start_interval_min"] == 4 for row in rows))
        self.assertTrue(all(row["no_command_inflight_elapsed_cycles"] == 0 for row in rows))
        for field, value in (("repeat", 0), ("vector_sha256", "wrong"),
                             ("input_schedule", "wrong"), ("tile_bytes_written", 0),
                             ("launch_wait_to_halt_cycles", 998), ("command_pc_offsets_bytes", [0])):
            changed = copy.deepcopy(records)
            changed[-1][field] = value
            with self.assertRaises(AssertionError):
                summarize(changed, BURST_HASHES, BURST_SCHEDULE)
        with self.assertRaises(AssertionError):
            summarize(records[:-1], BURST_HASHES, BURST_SCHEDULE)
        with self.assertRaises(AssertionError):
            summarize(records)  # Burst records must not pass as common vectors.


if __name__ == "__main__":
    unittest.main(verbosity=2)
