"""Frontdoor-selected single-Conv fragment, timing comes from NPU mcycle."""
import hashlib
import json
import os
import sys
import time
import types
import cocotb
import numpy as np
from cocotb.triggers import ClockCycles,First,ReadOnly,RisingEdge
from cocotb.utils import get_sim_time

for n in ("bazel_tools","bazel_tools.tools","bazel_tools.tools.python","bazel_tools.tools.python.runfiles"):
    if n not in sys.modules:
        m=types.ModuleType(n);m.__path__=[];sys.modules[n]=m
shim=types.ModuleType("bazel_tools.tools.python.runfiles.runfiles");shim.Create=lambda:None
sys.modules[shim.__name__]=shim;sys.modules["bazel_tools.tools.python.runfiles"].runfiles=shim
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture
from server_conv import load_packet,helper,MARKER


@cocotb.test()
async def conv_rtl_test(dut):
    assert os.environ.get("COCOTB_USE_FRONTDOOR")=="1"
    packet=load_packet(os.environ["CONV_PACKET"])
    _,_,_,rtl=helper().load_runtime(os.environ["PERSON_PACKAGE"])
    case_id=int(os.environ["CONV_CASE"]);budget=int(os.environ["CONV_CYCLES"])
    case=packet.manifest["cases"][case_id];report=packet.report
    fixture=await VerilatorTestFixture.Create(dut,csr_base_addr=0x02000000)
    await fixture.write(0,np.tile(np.array([0x13,0,0,0],dtype=np.uint8),256*1024//4))
    await fixture.write(0x01000000,np.full(512*1024,0xA5,dtype=np.uint8))
    await fixture.load_elf_and_lookup_symbols(packet.root/"conv_program.elf",list(report["symbols"]),optional=False)
    assert fixture.entry_point==report["entry"]
    assert {n:fixture.symbols[n] for n in report["symbols"]}=={n:v["address"] for n,v in report["symbols"].items()}
    for item in packet.layout[str(case_id)].values():
        readback=await fixture.read(item["address"],size_bytes=item["bytes"])
        assert hashlib.sha256(readback.tobytes()).hexdigest()==item["sha256"],"small model/input frontdoor mismatch"
    await fixture.write_word("pd_conv_case",case_id)
    assert int(await fixture.read_word("pd_conv_case"))==case_id
    stack=fixture.symbols["__stack_start__"];await fixture.write(stack,bytes([0xA5])*64)
    dut._log.info("[PERSON_CONV_STAGE] executing ONLY case=%s; Prepare/checking excluded from kernel windows",case["name"])
    await fixture.core_mini_axi.execute_from(fixture.entry_point)
    await ClockCycles(dut.io_aclk,2);await ReadOnly()
    start=float(get_sim_time(unit="ns"));wall=time.monotonic()
    if not bool(int(dut.io_fault.value)) and not bool(int(dut.io_halted.value)):
        await First(ClockCycles(dut.io_aclk,budget),RisingEdge(dut.io_fault),RisingEdge(dut.io_halted))
        await ReadOnly()
    fault=bool(int(dut.io_fault.value));halted=bool(int(dut.io_halted.value))
    cycles=round((float(get_sim_time(unit="ns"))-start)/1.25);elapsed=time.monotonic()-wall
    await ClockCycles(dut.io_aclk,1);await fixture.core_mini_axi.halt()
    values={n:int(await fixture.read_word("pd_probe_"+n)) for n in ("status","cases","checked","mismatches","commands","signature")}
    ref=list(map(int,await fixture.read("pd_conv_ref_cycles",dtype=np.uint32,shape=(4,))))
    vme=list(map(int,await fixture.read("pd_conv_vme_cycles",dtype=np.uint32,shape=(4,))))
    extra={n:int(await fixture.read_word("pd_conv_"+n)) for n in ("empty_cycles","m","k","n","op","arena_ref","arena_vme")}
    counts={n:int(await fixture.read_word("pd_vme_"+n)) for n in ("conv_calls","fallback_calls","commands","mismatches","validated_layers")}
    assert (extra["op"],extra["m"],extra["k"],extra["n"])==(case["original_operator_index"],case["M"],case["K"],case["N"])
    canary=(await fixture.read(stack,size_bytes=64)).tobytes()==bytes([0xA5])*64
    row=dict(schema=1,scope=packet.manifest["timing_scope"],case_id=case_id,case=case["name"],M=case["M"],K=case["K"],N=case["N"],
        useful_macs_per_call=case["useful_macs"],elf_sha256=packet.manifest["elf_sha256"],rtl_sha256=rtl.manifest["rtl_sha256"],
        source_model_sha256=packet.manifest["source_model_sha256"],derived_model_sha256=case["derived_model_sha256"],input_sha256=case["input_sha256"],
        fixture_model_readback_equal=True,input_readback_equal=True,itcm_kib=256,dtcm_kib=512,fault=fault,natural_halt=halted,
        firmware_status=values.pop("status"),stack_low_canary_intact=canary,stack_check="low_64_bytes_only_not_full_watermark",
        requested_cycles=budget,observation_elapsed_cycles=cycles,execution_wall_seconds=elapsed,reference_cycles=ref,vme_cycles=vme,
        empty_boundary_cycles=extra["empty_cycles"],arena_used_reference=extra["arena_ref"],arena_used_vme=extra["arena_vme"],
        vme_calls=counts["conv_calls"],vme_fallbacks=counts["fallback_calls"],vme_mismatches=counts["mismatches"],
        vme_internal_validations=counts["validated_layers"],vme_commands=counts["commands"],**values)
    dut._log.info(MARKER+json.dumps(row,sort_keys=True))
    assert not fault and halted and row["firmware_status"]==3,"fault/premature halt/budget exhausted, NOT PASS"
    assert canary and not row["mismatches"] and row["signature"]==packet.native[case["name"]]["signature"]
