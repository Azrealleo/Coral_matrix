def audit_hoisted_loops(elf):
    """Audit real RV32+C control flow, not a search for instruction strings.

    Both template instances must have ONE backward branch, ONE matrix opcode
    in its body, and the only msetmtype strictly BEFORE that body. No calls or
    other branches/jumps are permitted inside the accumulation loop.
    """
    loops=[]
    for symbol in elf.get_section_by_name('.symtab').iter_symbols():
        if 'HoistedKLoop' not in symbol.name or not symbol['st_size'] or symbol['st_info']['type']!='STT_FUNC':continue
        section=elf.get_section(symbol['st_shndx']);start=int(symbol['st_value'])-int(section['sh_addr'])
        raw=section.data()[start:start+int(symbol['st_size'])];ins=[];at=0
        while at<len(raw):
            half=int.from_bytes(raw[at:at+2],'little');size=4 if half&3==3 else 2
            if at+size>len(raw):raise ValueError('Truncated K loop instruction')
            word=int.from_bytes(raw[at:at+size],'little');ins.append((at,size,word));at+=size
        backs=[]
        for at,size,w in ins:
            if size==4 and w&127==0x63:
                imm=((w>>31)<<12)|(((w>>7)&1)<<11)|(((w>>25)&63)<<5)|(((w>>8)&15)<<1)
                offset=imm-8192 if imm&4096 else imm
                if offset<0:backs.append((at+offset,at))
            elif size==2 and w&3==1 and (w>>13)&7 in (6,7):
                imm=(((w>>12)&1)<<8)|(((w>>10)&3)<<3)|(((w>>5)&3)<<6)|(((w>>3)&3)<<1)|(((w>>2)&1)<<5)
                offset=imm-512 if imm&256 else imm
                if offset<0:backs.append((at+offset,at))
        if len(backs)!=1:raise ValueError('Expected exactly one backward K branch')
        first,last=backs[0];body=[(a,s,w) for a,s,w in ins if first<=a<last]
        if first not in {a for a,s,w in ins}:raise ValueError('K branch target is not an instruction boundary')
        configs=[a for a,s,w in ins if s==4 and w&127==0x57 and (w>>12)&7==7 and w>>25==0x41]
        matrices=[a for a,s,w in ins if s==4 and w==0xf28800f7]
        if len(configs)!=1 or not 0<=configs[0]<first or len(matrices)!=1 or not first<=matrices[0]<last:
            raise ValueError('Matrix configuration is not hoisted before K loop')
        for a,size,w in body:
            if size==4 and w&127 in (0x63,0x67,0x6f):raise ValueError('Control transfer inside K body')
            if size==2 and ((w&3==1 and (w>>13)&7 in (1,5,6,7)) or
                            (w&3==2 and (w>>13)&7==4 and ((w>>2)&31)==0)):
                raise ValueError('Compressed control transfer inside K body')
        if len([1 for a,s,w in body if s==4 and w&127==7])!=8:
            raise ValueError('Expected eight operand loads per Tk4')
        dimensions=sum(s==4 and w&127==0x57 and (w>>12)&7==7 and w>>25==0x42 for a,s,w in body)
        if dimensions not in (0,2):raise ValueError('Unexpected in-loop dimension configuration')
        loops.append(dict(symbol=symbol.name,loop_start_offset=first,loop_branch_offset=last,
                          matrix_commands_in_body=1,operand_loads_in_body=8,
                          msetmtype_in_body=0,mset_dimension_in_body=dimensions))
    if len(loops)!=2 or sorted(l['mset_dimension_in_body'] for l in loops)!=[0,2]:
        raise ValueError('Need full-width AND partial-width audited K loops')
    return loops
