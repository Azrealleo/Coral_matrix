async def run_case(dut,index,packet):
    assert os.environ.get('COCOTB_USE_FRONTDOOR')=='1'
    data=spec.fixture(index);report=packet.report;n=len(data['y'])
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
    begin=float(get_sim_time(unit='ns'));wall=time.monotonic();budget=10000000
    if not bool(int(dut.io_fault.value)) and not bool(int(dut.io_halted.value)):
        await First(ClockCycles(dut.io_aclk,budget),RisingEdge(dut.io_fault),RisingEdge(dut.io_halted));await ReadOnly()
    fault,halted=bool(int(dut.io_fault.value)),bool(int(dut.io_halted.value))
    cycles=round((float(get_sim_time(unit='ns'))-begin)/1.25);elapsed=time.monotonic()-wall
    await ClockCycles(dut.io_aclk,1);await fixture.core_mini_axi.halt()
    values={s:int(await fixture.read_word('lv_'+s)) for s in ('status','checked','mismatches','quality_mismatches',
        'guard_ok','empty_cycles','scalar_calls','project_calls','official_calls','probe_signature')}
    arrays={k:list(map(int,await fixture.read('lv_'+k,dtype=np.dtype('<u4'),shape=(4,))))
        for k in ('scalar_cycles','project_cycles','official_cycles')}
    inputs=True
    for symbol in ('x','w'):
        expected=spec.packed(data[symbol])+bytes(4096-4*len(data[symbol]))
        inputs=inputs and (await fixture.read('lv_'+symbol,size_bytes=4096)).tobytes()==expected
    guards=True;baselines=True;algorithm=True;quality=True;max_error=algorithm_error=None;bad_count=0
    gold=np.array(data['y'],dtype=np.float64);gold_algorithm=np.array(data['algorithm'],dtype=np.float64)
    for label in ('scalar','project','official'):
        raw=(await fixture.read('lv_'+label+'_out',size_bytes=4128)).tobytes();guard=spec.GUARD
        guards=guards and raw[:16]==guard*4 and raw[-16:]==guard*4 and raw[16+4*n:-16]==guard*(1024-n)
        actual=np.frombuffer(raw[16:16+4*n],dtype='<f4').astype(np.float64)
        matches=np.isfinite(actual)&(np.abs(actual-gold)<=spec.ATOL+spec.RTOL*np.abs(gold))
        if label!='official':baselines=baselines and bool(matches.all())
        else:
            quality=bool(matches.all());bad_count=int((~matches).sum())
            max_error=float(np.max(np.abs(actual-gold))) if bool(np.isfinite(actual).all()) else None
            algorithm_error=float(np.max(np.abs(actual-gold_algorithm))) if bool(np.isfinite(actual).all()) else None
            algorithm=bool(np.isfinite(actual).all()) and bool(np.all(np.abs(actual-gold_algorithm)<=spec.ATOL+spec.RTOL*np.abs(gold_algorithm)))
    canary=(await fixture.read(stack,size_bytes=64)).tobytes()==bytes([0xa5])*64
    row=dict(schema=1,scope=spec.PROBE_SCOPE if index==6 else spec.SCOPE,case_id=index,case=data['name'],kind=data['kind'],
        shape=list(data['shape']),itcm_kib=256,dtcm_kib=512,rtl_sha256=spec.RTL_SHA,elf_sha256=report['elf_sha256'],
        vector_sha256=data['vector_sha256'],algorithm_sha256=data['algorithm_sha256'],atol=spec.ATOL,rtol=spec.RTOL,
        fault=fault,natural_halt=halted,firmware_status=values['status'],checked_elements=values['checked'],
        algorithm_mismatches=values['mismatches'],scalar_calls=values['scalar_calls'],project_calls=values['project_calls'],
        official_calls=values['official_calls'],guard_ok=guards and values['guard_ok']==1,
        input_readback_equal=inputs,mathematical_baselines_check=baselines,official_algorithm_output_check=algorithm,
        strict_math_quality_pass=quality,strict_math_quality_mismatches=values['quality_mismatches'],
        official_max_math_abs_error=max_error,official_max_algorithm_abs_error=algorithm_error,
        stack_low_canary_intact=canary,stack_check='low_64_bytes_not_full_watermark',
        empty_boundary_cycles=values['empty_cycles'],requested_cycles=budget,observation_elapsed_cycles=cycles,
        execution_wall_seconds=elapsed,probe_signature=values['probe_signature'],**arrays)
    dut._log.info(spec.MARKER+json.dumps(row,sort_keys=True))
    if values['quality_mismatches']!=4*bad_count:raise ValueError('Firmware/frontdoor math-quality disagreement')
    result=spec.accept(row,index)
    dut._log.info('[OFFICIAL_RVV_COMPARISON] '+json.dumps(result,sort_keys=True))


@cocotb.test()
async def official_rvv_test(dut):
    assert os.environ.get('LV_CHILD')=='1'
    await run_case(dut,int(os.environ['LV_CASE']),lv_packet.load(os.environ['LV_PACKET']))
