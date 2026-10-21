"""One FP32 operator, strict independent numerical and safety checks."""
import hashlib
import json
import os
from pathlib import Path
import struct
import time
import cocotb
import numpy as np
from cocotb.triggers import ClockCycles,First,ReadOnly,RisingEdge
from cocotb.utils import get_sim_time
from bazel_tools.tools.python.runfiles import runfiles
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture
from tx_spec import ATOL,RTOL,CASES,MARKER,PACKAGE,LINEAR_PACKAGE,TOP,SCOPE,KINDS,fixture,packed,accept
from tx_audit import inspect,checked_header


def locate(package,name):
    files=runfiles.Create()
    for workspace in (os.environ.get("TEST_WORKSPACE","_main"),"_main","coralnpu_hw"):
        path=files.Rlocation(workspace+"/"+package+"/"+name)
        if path and Path(path).is_file():return Path(path)
    raise ValueError("Missing runfile: "+package+"/"+name)


async def run_case(dut,index):
    assert os.environ.get("COCOTB_USE_FRONTDOOR")=="1"
    case=fixture(index);path=locate(PACKAGE,"probe_program.elf");report=inspect(path.read_bytes())
    rtl_sha=hashlib.sha256(locate(LINEAR_PACKAGE,TOP+".sv").read_bytes()).hexdigest()
    checked_header(locate(LINEAR_PACKAGE,"V"+TOP+"_parameters.h").read_text())
    fixture_hw=await VerilatorTestFixture.Create(dut,csr_base_addr=0x02000000)
    await fixture_hw.write(0,np.tile(np.array([0x13,0,0,0],dtype=np.uint8),256*1024//4))
    await fixture_hw.write(0x01000000,np.full(512*1024,0xa5,dtype=np.uint8))
    await fixture_hw.load_elf_and_lookup_symbols(path,list(report["symbols"]),optional=False)
    assert fixture_hw.entry_point==report["entry"]
    assert {s:fixture_hw.symbols[s] for s in report["symbols"]}=={s:v["address"] for s,v in report["symbols"].items()}
    await fixture_hw.write_word("tx_case",index)
    assert int(await fixture_hw.read_word("tx_case"))==index
    stack=fixture_hw.symbols["__stack_start__"];await fixture_hw.write(stack,bytes([0xa5])*64)
    await fixture_hw.core_mini_axi.execute_from(fixture_hw.entry_point)
    await ClockCycles(dut.io_aclk,2);await ReadOnly()
    start=float(get_sim_time(unit="ns"));wall=time.monotonic();budget=10000000
    if not bool(int(dut.io_fault.value)) and not bool(int(dut.io_halted.value)):
        await First(ClockCycles(dut.io_aclk,budget),RisingEdge(dut.io_fault),RisingEdge(dut.io_halted))
        await ReadOnly()
    fault,halted=bool(int(dut.io_fault.value)),bool(int(dut.io_halted.value))
    cycles=round((float(get_sim_time(unit="ns"))-start)/1.25);elapsed=time.monotonic()-wall
    await ClockCycles(dut.io_aclk,1);await fixture_hw.core_mini_axi.halt()
    values={s:int(await fixture_hw.read_word("tx_"+s)) for s in
            ("status","kind","checked","mismatches","calls","guard_ok","first_bad","empty")}
    scalar=list(map(int,await fixture_hw.read("tx_scalar_cycles",dtype=np.dtype("<u4"),shape=(4,))))
    rvv=list(map(int,await fixture_hw.read("tx_rvv_cycles",dtype=np.dtype("<u4"),shape=(4,))))
    inputs_ok=True
    for name in ("x","w","v"):
        expected=packed(case[name])
        if expected:
            actual=(await fixture_hw.read("tx_"+name,size_bytes=len(expected))).tobytes()
            inputs_ok=inputs_ok and actual==expected
    outputs_ok,guards_ok=True,True;errors=[];n=len(case["y"])
    gold=np.array(case["y"],dtype=np.float64)
    for name in ("tx_scalar_out","tx_rvv_out"):
        raw=(await fixture_hw.read(name,size_bytes=4128)).tobytes()
        guard=struct.pack("<I",0x55aa7711)
        guards_ok=guards_ok and raw[:16]==guard*4 and raw[-16:]==guard*4 and raw[16+n*4:-16]==guard*(1024-n)
        actual=np.frombuffer(raw[16:16+n*4],dtype="<f4").astype(np.float64)
        finite=bool(np.isfinite(actual).all())
        outputs_ok=outputs_ok and finite and bool(np.all(np.abs(actual-gold)<=ATOL+RTOL*np.abs(gold)))
        errors.append(float(np.max(np.abs(actual-gold))) if finite else None)
    canary=(await fixture_hw.read(stack,size_bytes=64)).tobytes()==bytes([0xa5])*64
    row=dict(schema=1,scope=SCOPE,case_id=index,case=case["name"],kind=case["kind"],shape=case["shape"],
        itcm_kib=256,dtcm_kib=512,elf_sha256=report["elf_sha256"],rtl_sha256=rtl_sha,
        vector_sha256=case["vector_sha256"],atol=ATOL,rtol=RTOL,
        input_readback_equal=inputs_ok,independent_output_check=outputs_ok,
        fault=fault,natural_halt=halted,firmware_status=values["status"],checked_elements=values["checked"],
        mismatches=values["mismatches"],rvv_calls=values["calls"],guard_ok=guards_ok and values["guard_ok"]==1,
        first_bad_index=values["first_bad"],stack_low_canary_intact=canary,
        scalar_cycles=scalar,rvv_cycles=rvv,empty_boundary_cycles=values["empty"],
        observation_elapsed_cycles=cycles,execution_wall_seconds=elapsed,requested_cycles=budget,
        scalar_max_abs_error=errors[0],rvv_max_abs_error=errors[1],
        source="official_FP32_matmul_other_operators_project_baselines_scalar_libm_exp_tanh",
        stack_check="low_64_bytes_not_full_watermark")
    dut._log.info(MARKER+json.dumps(row,sort_keys=True))
    assert values["kind"]==KINDS.index(case["kind"]),"Wrong dispatched operator"
    result=accept(row,index)
    dut._log.info("[LLM_TX_CYCLE_COMPARISON] "+json.dumps(result,sort_keys=True))


# Explicit individual test names; the driver never invokes the all-tests target.
@cocotb.test()
async def tx_f32_decode_test(dut): await run_case(dut,0)
@cocotb.test()
async def tx_f32_prefill_test(dut): await run_case(dut,1)
@cocotb.test()
async def tx_rms_decode_test(dut): await run_case(dut,2)
@cocotb.test()
async def tx_rms_prefill_test(dut): await run_case(dut,3)
@cocotb.test()
async def tx_rms_tail_test(dut): await run_case(dut,4)
@cocotb.test()
async def tx_softmax_short_test(dut): await run_case(dut,5)
@cocotb.test()
async def tx_softmax_extreme_tail_test(dut): await run_case(dut,6)
@cocotb.test()
async def tx_rope_decode_test(dut): await run_case(dut,7)
@cocotb.test()
async def tx_rope_prefill_test(dut): await run_case(dut,8)
@cocotb.test()
async def tx_swiglu_test(dut): await run_case(dut,9)
@cocotb.test()
async def tx_geglu_test(dut): await run_case(dut,10)
@cocotb.test()
async def tx_residual_test(dut): await run_case(dut,11)
@cocotb.test()
async def tx_kv_append_test(dut): await run_case(dut,12)
@cocotb.test()
async def tx_causal_prefill_test(dut): await run_case(dut,13)
@cocotb.test()
async def tx_causal_decode_test(dut): await run_case(dut,14)
@cocotb.test()
async def tx_causal_first_test(dut): await run_case(dut,15)
@cocotb.test()
async def tx_causal_future_poison_test(dut): await run_case(dut,16)
