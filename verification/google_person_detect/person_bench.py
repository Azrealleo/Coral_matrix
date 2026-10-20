"""One unchanged complete model/ELF, bounded smoke or full single-image invoke."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import types

import cocotb
from cocotb.triggers import ClockCycles, First, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
import numpy as np

# The pinned upstream fixture imports runfiles, but the standalone ELF path is
# absolute. This namespace-only adapter deliberately resolves NO Bazel paths.
for name in ("bazel_tools", "bazel_tools.tools", "bazel_tools.tools.python", "bazel_tools.tools.python.runfiles"):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = []
        sys.modules[name] = mod
shim = types.ModuleType("bazel_tools.tools.python.runfiles.runfiles")
shim.Create = lambda: None
sys.modules[shim.__name__] = shim
sys.modules["bazel_tools.tools.python.runfiles"].runfiles = shim

from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture
from person_runner import load_bundle, MARKER, sha


@cocotb.test()
async def person_model_test(dut):
    assert os.environ.get("COCOTB_USE_FRONTDOOR") == "1"
    bundle = load_bundle(os.environ["PERSON_PACKAGE"])
    root, report = bundle.root, bundle.report
    case, mode, budget = os.environ["PERSON_CASE"], os.environ["PERSON_MODE"], int(os.environ["PERSON_CYCLES"])
    assert case in ("person", "no_person") and mode in ("smoke", "infer")
    fixture = await VerilatorTestFixture.Create(dut, csr_base_addr=0x02000000)
    clock = dut.io_aclk
    start = time.monotonic()
    dut._log.info("[PERSON_RTL_STAGE] Frontdoor ITCM/DTCM initialization and unchanged ELF loading")
    await fixture.write(0, np.tile(np.array([0x13, 0, 0, 0], dtype=np.uint8), 256 * 1024 // 4))
    await fixture.write(0x01000000, np.full(512 * 1024, 0xA5, dtype=np.uint8))
    symbols = list(report["symbols"])
    await fixture.load_elf_and_lookup_symbols(root / "firmware/person_program.elf", symbols, optional=False)
    assert fixture.entry_point == report["entry"]
    assert {n: fixture.symbols[n] for n in symbols} == {n: v["address"] for n, v in report["symbols"].items()}
    model = await fixture.read("pd_model", size_bytes=300568)
    assert hashlib.sha256(model.tobytes()).hexdigest() == bundle.manifest["model_sha256"], "model frontdoor readback mismatch"
    inputs = (root / "inputs" / (case + ".int8.bin")).read_bytes()
    await fixture.write("pd_input", inputs)
    assert (await fixture.read("pd_input", size_bytes=9216)).tobytes() == inputs, "input readback mismatch"
    await fixture.write("pd_output", bytes([37, 53]))
    for name in ("pd_status", "pd_arena_used", "pd_invoke_cycles"):
        await fixture.write_word(name, 0)
    stack_base = fixture.symbols["__stack_start__"]
    await fixture.write(stack_base, bytes([0xA5]) * 64)
    load_seconds = time.monotonic() - start
    dut._log.info("[PERSON_RTL_STAGE] Load/readback complete; executing %s budget=%d cycles", case, budget)
    await fixture.core_mini_axi.execute_from(fixture.entry_point)
    # Move to a fresh edge even if the AXI driver completed in ReadOnly.
    await ClockCycles(clock, 2)
    await ReadOnly()
    execution_start = float(get_sim_time(unit="ns"))
    wall_start = time.monotonic()
    assert not bool(int(dut.io_fault.value)), "NPU fault immediately after release"
    # An already asserted halted indication is handled explicitly, never missed
    # by waiting exclusively for a new rising edge.
    if not bool(int(dut.io_halted.value)):
        await First(ClockCycles(clock, budget), RisingEdge(dut.io_fault), RisingEdge(dut.io_halted))
        await ReadOnly()
    fault = bool(int(dut.io_fault.value))
    natural_halt = bool(int(dut.io_halted.value))
    elapsed_ns = float(get_sim_time(unit="ns")) - execution_start
    execution_seconds = time.monotonic() - wall_start
    # Stop this disposable simulation before inspecting RAM. This is NOT a
    # resumable checkpoint: halt() asserts the core reset/clock-gate CSR.
    await ClockCycles(clock, 1)
    await fixture.core_mini_axi.halt()
    status = int(await fixture.read_word("pd_status"))
    used = int(await fixture.read_word("pd_arena_used"))
    invoke = int(await fixture.read_word("pd_invoke_cycles"))
    scores = list(map(int, await fixture.read("pd_output", dtype=np.int8, shape=(2,))))
    canary = (await fixture.read(stack_base, size_bytes=64)).tobytes() == bytes([0xA5]) * 64
    row = dict(schema=1, case=case, mode=mode, requested_cycles=budget, fault=fault,
               itcm_kib=256, dtcm_kib=512, elf_sha256=bundle.manifest["elf_sha256"],
               model_sha256=bundle.manifest["model_sha256"],
               input_sha256=sha(root / "inputs" / (case + ".int8.bin")),
               model_readback_equal=True, input_readback_equal=True,
               firmware_status=status, arena_used_bytes=used, arena_reserved_bytes=163840,
               scores_no_person_then_person=scores, invoke_cycles=invoke,
               natural_halt=natural_halt, inference_complete=natural_halt and status == 3,
               stack_low_canary_intact=canary, stack_check="low_64_bytes_only_not_full_watermark",
               observation_elapsed_cycles=round(elapsed_ns / 1.25),
               execution_wall_seconds=execution_seconds, host_load_readback_wall_seconds=load_seconds,
               timing_scope="after_execute_release_plus_2_settle_cycles_to_halt_or_bounded_window_before_readback",
               stop_method="CSR_core_reset_clock_gate_not_resume_checkpoint",
               kernel_backend="pinned_TFLM_INT8_not_VME_offload")
    dut._log.info(MARKER + json.dumps(row, sort_keys=True))
    assert not fault, "NPU fault; see observation"
    assert status in (0, 1, 2, 3), "firmware failure status; see observation"
    assert canary, "lowest stack canary overwritten; stack budget not accepted"
    assert 0 <= used <= 163840 and (status < 2 or used > 0), "arena measurement invalid"
    if status == 3:
        assert scores == bundle.manifest["reference_scores_no_person_then_person"][case], "NPU output differs from native TFLM"
        assert invoke > 0
    if natural_halt:
        assert status == 3, "premature halt before complete Invoke"
    elif mode == "infer":
        raise AssertionError("Cycle budget exhausted; inference incomplete, NOT PASS")
