"""One selected synthetic linear case. All timing originates in NPU mcycle."""
import hashlib
import json
import os
from pathlib import Path
import struct
import time

import cocotb
from cocotb.triggers import ClockCycles, First, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
import numpy as np
from bazel_tools.tools.python.runfiles import runfiles
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture

from spec import CASES, MARKER, PACKAGE, SAMPLES, SCOPE, TOP, accept, vectors
from audit import inspect, checked_header


def runfile(name):
    resolver = runfiles.Create()
    for workspace in (os.environ.get("TEST_WORKSPACE", "_main"), "_main", "coralnpu_hw"):
        path = resolver.Rlocation(workspace+"/"+PACKAGE+"/"+name)
        if path and Path(path).is_file():
            return Path(path)
    raise ValueError("Missing runfile: "+name)


async def run_case(dut, index):
    assert os.environ.get("COCOTB_USE_FRONTDOOR") == "1"
    name,m,k,n = CASES[index]; golden = vectors(index)
    path = runfile("probe_program.elf"); report = inspect(path.read_bytes())
    checked_header(runfile("V"+TOP+"_parameters.h").read_text())
    rtl_sha = hashlib.sha256(runfile(TOP+".sv").read_bytes()).hexdigest()
    fixture = await VerilatorTestFixture.Create(dut, csr_base_addr=0x02000000)
    # Exact 256/512KiB map; NEVER use an older ITCM8KiB control model.
    await fixture.write(0, np.tile(np.array([0x13,0,0,0],dtype=np.uint8),256*1024//4))
    await fixture.write(0x01000000, np.full(512*1024,0xa5,dtype=np.uint8))
    await fixture.load_elf_and_lookup_symbols(path, list(report["symbols"]), optional=False)
    assert fixture.entry_point == report["entry"]
    assert {s:fixture.symbols[s] for s in report["symbols"]} == {s:v["address"] for s,v in report["symbols"].items()}
    await fixture.write_word("llm_case",index)
    assert int(await fixture.read_word("llm_case")) == index
    stack = fixture.symbols["__stack_start__"]
    await fixture.write(stack,bytes([0xa5])*64)
    budget = 2000000 if index == 0 else 10000000
    dut._log.info("[LLM_LINEAR_STAGE] case=%s M=%d K=%d N=%d first+3steady scalar/RVV; no model",name,m,k,n)
    await fixture.core_mini_axi.execute_from(fixture.entry_point)
    await ClockCycles(dut.io_aclk,2); await ReadOnly()
    start = float(get_sim_time(unit="ns")); wall = time.monotonic()
    if not bool(int(dut.io_fault.value)) and not bool(int(dut.io_halted.value)):
        await First(ClockCycles(dut.io_aclk,budget),RisingEdge(dut.io_fault),RisingEdge(dut.io_halted))
        await ReadOnly()
    fault,halted = bool(int(dut.io_fault.value)),bool(int(dut.io_halted.value))
    elapsed = round((float(get_sim_time(unit="ns"))-start)/1.25)
    wall_seconds = time.monotonic()-wall
    await ClockCycles(dut.io_aclk,1); await fixture.core_mini_axi.halt()
    values = {s:int(await fixture.read_word("llm_"+s)) for s in
              ("status","checked","mismatches","signature","m","k","n","rvv_calls","guard_ok","empty_cycles")}
    assert (values["m"],values["k"],values["n"]) == (m,k,n)
    scalar = list(map(int,await fixture.read("llm_scalar_cycles",dtype=np.dtype("<u4"),shape=(4,))))
    rvv = list(map(int,await fixture.read("llm_rvv_cycles",dtype=np.dtype("<u4"),shape=(4,))))
    x = (await fixture.read("llm_x",size_bytes=m*k)).tobytes()
    w = (await fixture.read("llm_w",size_bytes=k*n)).tobytes()
    assert x == golden["x"] and w == golden["w"], "Actual NPU vectors differ from independent generator"
    expected = struct.pack("<"+"i"*(m*n),*golden["y"])
    for symbol in ("llm_scalar_out","llm_rvv_out"):
        raw = (await fixture.read(symbol,size_bytes=4128)).tobytes()
        guard = struct.pack("<I",0x55aa7711)
        assert raw[:16] == guard*4 and raw[-16:] == guard*4
        assert raw[16:16+4*m*n] == expected, "Raw INT32 output not exact: "+symbol
        assert raw[16+4*m*n:-16] == guard*(16*64-m*n), "Out-of-range output write"
    canary = (await fixture.read(stack,size_bytes=64)).tobytes() == bytes([0xa5])*64
    row = dict(schema=1,scope=SCOPE,case_id=index,case=name,M=m,K=k,N=n,
        itcm_kib=256,dtcm_kib=512,elf_sha256=report["elf_sha256"],rtl_sha256=rtl_sha,
        vector_sha256=golden["vector_sha256"],input_readback_equal=True,output_readback_equal=True,
        fault=fault,natural_halt=halted,firmware_status=values["status"],checked_elements=values["checked"],
        mismatches=values["mismatches"],signature=values["signature"],rvv_calls=values["rvv_calls"],
        guard_ok=values["guard_ok"]==1,stack_low_canary_intact=canary,samples=SAMPLES,
        scalar_cycles=scalar,rvv_cycles=rvv,empty_boundary_cycles=values["empty_cycles"],
        observation_elapsed_cycles=elapsed,execution_wall_seconds=wall_seconds,requested_cycles=budget,
        stack_check="low_64_bytes_not_full_watermark",quantization="raw_INT8_to_INT32_no_requantization",
        timing="kernel_call_only_inputs_resident_excludes_generation_checks_and_host_loading")
    dut._log.info(MARKER+json.dumps(row,sort_keys=True))
    comparison = accept(row,index)
    dut._log.info("[LLM_LINEAR_CYCLE_COMPARISON] "+json.dumps(comparison,sort_keys=True))


@cocotb.test()
async def llm_decode_tiny_test(dut):
    await run_case(dut,0)


@cocotb.test()
async def llm_prefill_tiny_test(dut):
    await run_case(dut,1)


@cocotb.test()
async def llm_decode_small_test(dut):
    await run_case(dut,2)


@cocotb.test()
async def llm_prefill_small_test(dut):
    await run_case(dut,3)
