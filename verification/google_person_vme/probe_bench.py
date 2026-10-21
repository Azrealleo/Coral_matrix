"""Short real VME check using the original frontdoor fixture. NOT model inference."""
import json
import os
import sys
import time
import types
import cocotb
import numpy as np
from cocotb.triggers import ClockCycles, First, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

for name in ("bazel_tools","bazel_tools.tools","bazel_tools.tools.python","bazel_tools.tools.python.runfiles"):
    if name not in sys.modules:
        m=types.ModuleType(name);m.__path__=[];sys.modules[name]=m
shim=types.ModuleType("bazel_tools.tools.python.runfiles.runfiles");shim.Create=lambda:None
sys.modules[shim.__name__]=shim;sys.modules["bazel_tools.tools.python.runfiles"].runfiles=shim
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture
from server_probe import load_bundle, MARKER


@cocotb.test()
async def person_vme_probe_test(dut):
    assert os.environ.get("COCOTB_USE_FRONTDOOR")=="1"
    bundle=load_bundle(os.environ["PERSON_PACKAGE"])
    report=bundle.report;budget=int(os.environ["PERSON_CYCLES"])
    fixture=await VerilatorTestFixture.Create(dut,csr_base_addr=0x02000000)
    await fixture.write(0,np.tile(np.array([0x13,0,0,0],dtype=np.uint8),256*1024//4))
    await fixture.write(0x01000000,np.full(512*1024,0xA5,dtype=np.uint8))
    await fixture.load_elf_and_lookup_symbols(bundle.root/bundle.manifest["firmwares"]["probe"]["file"],
                                              list(report["symbols"]),optional=False)
    assert fixture.entry_point==report["entry"]
    assert {n:fixture.symbols[n] for n in report["symbols"]}=={n:v["address"] for n,v in report["symbols"].items()}
    stack=fixture.symbols["__stack_start__"]
    await fixture.write(stack,bytes([0xA5])*64)
    await fixture.core_mini_axi.execute_from(fixture.entry_point)
    await ClockCycles(dut.io_aclk,2);await ReadOnly()
    start=float(get_sim_time(unit="ns"));wall=time.monotonic()
    if not bool(int(dut.io_fault.value)) and not bool(int(dut.io_halted.value)):
        await First(ClockCycles(dut.io_aclk,budget),RisingEdge(dut.io_fault),RisingEdge(dut.io_halted))
        await ReadOnly()
    fault=bool(int(dut.io_fault.value));halted=bool(int(dut.io_halted.value))
    cycles=round((float(get_sim_time(unit="ns"))-start)/1.25)
    elapsed=time.monotonic()-wall
    await ClockCycles(dut.io_aclk,1);await fixture.core_mini_axi.halt()
    names=("status","cases","checked","mismatches","commands","signature","first_case","first_expected","first_actual")
    values={n:int(await fixture.read_word("pd_probe_"+n)) for n in names}
    canary=(await fixture.read(stack,size_bytes=64)).tobytes()==bytes([0xA5])*64
    row=dict(schema=1,scope="short_VME_arithmetic_not_model_inference",fault=fault,natural_halt=halted,
        firmware_status=values.pop("status"),requested_cycles=budget,observation_elapsed_cycles=cycles,
        itcm_kib=256,dtcm_kib=512,elf_sha256=bundle.manifest["firmwares"]["probe"]["sha256"],
        rtl_sha256=bundle.manifest["rtl_sha256"],stack_low_canary_intact=canary,
        execution_wall_seconds=elapsed,stack_check="low_64_bytes_not_full_watermark",**values)
    dut._log.info(MARKER+json.dumps(row,sort_keys=True))
    assert not fault and halted and row["firmware_status"]==3, "fault/premature halt/budget exhausted; NOT PASS"
    assert canary and values["mismatches"]==0
    assert {k:values[k] for k in ("cases","checked","commands","signature")}==bundle.manifest["probe_expected"]
