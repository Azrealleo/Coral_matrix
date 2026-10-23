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

try:
    from bazel_tools.tools.python.runfiles import runfiles as _real_runfiles
except ImportError:
    for n in ('bazel_tools','bazel_tools.tools','bazel_tools.tools.python','bazel_tools.tools.python.runfiles'):
        if n not in sys.modules:
            module=types.ModuleType(n);module.__path__=[];sys.modules[n]=module
    shim=types.ModuleType('bazel_tools.tools.python.runfiles.runfiles');shim.Create=lambda:None
    sys.modules[shim.__name__]=shim;sys.modules['bazel_tools.tools.python.runfiles'].runfiles=shim
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture


async def run_case(dut,index,packet):
    assert os.environ.get('COCOTB_USE_FRONTDOOR')=='1'
    probe=index==spec.PROBE_INDEX
    if probe:
        m,k,n=spec.PROBE_SHAPES[-1];name='optimized_instruction_probe';gold=spec.probe_vectors(len(spec.PROBE_SHAPES)-1)
    else:name,m,k,n=spec.CASES[index];gold=spec.vectors(index)
    report=packet.report
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
    start=float(get_sim_time(unit='ns'));wall=time.monotonic();budget=5000000 if probe else 10000000
    if not bool(int(dut.io_fault.value)) and not bool(int(dut.io_halted.value)):
        await First(ClockCycles(dut.io_aclk,budget),RisingEdge(dut.io_fault),RisingEdge(dut.io_halted));await ReadOnly()
    fault,halted=bool(int(dut.io_fault.value)),bool(int(dut.io_halted.value))
    cycles=round((float(get_sim_time(unit='ns'))-start)/1.25);elapsed=time.monotonic()-wall
    await ClockCycles(dut.io_aclk,1);await fixture.core_mini_axi.halt()
    values={s:int(await fixture.read_word('lv_'+s)) for s in ('status','checked','mismatches','signature','guard_ok','m','k','n',
        'rvv_calls','complete_calls','reuse_calls','prepack_calls','empty_cycles','prepack_cycles','complete_commands','reuse_commands',
        'opt_complete_calls','opt_reuse_calls','opt_prepack_calls','opt_prepack_cycles','opt_complete_commands','opt_reuse_commands',
        'probe_cases','probe_checked','probe_signature','probe_mismatches','probe_fail_case','probe_commands',
        'probe_current_case','probe_step','probe_first_element','probe_first_actual','probe_first_expected')}
    arrays={s:list(map(int,await fixture.read('lv_'+s,dtype=np.dtype('<u4'),shape=(4,))))
        for s in ('rvv_cycles','complete_cycles','reuse_cycles','opt_complete_cycles','opt_reuse_cycles')}
    tiles={}
    for label in ('opt_complete','opt_reuse','probe'):
        fast,fallback=map(int,await fixture.read('lv_'+label+'_tiles',dtype=np.dtype('<u4'),shape=(2,)))
        tiles[label+'_fast_tiles']=fast;tiles[label+'_fallback_tiles']=fallback
    inputs=True
    for symbol,raw,size in (('lv_x',gold['x'],1024),('lv_w',gold['w'],4096)):
        data=(await fixture.read(symbol,size_bytes=size)).tobytes()
        inputs=inputs and data==raw+bytes([0x5a])*(size-len(raw))
    expected=spec.GUARD*4+struct.pack('<'+'i'*(m*n),*gold['y'])+spec.GUARD*(1024-m*n)+spec.GUARD*4
    outputs=True
    output_symbols=('lv_opt_complete_out',) if probe else ('lv_rvv_out','lv_complete_out','lv_reuse_out','lv_opt_complete_out','lv_opt_reuse_out')
    for symbol in output_symbols:
        actual=(await fixture.read(symbol,size_bytes=4128)).tobytes();outputs=outputs and actual==expected
    packed=True
    weight_symbols=('lv_complete_weights','lv_opt_complete_weights') if probe else ('lv_complete_weights','lv_reuse_weights','lv_opt_complete_weights','lv_opt_reuse_weights')
    expected_weights=spec.packed_weights_for(m,k,n,gold)
    for symbol in weight_symbols:
        actual=(await fixture.read(symbol,size_bytes=4384)).tobytes();packed=packed and actual==expected_weights
    work=(await fixture.read('lv_opt_workspace',size_bytes=2080)).tobytes()==spec.workspace_for(m,k,n,gold,direct=True)
    if not probe:work=work and (await fixture.read('lv_workspace',size_bytes=2080)).tobytes()==spec.workspace(index)
    canary=(await fixture.read(stack,size_bytes=64)).tobytes()==bytes([0xa5])*64
    # Even a premature trap must emit diagnostic state BEFORE strict rejection.
    row=dict(schema=1,scope=spec.PROBE_SCOPE if probe else spec.SCOPE,case_id=index,case=name,
        M=values['m'],K=values['k'],N=values['n'],itcm_kib=256,dtcm_kib=512,
        elf_sha256=report['elf_sha256'],rtl_sha256=spec.RTL_SHA,
        fault=fault,natural_halt=halted,firmware_status=values['status'],checked_elements=values['checked'],
        mismatches=values['mismatches'],signature=values['signature'],guard_ok=values['guard_ok']==1,
        rvv_calls=values['rvv_calls'],complete_calls=values['complete_calls'],reuse_calls=values['reuse_calls'],
        prepack_calls=values['prepack_calls'],complete_commands=values['complete_commands'],reuse_commands=values['reuse_commands'],
        opt_complete_calls=values['opt_complete_calls'],opt_reuse_calls=values['opt_reuse_calls'],opt_prepack_calls=values['opt_prepack_calls'],
        opt_complete_commands=values['opt_complete_commands'],opt_reuse_commands=values['opt_reuse_commands'],
        empty_boundary_cycles=values['empty_cycles'],prepack_once_cycles=values['prepack_cycles'],opt_prepack_once_cycles=values['opt_prepack_cycles'],
        input_readback_equal=inputs,output_readback_equal=outputs,packed_readback_equal=packed,workspace_readback_equal=work,
        stack_low_canary_intact=canary,stack_check='low_64_bytes_not_full_watermark',
        requested_cycles=budget,observation_elapsed_cycles=cycles,execution_wall_seconds=elapsed,**arrays,**tiles)
    if probe:
        row.update({key:values[key] for key in ('probe_cases','probe_checked','probe_signature','probe_mismatches','probe_fail_case','probe_commands',
            'probe_current_case','probe_step','probe_first_element','probe_first_actual','probe_first_expected')})
        row['probe_vector_set_sha256']=spec.probe_contract()['probe_vector_set_sha256']
    else:row['vector_sha256']=gold['vector_sha256']
    dut._log.info(spec.MARKER+json.dumps(row,sort_keys=True))
    comparison=spec.accept(row,index)
    dut._log.info('[LLM_VME_OPT_COMPARISON] '+json.dumps(comparison,sort_keys=True))


@cocotb.test()
async def llm_vme_opt_test(dut):
    assert os.environ.get('LV_CHILD')=='1'
    await run_case(dut,int(os.environ['LV_CASE']),lv_packet.load(os.environ['LV_PACKET']))
