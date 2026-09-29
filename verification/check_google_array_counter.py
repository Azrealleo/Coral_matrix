#!/usr/bin/env python3
"""Unit-test the observer with synthetic edge traces. NOT RTL simulation."""

import ast
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "coralnpu-google/tests/cocotb/vme_test"
sys.path.insert(0, str(PACKAGE))
sys.dont_write_bytecode = True
from vme_matrix_engine_counter import ArrayCounter


def synthetic_trace(starts):
    trace = []
    for cycle in range(starts[-1] + 14):
        sample = dict(rst_n=1, flush=0, cnt=0, blkCmdVld=0, blkCmdRdy=15,
                      canStart=0, peCmdVld=0, peCmdRdy=0, hitRaw=0,
                      busy=int(any(start <= cycle <= start + 13 for start in starts)),
                      writeEn=0, mtWriteEn=0, writeMtIdx=0, writeSubIdx=0,
                      writePc=0, peRtVld=0)
        for start in starts:
            strip = cycle - start
            if 0 <= strip < 4:
                sample.update(cnt=strip, blkCmdVld=1, canStart=1, peCmdVld=15,
                              peCmdRdy=15 if strip == 3 else 0)
            for block, delay in enumerate((8, 9, 9, 10)):
                strip = cycle - start - delay
                if 0 <= strip < 4:
                    for port in range(4):
                        flat = block * 4 + port
                        mt = 2 * (block // 2) + port % 2
                        sub = 2 * (block % 2) + 4 * strip + port // 2
                        sample["writeEn"] |= 0xFFFF << (flat * 16)
                        sample["writeMtIdx"] |= mt << (flat * 4)
                        sample["writeSubIdx"] |= sub << (flat * 4)
                    sample["writePc"] |= 0x100 << (block * 32)
                    if strip == 3:
                        sample["peRtVld"] |= 1 << block
        sample["mtWriteEn"] = sample["writeEn"]
        trace.append(sample)
    return trace


def run(trace, k=16):
    counter = ArrayCounter()
    for sample in trace:
        counter.step(sample)
    return counter.summary(k)


class CounterTests(unittest.TestCase):
    def setUp(self):
        self.trace = synthetic_trace([0, 24, 48, 72])

    def test_overlapping_commands(self):
        result = run(synthetic_trace([0, 4, 8, 12]))
        self.assertEqual(result["command_latency_cycles"], [13] * 4)
        self.assertEqual(result["array_schedule_elapsed_cycles"], 25)
        self.assertEqual(result["command_active_union_elapsed_cycles"], 25)
        self.assertEqual(result["no_command_inflight_elapsed_cycles"], 0)
        self.assertEqual(result["command_start_intervals"], [4] * 3)
        self.assertEqual(result["tile_bytes_written"], 4096)

    def test_feed_gaps_and_latency_boundary(self):
        result = run(self.trace)
        self.assertEqual(result["array_schedule_elapsed_cycles"], 85)
        self.assertEqual(result["command_active_union_elapsed_cycles"], 52)
        self.assertEqual(result["no_command_inflight_elapsed_cycles"], 33)
        self.assertEqual(result["command_consumed_offsets"], [3, 27, 51, 75])
        self.assertEqual(result["command_latency_cycles"], [13] * 4)
        self.assertEqual(result["block0_strip_issue_cycles"], 16)
        self.assertEqual(result["no_full_command_offered_cycles"], 69)

    def test_offset_invariance_and_all_k(self):
        self.assertEqual(run(self.trace), run(synthetic_trace([100, 124, 148, 172])))
        for k in (16, 64, 256):
            result = run(synthetic_trace([24 * i for i in range(k // 4)]), k)
            self.assertEqual(result["matrix_commands"], k // 4)
            self.assertEqual(result["tile_bytes_written"], 256 * k)

    def test_missing_last_write_rejected(self):
        self.trace[-1].update(writeEn=0, mtWriteEn=0, peRtVld=0)
        with self.assertRaisesRegex(AssertionError, "Incomplete"):
            run(self.trace)

    def test_duplicate_address_rejected(self):
        self.trace[9]["writeSubIdx"] &= ~0xFFFF
        with self.assertRaisesRegex(AssertionError, "Duplicate"):
            run(self.trace)

    def test_suppressed_mt_write_rejected(self):
        self.trace[8]["mtWriteEn"] = 0
        with self.assertRaisesRegex(AssertionError, "suppressed"):
            run(self.trace)

    def test_early_consume_rejected(self):
        self.trace[2]["peCmdRdy"] = 15
        with self.assertRaisesRegex(AssertionError, "before its last"):
            run(self.trace)

    def test_early_retire_rejected(self):
        self.trace[8]["peRtVld"] = 1
        with self.assertRaisesRegex(AssertionError, "before all"):
            run(self.trace)

    def test_partial_int32_write_rejected(self):
        self.trace[8]["writeEn"] &= ~14
        self.trace[8]["mtWriteEn"] = self.trace[8]["writeEn"]
        with self.assertRaisesRegex(AssertionError, "Partial"):
            run(self.trace)

    def test_changed_pc_rejected(self):
        self.trace[9]["writePc"] ^= 4 << 32
        with self.assertRaisesRegex(AssertionError, "PC changed"):
            run(self.trace)

    def test_reset_flush_and_wrong_count_rejected(self):
        for field, value in (("rst_n", 0), ("flush", 1)):
            trace = copy.deepcopy(self.trace)
            trace[1][field] = value
            with self.assertRaises(AssertionError):
                run(trace)
        with self.assertRaisesRegex(AssertionError, "number"):
            run(self.trace, 64)
        idle_flush = copy.deepcopy(self.trace)
        idle_flush[17]["flush"] = 1  # Between commands, no pipeline work to kill.
        self.assertEqual(run(idle_flush), run(self.trace))


if __name__ == "__main__":
    for name in ("vme_matrix_engine_counter.py", "vme_matrix_engine_probe.py",
                 "vme_matrix_engine_bench.py", "vme_matrix_perf_bench.py", "BUILD"):
        path = PACKAGE / name
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print("[COUNTER_UNIT] Syntax checked; synthetic tests only, NOT RTL simulation", flush=True)
    unittest.main()
