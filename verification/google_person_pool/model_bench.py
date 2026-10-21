"""Actual combined VME+RVV complete-model execution; frontdoor only."""
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
from model_runner import load_runtime,selected_report,MARKER,BACKEND,sha


@cocotb.test()
async def person_pool_model_test(dut):
    assert os.environ.get("COCOTB_USE_FRONTDOOR")=="1"
    _,_,_,bundle=load_runtime(os.environ["PERSON_PACKAGE"])
    variant,case,budget=os.environ["PERSON_VARIANT"],os.environ["PERSON_CASE"],int(os.environ["PERSON_CYCLES"])
    report=selected_report(bundle,variant)
    symbols=dict(report["symbols"],**report["vme_symbols"],**report["pool_symbols"])
    fixture=await VerilatorTestFixture.Create(dut,csr_base_addr=0x02000000)
    load_start=time.monotonic()
    dut._log.info("[PERSON_POOL_MODEL_STAGE] frontdoor initialization and %s ELF/model/input readback",variant)
    await fixture.write(0,np.tile(np.array([0x13,0,0,0],dtype=np.uint8),256*1024//4))
    await fixture.write(0x01000000,np.full(512*1024,0xA5,dtype=np.uint8))
    await fixture.load_elf_and_lookup_symbols(bundle.root/bundle.manifest["firmwares"][variant]["file"],list(symbols),optional=False)
    assert fixture.entry_point==report["entry"]
    assert {n:fixture.symbols[n] for n in symbols}=={n:v["address"] for n,v in symbols.items()}
    model=await fixture.read("pd_model",size_bytes=300568)
    assert hashlib.sha256(model.tobytes()).hexdigest()==bundle.manifest["model_sha256"]
    inputs=(bundle.root/"inputs"/(case+".int8.bin")).read_bytes()
    await fixture.write("pd_input",inputs)
    assert (await fixture.read("pd_input",size_bytes=9216)).tobytes()==inputs
    await fixture.write("pd_output",bytes([37,53]))
    for n in ("pd_status","pd_arena_used","pd_invoke_cycles"):await fixture.write_word(n,0)
    stack=fixture.symbols["__stack_start__"];await fixture.write(stack,bytes([0xA5])*64)
    load_seconds=time.monotonic()-load_start
    dut._log.info("[PERSON_POOL_MODEL_STAGE] executing case=%s variant=%s budget=%d; no mid-run RAM polling",case,variant,budget)
    await fixture.core_mini_axi.execute_from(fixture.entry_point)
    await ClockCycles(dut.io_aclk,2);await ReadOnly()
    start=float(get_sim_time(unit="ns"));wall=time.monotonic()
    if not bool(int(dut.io_fault.value)) and not bool(int(dut.io_halted.value)):
        await First(ClockCycles(dut.io_aclk,budget),RisingEdge(dut.io_fault),RisingEdge(dut.io_halted))
        await ReadOnly()
    fault=bool(int(dut.io_fault.value));halted=bool(int(dut.io_halted.value))
    cycles=round((float(get_sim_time(unit="ns"))-start)/1.25);elapsed=time.monotonic()-wall
    await ClockCycles(dut.io_aclk,1);await fixture.core_mini_axi.halt()
    status=int(await fixture.read_word("pd_status"))
    used=int(await fixture.read_word("pd_arena_used"));invoke=int(await fixture.read_word("pd_invoke_cycles"))
    counters={}
    for n in sorted(set(report["vme_symbols"])|set(report["pool_symbols"])):counters[n]=int(await fixture.read_word(n))
    scores=list(map(int,await fixture.read("pd_output",dtype=np.int8,shape=(2,))))
    canary=(await fixture.read(stack,size_bytes=64)).tobytes()==bytes([0xA5])*64
    row=dict(schema=1,variant=variant,case=case,scope="complete_original_model_single_image",
        requested_cycles=budget,observation_elapsed_cycles=cycles,fault=fault,natural_halt=halted,
        firmware_status=status,inference_complete=halted and status==3,itcm_kib=256,dtcm_kib=512,
        elf_sha256=bundle.manifest["firmwares"][variant]["sha256"],model_sha256=bundle.manifest["model_sha256"],
        rtl_sha256=bundle.manifest["rtl_sha256"],input_sha256=sha(bundle.root/"inputs"/(case+".int8.bin")),
        model_readback_equal=True,input_readback_equal=True,scores_no_person_then_person=scores,
        arena_reserved_bytes=163840,arena_used_bytes=used,invoke_cycles=invoke,counters=counters,
        kernel_backend=BACKEND,depthwise="official_default_registration_unchanged",
        validation_executes_reference=variant=="validate",performance_eligible=variant=="fast",
        stack_low_canary_intact=canary,stack_check="low_64_bytes_only_not_full_watermark",
        execution_wall_seconds=elapsed,host_load_readback_wall_seconds=load_seconds,
        timing_scope="after_execute_release_plus_2_settle_cycles_to_halt_or_bounded_window_before_readback",
        stop_method="CSR_core_reset_clock_gate_not_resume_checkpoint")
    dut._log.info(MARKER+json.dumps(row,sort_keys=True))
    assert not fault and halted and status==3,"fault/premature halt/budget exhausted; see observation, NOT PASS"
    assert scores==bundle.manifest["reference_scores_no_person_then_person"][case] and invoke>0
    assert canary and 0<used<=163840
    assert counters["pd_vme_conv_calls"]==14 and counters["pd_pool_calls"]==1
    assert counters["pd_vme_commands"]>0 and counters["pd_pool_vector_blocks"]==16
    assert not any(counters[n] for n in ("pd_vme_fallback_calls","pd_vme_mismatches","pd_pool_fallbacks","pd_pool_mismatches"))
    if variant=="validate":assert counters["pd_vme_validated_layers"]==14 and counters["pd_pool_validated"]==1
