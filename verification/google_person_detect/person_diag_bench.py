"""Intrusive pause/read/resume samples. Does not reset before collecting PC."""
import hashlib
import json
import os
import struct

import cocotb
from cocotb.triggers import ClockCycles, First, ReadOnly, RisingEdge
import numpy as np

# Installs the unchanged namespace adapter and exposes the unchanged fixture.
from person_bench import VerilatorTestFixture
from diagnose_person import base_tools, functions, symbolize, MARKER


async def bounded(clock, operation, cycles=20000):
    task = cocotb.start_soon(operation)
    await First(task, ClockCycles(clock, cycles))
    if not task.done():
        task.cancel()
        raise TimeoutError("Debug operation exceeded its own cycle budget; no reset fallback")
    return await task


async def read_registers(core):
    # DPC and GPRs first. Optional CSR failure is kept explicit and cmderr cleared.
    values, errors = {}, {}
    registers = [("dpc", 0x7B1), ("dcsr", 0x7B0), ("ra", 0x1001), ("sp", 0x1002),
                 ("s0", 0x1008)] + [("a" + str(i), 0x100A + i) for i in range(8)]
    registers += [("mepc", 0x341), ("mcause", 0x342), ("mtval", 0x343), ("mtvec", 0x305),
                  ("mcycle", 0xB00), ("minstret", 0xB02)]
    for name, address in registers:
        try:
            values[name] = int(await core.dm_read_reg(address))
        except (AssertionError, ValueError) as error:
            errors[name] = str(error) or type(error).__name__
            await core.dm_write(0x16, 0x700)  # Explicit W1C abstractcs.cmderr.
            if name in ("dpc", "dcsr", "ra", "sp"):
                raise AssertionError("Essential debug register unavailable: " + name) from error
    return values, errors


@cocotb.test()
async def person_diagnostic_test(dut):
    base = base_tools()
    bundle = base.load_bundle(os.environ["PERSON_PACKAGE"])
    root = bundle.root
    cycles, samples = int(os.environ["PERSON_DIAG_CYCLES"]), int(os.environ["PERSON_DIAG_SAMPLES"])
    assert os.environ.get("COCOTB_USE_FRONTDOOR") == "1"
    fixture = await VerilatorTestFixture.Create(dut, csr_base_addr=0x02000000)
    core, clock = fixture.core_mini_axi, dut.io_aclk
    dut._log.info("[PERSON_DIAG_STAGE] Frontdoor initialization and original ELF/model verification")
    await fixture.write(0, np.tile(np.array([0x13, 0, 0, 0], dtype=np.uint8), 256 * 1024 // 4))
    await fixture.write(0x01000000, np.full(512 * 1024, 0xA5, dtype=np.uint8))
    await fixture.load_elf_and_lookup_symbols(root / "firmware/person_program.elf",
                                              list(bundle.report["symbols"]), optional=False)
    loaded = await fixture.read("pd_model", size_bytes=300568)
    assert hashlib.sha256(loaded.tobytes()).hexdigest() == bundle.manifest["model_sha256"]
    inputs = (root / "inputs/person.int8.bin").read_bytes()
    await fixture.write("pd_input", inputs)
    assert (await fixture.read("pd_input", size_bytes=9216)).tobytes() == inputs
    await fixture.write("pd_output", bytes([37, 53]))
    for name in ("pd_status", "pd_arena_used", "pd_invoke_cycles"):
        await fixture.write_word(name, 0)
    table = functions((root / "firmware/person_program.elf").read_bytes())
    await core.execute_from(fixture.entry_point)
    await ClockCycles(clock, 2)
    for sample in range(samples):
        await ReadOnly()
        if not int(dut.io_fault.value) and not int(dut.io_halted.value):
            await First(ClockCycles(clock, cycles if sample == 0 else 4096),
                        RisingEdge(dut.io_fault), RisingEdge(dut.io_halted))
            await ReadOnly()
        fault, halted = bool(int(dut.io_fault.value)), bool(int(dut.io_halted.value))
        await ClockCycles(clock, 1)
        # Debug halt, NOT CSR halt/reset. The original tests exercise this path.
        await bounded(clock, core.dm_request_halt())
        await bounded(clock, core.dm_wait_for_halted())
        registers, errors = await bounded(clock, read_registers(core), cycles=100000)
        status = int(await fixture.read_word("pd_status"))
        used = int(await fixture.read_word("pd_arena_used"))
        invoke = int(await fixture.read_word("pd_invoke_cycles"))
        stack_candidates = []
        sp = registers["sp"]
        if 0x01000000 <= sp <= 0x01080000 - 128 and sp % 4 == 0:
            stack = (await fixture.read(sp, size_bytes=128)).tobytes()
            for offset, value in enumerate(struct.unpack("<32I", stack)):
                location = symbolize(table, max(0, value - 1))
                if location["contains_address"]:
                    stack_candidates.append(dict(stack_address=sp + offset * 4, word=value, location=location))
        row = dict(schema=1, sample=sample, initial_window_cycles=cycles,
                   subsequent_window_cycles=4096 if sample else 0,
                   scope="intrusive_DM_debug_NOT_inference_or_performance", firmware_changed=False,
                   core_reset_before_capture=False, elf_sha256=bundle.manifest["elf_sha256"],
                   fault_before_pause=fault, natural_halt_before_pause=halted,
                   firmware_status=status, arena_used_bytes=used, invoke_cycles=invoke,
                   registers=registers, optional_register_errors=errors,
                   dcsr_cause=(registers["dcsr"] >> 6) & 7,
                   pc_location=symbolize(table, registers["dpc"]),
                   ra_callsite_candidate=symbolize(table, max(0, registers["ra"] - 1)),
                   stack_code_candidates_NOT_backtrace=stack_candidates[:8])
        dut._log.info(MARKER + json.dumps(row, sort_keys=True))
        if fault or halted or sample == samples - 1:
            break
        await bounded(clock, core.dm_request_resume())
        await bounded(clock, core.dm_wait_for_resumed())
        await ClockCycles(clock, 2)
    # Remain debug halted until simulation exits; no CSR reset and no PASS claim.
