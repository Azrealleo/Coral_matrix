"""Real RTL frontdoor comparison of dense RVV and two VME scheduling scopes."""
import json
import os
import struct
import sys
import time
import types
import cocotb
import numpy as np
from cocotb.triggers import ClockCycles,First,ReadOnly,RisingEdge
from cocotb.utils import get_sim_time
import lv_spec as spec
import lv_packet

for n in ('bazel_tools','bazel_tools.tools','bazel_tools.tools.python','bazel_tools.tools.python.runfiles'):
    if n not in sys.modules:
        m=types.ModuleType(n);m.__path__=[];sys.modules[n]=m
shim=types.ModuleType('bazel_tools.tools.python.runfiles.runfiles');shim.Create=lambda:None
sys.modules[shim.__name__]=shim;sys.modules['bazel_tools.tools.python.runfiles'].runfiles=shim
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture


@cocotb.test()
async def llm_vme_linear_test(dut):
    assert os.environ.get('LV_CHILD')=='1' and os.environ.get('COCOTB_USE_FRONTDOOR')=='1'
    packet=lv_packet.load(os.environ['LV_PACKET']);index=int(os.environ['LV_CASE'])
    name,m,k,n=spec.CASES[index];gold=spec.vectors(index);report=packet.report
    fixture=await VerilatorTestFixture.Create(dut,csr_base_addr=0x02000000)
    await fixture.write(0,np.tile(np.array([0x13,0,0,0],dtype=np.uint8),256*1024//4))
    await fixture.write(0x01000000,np.full(512*1024,0xa5,dtype=np.uint8))
    await fixture.load_elf_and_lookup_symbols(packet.root/'probe_program.elf',list(report['symbols']),optional=False)
    assert fixture.entry_point==report['entry']
    assert {s:fixture.symbols[s] for s in report['symbols']}=={s:v['address'] for s,v in report['symbols'].items()}
    await fixture.write_word('lv_case',index);assert int(await fixture.read_word('lv_case'))==index
    stack=fixture.symbols['__stack_start__'];await fixture.write(stack,bytes([0xa5])*64)
    await fixture.core_mini_axi.execute_from(fixture.entry_point)
    await ClockCycles(dut.io_aclk,2);await ReadOnly()
    start=float(get_sim_time(unit='ns'));wall=time.monotonic();budget=10000000
    if not bool(int(dut.io_fault.value)) and not bool(int(dut.io_halted.value)):
        await First(ClockCycles(dut.io_aclk,budget),RisingEdge(dut.io_fault),RisingEdge(dut.io_halted));await ReadOnly()
    fault,halted=bool(int(dut.io_fault.value)),bool(int(dut.io_halted.value))
    cycles=round((float(get_sim_time(unit='ns'))-start)/1.25);elapsed=time.monotonic()-wall
    await ClockCycles(dut.io_aclk,1);await fixture.core_mini_axi.halt()
    values={s:int(await fixture.read_word('lv_'+s)) for s in ('status','checked','mismatches','signature','guard_ok','m','k','n',
        'rvv_calls','complete_calls','reuse_calls','prepack_calls','empty_cycles','prepack_cycles','complete_commands','reuse_commands')}
    assert (values['m'],values['k'],values['n'])==(m,k,n)
    arrays={s:list(map(int,await fixture.read('lv_'+s,dtype=np.dtype('<u4'),shape=(4,))))
        for s in ('rvv_cycles','complete_cycles','reuse_cycles')}
    inputs=True
    for symbol,raw,size in (('lv_x',gold['x'],1024),('lv_w',gold['w'],4096)):
        data=(await fixture.read(symbol,size_bytes=size)).tobytes()
        inputs=inputs and data==raw+bytes([0x5a])*(size-len(raw))
    expected=spec.GUARD*4+struct.pack('<'+'i'*(m*n),*gold['y'])+spec.GUARD*(1024-m*n)+spec.GUARD*4
    outputs=True
    for symbol in ('lv_rvv_out','lv_complete_out','lv_reuse_out'):
        actual=(await fixture.read(symbol,size_bytes=4128)).tobytes();outputs=outputs and actual==expected
    packed=True
    for symbol in ('lv_complete_weights','lv_reuse_weights'):
        actual=(await fixture.read(symbol,size_bytes=4384)).tobytes();packed=packed and actual==spec.packed_weights(index)
    work=(await fixture.read('lv_workspace',size_bytes=2080)).tobytes()==spec.workspace(index)
    canary=(await fixture.read(stack,size_bytes=64)).tobytes()==bytes([0xa5])*64
    row=dict(schema=1,scope=spec.SCOPE,case_id=index,case=name,M=m,K=k,N=n,itcm_kib=256,dtcm_kib=512,
        elf_sha256=report['elf_sha256'],rtl_sha256=spec.RTL_SHA,vector_sha256=gold['vector_sha256'],
        fault=fault,natural_halt=halted,firmware_status=values['status'],checked_elements=values['checked'],
        mismatches=values['mismatches'],signature=values['signature'],guard_ok=values['guard_ok']==1,
        rvv_calls=values['rvv_calls'],complete_calls=values['complete_calls'],reuse_calls=values['reuse_calls'],
        prepack_calls=values['prepack_calls'],complete_commands=values['complete_commands'],reuse_commands=values['reuse_commands'],
        empty_boundary_cycles=values['empty_cycles'],prepack_once_cycles=values['prepack_cycles'],
        input_readback_equal=inputs,output_readback_equal=outputs,packed_readback_equal=packed,workspace_readback_equal=work,
        stack_low_canary_intact=canary,stack_check='low_64_bytes_not_full_watermark',
        requested_cycles=budget,observation_elapsed_cycles=cycles,execution_wall_seconds=elapsed,**arrays)
    dut._log.info(spec.MARKER+json.dumps(row,sort_keys=True))
    comparison=spec.accept(row,index)
    dut._log.info('[LLM_VME_COMPARISON] '+json.dumps(comparison,sort_keys=True))
