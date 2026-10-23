def audit_pair_loops(elf):
    """Verify real mt0/mt4 instructions and shared B loads in both K loops."""
    reports=[]
    for symbol in elf.get_section_by_name('.symtab').iter_symbols():
        if 'PairKLoop' not in symbol.name or not symbol['st_size'] or symbol['st_info']['type']!='STT_FUNC':continue
        section=elf.get_section(symbol['st_shndx']);start=int(symbol['st_value'])-int(section['sh_addr'])
        code=section.data()[start:start+int(symbol['st_size'])];ins=[];at=0
        while at<len(code):
            half=int.from_bytes(code[at:at+2],'little');size=4 if half&3==3 else 2
            if at+size>len(code):raise ValueError('Truncated pair instruction')
            w=int.from_bytes(code[at:at+size],'little');ins.append((at,size,w));at+=size
        backs=[]
        for a,size,w in ins:
            if size==4 and w&127==0x63:
                imm=((w>>31)<<12)|(((w>>7)&1)<<11)|(((w>>25)&63)<<5)|(((w>>8)&15)<<1)
                off=imm-8192 if imm&4096 else imm
                if off<0:backs.append((a+off,a))
            elif size==2 and w&3==1 and (w>>13)&7 in (6,7):
                imm=(((w>>12)&1)<<8)|(((w>>10)&3)<<3)|(((w>>5)&3)<<6)|(((w>>3)&3)<<1)|(((w>>2)&1)<<5)
                off=imm-512 if imm&256 else imm
                if off<0:backs.append((a+off,a))
        if len(backs)!=1:raise ValueError('Expected exactly one pair K backedge')
        lo,hi=backs[0]
        if lo not in {a for a,s,w in ins}:raise ValueError('Unaligned pair branch target')
        body=[(a,s,w) for a,s,w in ins if lo<=a<hi]
        cfg=[a for a,s,w in ins if s==4 and w&127==0x57 and (w>>12)&7==7 and w>>25==0x41]
        if len(cfg)!=1 or not 0<=cfg[0]<lo:raise ValueError('Pair configuration not hoisted')
        mats=[w for a,s,w in body if s==4 and w&127==0x77]
        if mats!=[0xf28800f7,0xf38804f7]:raise ValueError('Need distinct mt0/mt4 accumulators and A0/A1 sources')
        loads=[(w>>7)&31 for a,s,w in body if s==4 and w&127==7]
        if loads!=[8,10,12,14,16,18,20,22,24,26,28,30]:
            raise ValueError('Pair must load 12 unique vector rows with B only once')
        operands=[w for a,s,w in body if s==4 and w&127==7]
        if any(w&~((31<<7)|(31<<15))!=0x02000007 for w in operands):
            raise ValueError('Pair rows must be unmasked unit-stride vle8')
        pointers=[(w>>15)&31 for w in operands]
        if any(len(set(pointers[i:i+4]))!=1 for i in (0,4,8)) or len(set(pointers))!=3:
            raise ValueError('Pair A0/B/A1 must use three distinct pointer registers')
        for a,size,w in body:
            if size==4 and w&127 in (0x27,0x63,0x67,0x6f):raise ValueError('Store/control transfer inside pair K loop')
            if size==2 and ((w&3==1 and (w>>13)&7 in (1,5,6,7)) or
                            (w&3==2 and (w>>13)&7==4 and ((w>>2)&31)==0)):
                raise ValueError('Compressed transfer inside pair K loop')
        dims=sum(s==4 and w&127==0x57 and (w>>12)&7==7 and w>>25==0x42 for a,s,w in body)
        if dims not in (0,2):raise ValueError('Unexpected pair dimension changes')
        reports.append(dict(symbol=symbol.name,loop_start_offset=lo,loop_branch_offset=hi,
            matrix_tiles=[0,4],A_vector_bases=[8,24],shared_B_vector_base=16,
            vector_loads_per_Tk4_pair=12,single_tile_baseline_loads_per_pair=16,
            matrix_commands_per_iteration=2,mset_dimension_in_body=dims))
    if len(reports)!=2 or sorted(r['mset_dimension_in_body'] for r in reports)!=[0,2]:
        raise ValueError('Need full AND partial pair K loops')
    return reports


def audit_pair_tile_selector(elf):
    """Constant presence guard only, NOT a proof of dynamic TSS selection."""
    functions=[]
    for symbol in elf.get_section_by_name('.symtab').iter_symbols():
        if 'PairTileToRowMajor' not in symbol.name or not symbol['st_size'] or symbol['st_info']['type']!='STT_FUNC':continue
        section=elf.get_section(symbol['st_shndx']);start=int(symbol['st_value'])-int(section['sh_addr'])
        code=words(section.data()[start:start+int(symbol['st_size'])])
        # TSS(tile4,row0) = 4<<27. The fixed a0 register is consumed by the
        # explicit tile-move opcodes; actual row association needs the RTL probe.
        if 0x20000537 not in code:raise ValueError('Missing mt4 TSS selector constant in paired tile path')
        functions.append(symbol.name)
    if len(functions)!=1:raise ValueError('Need one paired tile move function')
    return dict(symbol=functions[0],tile4_tss_constant='0x20000000',dynamic_selection_proof=False)
