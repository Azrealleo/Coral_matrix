"""Native/reference, actual RV32 objects and tool checks; NOT RTL simulation."""
import ast
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import lv_spec as spec
import lv_audit as audit
import lv_packet as packet
import prepare
import server
import vm
import summarize

HERE=Path(__file__).resolve().parent


def observation(index=0):
    name,m,k,n=spec.CASES[index]
    return dict(schema=1,scope=spec.SCOPE,case_id=index,case=name,M=m,K=k,N=n,itcm_kib=256,dtcm_kib=512,
        fault=False,natural_halt=True,firmware_status=3,mismatches=0,guard_ok=True,stack_low_canary_intact=True,
        input_readback_equal=True,output_readback_equal=True,packed_readback_equal=True,workspace_readback_equal=True,
        checked_elements=20*m*n,signature=spec.expected_signature(index),rvv_calls=4,complete_calls=4,reuse_calls=4,
        prepack_calls=1,complete_commands=4*spec.commands(index),reuse_commands=4*spec.commands(index),
        vector_sha256=spec.vectors(index)['vector_sha256'],elf_sha256='a'*64,rtl_sha256=spec.RTL_SHA,
        requested_cycles=10000000,observation_elapsed_cycles=100000,empty_boundary_cycles=3,prepack_once_cycles=1000,
        opt_complete_calls=4,opt_reuse_calls=4,opt_prepack_calls=1,opt_prepack_once_cycles=500,
        opt_complete_commands=4*spec.commands(index),opt_reuse_commands=4*spec.commands(index),
        opt_complete_fast_tiles=4*((n+15)//16),opt_reuse_fast_tiles=4*((n+15)//16),
        opt_complete_fallback_tiles=0,opt_reuse_fallback_tiles=0,
        rvv_cycles=[2000]*4,complete_cycles=[1000]*4,reuse_cycles=[500]*4,
        opt_complete_cycles=[800]*4,opt_reuse_cycles=[300]*4)


def host_text():
    p=spec.probe_contract()
    return ''.join(f'[LV_HOST_REFERENCE] id={i} checked={20*c[1]*c[3]} signature={spec.expected_signature(i)} commands_each={4*spec.commands(i)} VME_RVV=NOT_RUN\n'
        for i,c in enumerate(spec.CASES))+'[LV_OPT_PACK_HOST_PASS] cases=980 hardware=NOT_RUN\n'+f"[LV_OPT_PROBE_HOST_PASS] cases={p['probe_cases']} checked={p['probe_checked']} signature={p['probe_signature']} hardware=NOT_RUN\n"


def probe_observation():
    return dict(schema=1,scope=spec.PROBE_SCOPE,case_id=4,case='optimized_instruction_probe',M=16,K=64,N=64,
        itcm_kib=256,dtcm_kib=512,fault=False,natural_halt=True,firmware_status=3,guard_ok=True,
        input_readback_equal=True,output_readback_equal=True,packed_readback_equal=True,workspace_readback_equal=True,
        stack_low_canary_intact=True,probe_mismatches=0,probe_fail_case=0xffffffff,
        probe_current_case=8,probe_step=6,probe_first_element=0xffffffff,probe_first_actual=0,probe_first_expected=0,
        rtl_sha256=spec.RTL_SHA,elf_sha256='a'*64,requested_cycles=5000000,observation_elapsed_cycles=10000,**spec.probe_contract())


def fake_preparation(root):
    """Control-flow fixture ONLY: never a real prepared model or ELF."""
    prepared=root/'prepared';prepared.mkdir();study=root/'study';study.mkdir();source=study/'source';source.mkdir()
    execution=study/'execroot';execution.mkdir()
    model=execution/'bazel-out/mock/model'/spec.TOP;model.parent.mkdir(parents=True);model.write_bytes(b'synthetic model; NOT executable')
    elf=execution/'bazel-out/mock/probe_program.elf';elf.write_bytes(b'synthetic ELF; NOT executable')
    bundle=prepared/'firmware'/spec.PACKET_NAME;bundle.mkdir(parents=True)
    (bundle/'probe_program.elf').write_bytes(elf.read_bytes());(bundle/'manifest.json').write_text('{"fixture_only":true}')
    generated=source/spec.PACKAGE/'code.cc';generated.parent.mkdir(parents=True);generated.write_bytes(b'synthetic source')
    manifest=dict(scope=spec.SCOPE,files={spec.PACKAGE+'/code.cc':spec.sha(generated)})
    (source/prepare.MANIFEST).write_text(json.dumps(manifest))
    packet=SimpleNamespace(root=bundle,report={'elf_sha256':spec.sha(elf)},manifest={'files':{}})
    def query(prefix,cwd,args):
        if args[:2]==['info','execution_root']:return str(execution)
        return model.relative_to(execution).as_posix() if 'deps(' in args[-1] else elf.relative_to(execution).as_posix()
    return prepared,study,source,packet,query,model,generated


class Checks(unittest.TestCase):
    def test_original_reference_and_qualified_tile_are_byte_identical(self):
        self.assertEqual(spec.sha(spec.reference_path()),spec.REFERENCE_SHA)
        self.assertEqual(spec.sha(HERE.parent/'google_person_vme/vme_tile.h'),spec.TILE_SHA)
        for i,c in enumerate(spec.CASES):
            gold=spec.vectors(i);self.assertEqual(len(gold['y']),c[1]*c[3])
            self.assertEqual(len(spec.packed_weights(i)),4384);self.assertEqual(len(spec.workspace(i)),2080)
            self.assertEqual(len(spec.optimized_workspace(i)),2080)

    def test_unsigned_bias_transform_matches_signed_dot_all_four(self):
        import struct
        for i,(_,m,k,n) in enumerate(spec.CASES):
            v=spec.vectors(i);x=list(struct.unpack('<'+'b'*len(v['x']),v['x']))
            packed=spec.packed_weights(i);w=list(struct.unpack('<4096b',packed[16:4112]));bias=struct.unpack('<64i',packed[4112:-16])
            for r in range(m):
                for c in range(n):
                    first=c//16*16;value=bias[c]+sum(w[first*k+d*16+c%16]*(x[r*k+d]+128) for d in range(k))
                    self.assertEqual(value,v['y'][r*n+c])

    def test_actual_native_main_and_980_boundary_arithmetic_cases(self):
        compiler=os.environ.get('LLM_TEST_CXX')
        if not compiler:self.skipTest('Set LLM_TEST_CXX')
        logs=[]
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name,defines in (('linear_bench.cc',['-DLV_HOST=1']),('core_test.cc',['-DLV_HOST=1'])):
                executable=root/(name+('.exe' if os.name=='nt' else '.out'))
                build=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',*defines,'-I'+str(HERE),str(HERE/name),'-o',str(executable)],capture_output=True,text=True,encoding='utf-8',errors='replace')
                self.assertEqual(build.returncode,0,build.stdout+build.stderr)
                run=subprocess.run([str(executable)],capture_output=True,text=True)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr);logs.append(run.stdout)
        spec.checked_host(''.join(logs))

    def test_real_rv32_objects_and_vme_encodings_not_hardware_execution(self):
        compiler=os.environ.get('LLM_TEST_CROSS');objdump=os.environ.get('LLM_TEST_OBJDUMP')
        if not compiler or not objdump:self.skipTest('Set target compiler/objdump')
        repo=HERE.parent.parent
        official=subprocess.check_output(['git','--git-dir='+str(repo/'.upstream-git/coralnpu-google.git'),'show',spec.UPSTREAM+':'+prepare.OFFICIAL])
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name,raw in (('linear_bench.cc',(HERE/'linear_bench.cc').read_bytes()),('rvv_int8_matmul.cc',official)):
                source=root/name;source.write_bytes(raw)
                built=subprocess.run([compiler,'-std=c++17','-march=rv32imafcv_zicsr','-mabi=ilp32f','-O2','-Wall','-Wextra','-Werror',
                    '-fno-tree-vectorize','-fno-tree-slp-vectorize','-fno-lto','-I'+str(HERE),
                    '-I'+str(HERE.parent/'google_person_vme'),'-c',str(source),'-o',str(source.with_suffix('.o'))],capture_output=True,text=True,encoding='utf-8',errors='replace')
                self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            output=subprocess.check_output([objdump,'-d','-C','-M','no-aliases',str(root/'linear_bench.o')],text=True)
            self.assertIn('f28800f7',output);self.assertIn('vle8.v',output);self.assertIn('vse32.v',output)
            for operation in ('vlse8.v','vsse32.v','vxor.vx','vmv.s.x','vwadd.vx','vadd.vv'):
                self.assertTrue(operation in output,'Missing target instruction: '+operation)
            # Only this translation unit, not the official CRT: main must
            # return, leaving the CRT's success mpause/failure ebreak intact.
            self.assertNotRegex(output,r'\b(?:e?break|wfi)\b')
            rvv=subprocess.check_output([objdump,'-d',str(root/'rvv_int8_matmul.o')],text=True)
            self.assertIn('vwmul',rvv);self.assertIn('vwmacc',rvv)
            from elftools.elf.elffile import ELFFile
            with (root/'linear_bench.o').open('rb') as f:
                elf=ELFFile(f);table=elf.get_section_by_name('.symtab')
                symbols={s.name:s for s in table.iter_symbols()}
                for name,size in audit.SIZES.items():self.assertEqual(symbols[name]['st_size'],size,name)
                selector=symbols['lv_case'];section=elf.get_section(selector['st_shndx'])
                self.assertEqual(section.data()[selector['st_value']:selector['st_value']+4],b'\xfe\xff\xff\xff')
                self.assertFalse(any('_GLOBAL__sub_I' in n for n in symbols))
            # A local synthetic bare-metal link checks the REAL ELF parser and
            # symbol geometry, not official VM CRT/toolchain or execution.
            support=root/'support.cc';support.write_text('''extern "C" void* memset(void* p,int v,unsigned n) {
  volatile unsigned char* q=(volatile unsigned char*)p;for(unsigned i=0;i<n;++i)q[i]=(unsigned char)v;return p;}
extern "C" void* memcpy(void* p,const void* s,unsigned n) {
  volatile unsigned char* q=(volatile unsigned char*)p;const unsigned char* r=(const unsigned char*)s;
  for(unsigned i=0;i<n;++i)q[i]=r[i];return p;}
''')
            linker=root/'synthetic.ld';linker.write_text('''MEMORY {
 ITCM (rx) : ORIGIN = 0, LENGTH = 256K
 DTCM (rw) : ORIGIN = 0x01000000, LENGTH = 512K
}
SECTIONS {
 .text : { *(.text*) *(.rodata*) *(.eh_frame*) } > ITCM
 .data : { *(.data*) *(.sdata*) } > DTCM
 .bss (NOLOAD) : { *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(16); __heap_start__ = .; } > DTCM
 __heap_end__ = 0x0107c000; __stack_start__ = 0x0107c000; __stack_end__ = 0x01080000;
}
''')
            linked=root/'synthetic.elf'
            result=subprocess.run([compiler,'-std=c++17','-march=rv32imafcv_zicsr','-mabi=ilp32f','-O2',
                '-nostdlib',str(root/'linear_bench.o'),str(root/'rvv_int8_matmul.o'),str(support),
                '-Wl,-e,main','-Wl,-T,'+str(linker),'-o',str(linked)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            report=audit.inspect(linked.read_bytes());self.assertEqual(report['NPU_RTL'],'NOT_RUN')
            self.assertLess(report['itcm_occupied_extent_bytes'],262144)
            # Mutate a REAL linked instruction, leaving geometry valid. The
            # code audit must reject an ordinary VSET in the matrix fragment.
            data=bytearray(linked.read_bytes());elf=ELFFile(io.BytesIO(data))
            symbol=next(s for s in elf.get_section_by_name('.symtab').iter_symbols() if 'FastTileToRowMajor' in s.name and s['st_size'])
            section=elf.get_section(symbol['st_shndx']);start=section['sh_offset']+symbol['st_value']-section['sh_addr']
            offset=start
            while offset<start+symbol['st_size']:
                half=int.from_bytes(data[offset:offset+2],'little')
                if half&3!=3:offset+=2;continue
                instruction=int.from_bytes(data[offset:offset+4],'little')
                if instruction&127==0x57 and (instruction>>12)&7==7 and instruction>>25==0x41:break
                offset+=4
            self.assertLess(offset,start+symbol['st_size'])
            data[offset:offset+4]=(0x0d207057).to_bytes(4,'little')
            with self.assertRaisesRegex(ValueError,'clear mtype'):audit.inspect(bytes(data))

    def test_exhaustive_native_dimensions_1_16_by_1_64_by_1_64(self):
        compiler=os.environ.get('LLM_TEST_CXX')
        if not compiler:self.skipTest('Set LLM_TEST_CXX')
        with tempfile.TemporaryDirectory() as temporary:
            executable=Path(temporary)/('exhaustive.exe' if os.name=='nt' else 'exhaustive')
            result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-DLV_HOST=1','-DLV_EXHAUSTIVE=1',
                '-I'+str(HERE),str(HERE/'core_test.cc'),'-o',str(executable)],capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(result.returncode,0,result.stderr)
            run=subprocess.run([str(executable)],capture_output=True,text=True,timeout=180)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('[LV_OPT_EXHAUSTIVE_HOST_PASS] cases=65536 hardware=NOT_RUN',run.stdout)

    def test_amortized_prepack_is_charged_and_slow_vme_is_valid(self):
        row=observation();result=spec.accept(row,0)
        self.assertEqual(result['reuse_first_including_prepack_cycles'],1500)
        self.assertEqual(result['reuse_four_calls_including_prepack_cycles'],3000)
        self.assertEqual(result['rvv_over_vme_reuse_four_calls_including_prepack'],8000/3000)
        row['complete_cycles']=[4000]*4;row['reuse_cycles']=[3000]*4
        self.assertLess(spec.accept(row,0)['steady_rvv_over_vme_complete'],1)
        self.assertLess(spec.accept(row,0)['steady_rvv_over_vme_reuse_excluding_prepack'],1)
        result=spec.accept(row,0)
        self.assertEqual(result['opt_reuse_first_including_prepack_cycles'],800)
        self.assertEqual(result['opt_reuse_four_calls_including_prepack_cycles'],1700)
        row['opt_complete_cycles']=[8000]*4;row['opt_reuse_cycles']=[4000]*4
        self.assertLess(spec.accept(row,0)['steady_rvv_over_opt_complete'],1)
        self.assertLess(spec.accept(row,0)['steady_rvv_over_opt_reuse_excluding_prepack'],1)

    def test_no_false_pass_missing_paths_corrupt_data_or_cycle_windows(self):
        row=observation()
        for name,value in dict(fault=True,natural_halt=False,firmware_status=2,mismatches=1,signature=0,
            guard_ok=False,packed_readback_equal=False,workspace_readback_equal=False,output_readback_equal=False,
            rvv_calls=0,reuse_calls=0,prepack_calls=0,complete_calls=0,complete_commands=0,reuse_commands=0,
            prepack_once_cycles=0,rvv_cycles=[2000]*3,complete_cycles=[0]*4,observation_elapsed_cycles=100,
            opt_prepack_once_cycles=0,opt_complete_commands=0,opt_reuse_commands=0,opt_prepack_calls=0,
            opt_complete_calls=0,opt_reuse_calls=0,opt_complete_fallback_tiles=1,opt_reuse_fast_tiles=0,
            opt_complete_cycles=[1]*4,opt_reuse_cycles=[False]*4,
            requested_cycles=2000000,rtl_sha256='b'*64,vector_sha256='c'*64).items():
            bad=copy.deepcopy(row);bad[name]=value
            with self.subTest(name=name),self.assertRaises(ValueError):spec.accept(bad,0)

    def test_native_log_requires_both_tests_and_all_signatures(self):
        text=host_text();spec.checked_host(text)
        for bad in (text*2,text.replace('cases=980','cases=979'),text.replace('id=0','id=1'),text+'FAILED\n',text.splitlines()[0]):
            with self.assertRaises(ValueError):spec.checked_host(bad)

    def test_build_rules_do_not_repeat_cc_test_hdrs_mistake(self):
        tree=ast.parse(prepare.build_text());tests=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='cc_test']
        self.assertEqual(len(tests),2)
        for node in tests:
            attrs={kw.arg:ast.literal_eval(kw.value) for kw in node.keywords}
            self.assertNotIn('hdrs',attrs);self.assertIn('linear_core.h',attrs['srcs'])
        shell=(HERE/'build_export.sh').read_text();self.assertNotIn(':model',shell);self.assertNotIn('--test_timeout',shell)
        self.assertIn('host_packing_test',shell)
        self.assertIn('"//tests/cocotb/llm_linear_v1:model"',prepare.build_text())
        self.assertIn('candidate_probe_test',prepare.build_text())
        self.assertIn('choices=range(5),default=4',(HERE/'server.py').read_text())

    def test_install_is_idempotent_and_refuses_overwrite(self):
        files={'rvv_int8_matmul.cc':b'official','linear_bench.cc':b'bench'}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);a=prepare.install(root,files);self.assertEqual(a,prepare.install(root,files))
            path=root/spec.PACKAGE/'linear_bench.cc';path.write_bytes(b'user edit')
            with self.assertRaises(ValueError):prepare.install(root,files)
            self.assertEqual(path.read_bytes(),b'user edit')

    def test_opt_uses_crt_exit_and_preserves_v2_artifacts(self):
        source=(HERE/'linear_bench.cc').read_text().split('#else\n  const unsigned selected=lv_case;',1)[1]
        self.assertIn('if(selected>=4){lv_status=99;return 1;}',source)
        self.assertIn('return Run(selected);',source)
        self.assertNotIn('asm volatile(',source)
        self.assertEqual(spec.PACKAGE,'tests/cocotb/llm_vme_opt_v1')
        self.assertEqual(prepare.MANIFEST,'llm_vme_opt_v1_manifest.json')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);old=root/'tests/cocotb/llm_vme_linear_v2';old.mkdir(parents=True)
            (old/'linear_bench.cc').write_bytes(b'v2 measured source must stay')
            marker=root/'llm_vme_linear_v2_manifest.json';marker.write_bytes(b'original sealed v2 manifest')
            prepare.install(root,{'rvv_int8_matmul.cc':b'official','linear_bench.cc':b'new opt source'})
            self.assertEqual((old/'linear_bench.cc').read_bytes(),b'v2 measured source must stay')
            self.assertEqual(marker.read_bytes(),b'original sealed v2 manifest')
            self.assertEqual((root/spec.PACKAGE/'linear_bench.cc').read_bytes(),b'new opt source')
        bad=observation();bad['fault']=True
        with self.assertRaisesRegex(ValueError,r': fault$'):spec.accept(bad,0)

    def test_raw_xml_and_exit_state_gate(self):
        helper=SimpleNamespace(json_row=lambda text,marker:json.loads(next(s.split(marker,1)[1] for s in text.splitlines() if marker in s)))
        with tempfile.TemporaryDirectory() as temporary,patch.object(server,'helper',return_value=helper):
            root=Path(temporary);bundle=SimpleNamespace(root=root,report={'elf_sha256':'a'*64})
            (root/'_test-status.json').write_text('{"exit_code":0,"timed_out":false}')
            (root/'results.xml').write_text('<testsuite><testcase name="llm_vme_opt_test"/></testsuite>')
            (root/'_test.log').write_text(spec.MARKER+json.dumps(observation())+'\x1b[39m\nTESTS=1 PASS=1 FAIL=0 SKIP=0')
            server.checked_results(root,bundle,0)
            for tag in ('failure','error','skipped'):
                (root/'results.xml').write_text('<testsuite><testcase name="llm_vme_opt_test"><'+tag+'/></testcase></testsuite>')
                with self.assertRaises(ValueError):server.checked_results(root,bundle,0)
            for key in ('failures','errors','skipped'):
                (root/'results.xml').write_text('<testsuite '+key+'="1"><testcase name="llm_vme_opt_test"/></testsuite>')
                with self.assertRaises(ValueError):server.checked_results(root,bundle,0)

    def test_elf_audit_rejects_wrong_map_missing_selector_or_overlap(self):
        class Segment(dict):
            def data(self):return b'\xfe\xff\xff\xff'
        class Symbol(dict):
            def __init__(self,name,address,size):
                super().__init__(st_value=address,st_size=size,st_shndx=1);self.name=name
        class Elf:
            elfclass=32;little_endian=True;header=dict(e_machine='EM_RISCV',e_entry=0)
            def __init__(self):
                self.segments=[Segment(p_type='PT_LOAD',p_paddr=0,p_vaddr=0,p_memsz=4096,p_filesz=4096,p_flags=5),
                    Segment(p_type='PT_LOAD',p_paddr=0x01000000,p_vaddr=0x01000000,p_memsz=65536,p_filesz=4,p_flags=6)]
                self.symbols=[];at=0x01000000
                for name,size in audit.SIZES.items():self.symbols.append(Symbol(name,at,size));at+=size
                for name,at in zip(audit.LINKER,(0x0107c000,0x01080000,0x01010000,0x0107c000)):
                    self.symbols.append(Symbol(name,at,0))
            def iter_segments(self):return iter(self.segments)
            def get_section_by_name(self,name):return self
            def iter_symbols(self):return iter(self.symbols)
        elf=Elf()
        with patch.object(audit,'ELFFile',return_value=elf),patch.object(audit,'instruction_audit',return_value={'mock':'geometry_only'}):audit.inspect(b'synthetic')
        failures=[]
        bad=copy.deepcopy(elf);bad.elfclass=64;failures.append(bad)
        bad=copy.deepcopy(elf);bad.segments[1]['p_filesz']=0;failures.append(bad)
        bad=copy.deepcopy(elf);bad.symbols[1]['st_value']=bad.symbols[0]['st_value'];failures.append(bad)
        bad=copy.deepcopy(elf);bad.symbols.pop();failures.append(bad)
        bad=copy.deepcopy(elf);bad.segments[1]['p_memsz']=1024*1024;failures.append(bad)
        for bad in failures:
            with patch.object(audit,'ELFFile',return_value=bad),patch.object(audit,'instruction_audit',return_value={'mock':'geometry_only'}),self.assertRaises(ValueError):audit.inspect(b'synthetic')

    def test_all_python_sources_and_cli_compile_without_simulator(self):
        for path in HERE.glob('*.py'):compile(path.read_text(encoding='utf-8'),str(path),'exec')
        for name in ('server.py','prepare.py','export.py','lv_audit.py','vm.py','summarize.py'):
            result=subprocess.run([sys.executable,'-B',str(HERE/name),'--help'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_synthetic_packet_export_roundtrip_and_corruption_rejection(self):
        import export as exporter
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'source';root.mkdir();job=Path(temporary)/'job';job.mkdir()
            files={n:(HERE/n).read_bytes() for n in ('linear_core.h','linear_bench.cc','lv_spec.py','lv_audit.py','lv_packet.py','lv_bench.py','optimized_core.h','vm_bench.py')}
            files.update({'rvv_int8_matmul.cc':b'synthetic official source placeholder; NOT linked firmware',
                'vme_tile.h':(HERE.parent/'google_person_vme/vme_tile.h').read_bytes(),
                'baseline_spec.py':spec.reference_path().read_bytes(),'BUILD':prepare.build_text().encode()})
            manifest=prepare.install(root,files)
            (root/'LICENSE').write_text('synthetic test fixture')
            (job/'source-manifest.json').write_text(json.dumps(manifest))
            (job/'probe_program.elf').write_bytes(b'synthetic ELF bytes: inspect mocked, NOT an RTL PASS')
            report=dict(elf_sha256=spec.sha(job/'probe_program.elf'),NPU_RTL='NOT_RUN')
            (job/'resources.json').write_text(json.dumps(report));(job/'host.log').write_text(host_text())
            (job/'build.log').write_text('synthetic export control-flow only')
            fields=dict(xlen='32',itcmSizeKBytes='256',dtcmSizeKBytes='512',axi2IdBits='6',rvvVlen='128',
                fetchDataBits='128',lsuDataBits='128',enableFetchL0='false',enableRvv='true',enableVme='true',
                enableFloat='true',enableZfbfmin='true',enableVectorBf16='true',enableAxiInstructionFetch='true',enableVerification='false')
            (job/'parameters.h').write_text(''.join('#define KP_'+k+' '+v+'\n' for k,v in fields.items()))
            (job/'rtl-identity.json').write_text(json.dumps(dict(rtl_sha256=spec.RTL_SHA,parameters=fields)))
            with patch.object(prepare,'prepare',return_value=manifest),patch.object(audit,'inspect',return_value=report),patch('sys.stdout',new=io.StringIO()):
                exporter.export(root,job)
                bundle=job/spec.PACKET_NAME;packet.load(bundle)
                self.assertEqual((bundle/'probe_program.elf').read_bytes(),(job/'probe_program.elf').read_bytes())
                self.assertFalse((bundle/'rtl').exists());self.assertTrue((job/(bundle.name+'.tar.gz')).is_file())
                (bundle/'source/linear_bench.cc').write_text('corrupted')
                with self.assertRaises(ValueError):packet.load(bundle)

    def test_child_cleans_waves_and_uses_owned_process_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);bundle=SimpleNamespace(root=root);rtl=SimpleNamespace(root=root/'old')
            base=SimpleNamespace(child_environment=lambda *args:dict(WAVES='0',GUI='0',COCOTB_ENABLE_PROFILING='1'),
                write_json=lambda path,v:path.write_text(json.dumps(v)))
            process=SimpleNamespace(wait=lambda **kwargs:0)
            with patch.object(subprocess,'Popen',return_value=process) as popen:
                server.execute(bundle,rtl,{},base,root,root/'model',0,100)
            child=popen.call_args.kwargs['env']
            for n in ('WAVES','GUI','COCOTB_ENABLE_PROFILING'):self.assertNotIn(n,child)
            self.assertEqual(child['LV_CASE'],'0');self.assertTrue(popen.call_args.kwargs['start_new_session'])

    def test_probe_is_distinct_strict_and_covers_new_and_fallback_paths(self):
        row=probe_observation();spec.accept(row,4)
        self.assertEqual(row['probe_cases'],9);self.assertEqual(row['probe_checked'],2716)
        self.assertEqual(row['probe_commands'],200)
        self.assertEqual((row['probe_fast_tiles'],row['probe_fallback_tiles']),(16,3))
        for name,value in dict(scope=spec.SCOPE,fault=True,probe_cases=8,probe_checked=0,probe_signature=0,
            probe_fast_tiles=0,probe_fallback_tiles=0,probe_fail_case=0,probe_mismatches=1,
            output_readback_equal=False,packed_readback_equal=False,requested_cycles=10000000,probe_current_case=0,
            probe_step=3,probe_first_element=0,probe_first_actual=1).items():
            bad=copy.deepcopy(row);bad[name]=value
            with self.subTest(name=name),self.assertRaises(ValueError):spec.accept(bad,4)

    def test_server_performance_requires_this_elf_probe_on_same_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);bundle=SimpleNamespace(root=root,report={'elf_sha256':'a'*64});build={'model':'same'}
            with self.assertRaises(ValueError):server.checked_opt_probe(None,bundle,build)
            (root/'producer-build-record.json').write_text(json.dumps(build))
            (root/'_test-status.json').write_text('{"exit_code":0,"timed_out":false}')
            (root/'results.xml').write_text('<testsuite><testcase name="llm_vme_opt_test"/></testsuite>')
            (root/'_test.log').write_text(spec.MARKER+json.dumps(probe_observation())+'\nTESTS=1 PASS=1 FAIL=0 SKIP=0')
            helper=SimpleNamespace(json_row=lambda text,marker:json.loads(next(line.split(marker,1)[1] for line in text.splitlines() if marker in line)))
            with patch.object(server,'helper',return_value=helper):
                proof=server.checked_opt_probe(root,bundle,build);self.assertEqual(proof['elf_sha256'],'a'*64)
                with self.assertRaises(ValueError):server.checked_opt_probe(root,bundle,{'model':'different'})
                (root/'_test.log').write_text(spec.MARKER+json.dumps(observation())+'\nTESTS=1 PASS=1 FAIL=0 SKIP=0')
                with self.assertRaises(ValueError):server.checked_opt_probe(root,bundle,build)

    def test_matrix_store_must_preserve_mtype_not_use_standard_vset(self):
        source=(HERE/'optimized_core.h').read_text()
        fast=source.split('void FastTileToRowMajor(',1)[1].split('\n#endif',1)[0]
        self.assertNotRegex(fast,r'"[^"\n]*vset(?:ivli|vli)')
        self.assertIn('.insn r 0x57,7,0x42,t0,%2,x0',fast)
        self.assertIn('.insn r 0x57,7,0x42,t0,%3,x0',fast)
        self.assertIn('vsse32.v',fast)
        # Verify the pin's real frontend contract, not generic RVV assumptions.
        repo=HERE.parent.parent
        frontend=subprocess.check_output(['git','--git-dir='+str(repo/'.upstream-git/coralnpu-google.git'),
            'show',spec.UPSTREAM+':hdl/verilog/rvv/design/RvvFrontEnd.sv'],text=True)
        self.assertIn("inst_config_state[i+1].mtwiden = 2'b00",frontend)
        self.assertIn('msettn rd, rs1',frontend)

    def test_vm_xml_log_status_and_elf_all_gate_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);bundle=SimpleNamespace(report={'elf_sha256':'a'*64})
            (root/'test-status.json').write_text('{"exit_code":0,"timed_out":false}')
            (root/'test.xml').write_text('<testsuite><testcase name="Bazel shell wrapper"/></testsuite>')
            text='running vm_bench.'+spec.testcase(4)+' (1/1)\n'+spec.MARKER+json.dumps(probe_observation())+'\nTESTS=1 PASS=1 FAIL=0 SKIP=0'
            (root/'test.log').write_text(text);vm.checked_results(root,bundle,4)
            for tag in ('failure','error','skipped'):
                (root/'test.xml').write_text('<testsuite><testcase name="wrapper"><'+tag+'/></testcase></testsuite>')
                with self.assertRaises(ValueError):vm.checked_results(root,bundle,4)
            (root/'test.xml').write_text('<testsuite><testcase name="wrapper"/></testsuite>')
            for bad in (text.replace('PASS=1','PASS=0'),text.replace(spec.testcase(4),spec.testcase(0)),text+'\n'+spec.MARKER+json.dumps(probe_observation())):
                (root/'test.log').write_text(bad)
                with self.assertRaises(ValueError):vm.checked_results(root,bundle,4)

    def test_preparation_is_build_only_and_simulation_requires_explicit_flag(self):
        script=(HERE/'prepare_tomorrow.sh').read_text()
        self.assertNotIn('run_vm.sh',script);self.assertNotIn('--allow-rtl-simulation',script)
        self.assertIn('vm.py" prepare',script)
        with tempfile.TemporaryDirectory() as temporary:
            result=subprocess.run([sys.executable,'-B',str(HERE/'vm.py'),'run','--prepared',temporary],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('Explicit --allow-rtl-simulation required',result.stderr)
            self.assertEqual(list(Path(temporary).iterdir()),[])
        tree=ast.parse((HERE/'vm.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prepare_vm')
        calls=[n for n in ast.walk(function) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='process']
        self.assertEqual(len(calls),1)
        self.assertIn("['build', *FLAGS, *targets]",ast.unparse(calls[0].args[0]))

    def test_vm_prepare_builds_configured_test_executables_without_running_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared,study,source,bundle,query,model,generated=fake_preparation(Path(temporary))
            with patch.object(vm.lv_packet,'load',return_value=bundle),patch.object(vm.source_prepare,'prepare'),\
                 patch.object(vm,'bazel',return_value=['fake-bazel']),patch.object(vm,'query',side_effect=query),\
                 patch.object(vm,'process',return_value={'exit_code':0,'timed_out':False}) as execute,patch('sys.stdout',new=io.StringIO()):
                vm.prepare_vm(study,source,prepared)
                argv=execute.call_args.args[0]
                self.assertEqual(argv[1],'build');self.assertNotIn('test',argv)
                for index in (4,0,1,2,3):self.assertIn(spec.target(index),argv)
                record,_,_,_=vm.checked_preparation(prepared)
                self.assertEqual(record['simulation'],'NOT_RUN');self.assertEqual(record['model_sha256'],spec.sha(model))
                old=model.read_bytes();model.write_bytes(b'changed model')
                with self.assertRaises(ValueError):vm.checked_preparation(prepared)
                model.write_bytes(old);generated.write_bytes(b'changed source')
                with self.assertRaises(ValueError):vm.checked_preparation(prepared)

    def test_vm_probe_then_case_evidence_and_tampering_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared,study,source,bundle,query,model,generated=fake_preparation(Path(temporary))
            with patch.object(vm.lv_packet,'load',return_value=bundle),patch.object(vm.source_prepare,'prepare'),\
                 patch.object(vm,'bazel',return_value=['fake-bazel']),patch.object(vm,'query',side_effect=query),\
                 patch.object(vm,'process',return_value={'exit_code':0,'timed_out':False}),patch('sys.stdout',new=io.StringIO()):vm.prepare_vm(study,source,prepared)
            def synthetic_test(argv,cwd,directory,label,timeout):
                index=next(i for i in range(5) if spec.target(i)==argv[-1])
                row=probe_observation() if index==4 else observation(index);row['elf_sha256']=bundle.report['elf_sha256']
                text='running vm_bench.'+spec.testcase(index)+' (1/1)\n'+spec.MARKER+json.dumps(row)+'\nTESTS=1 PASS=1 FAIL=0 SKIP=0'
                raw=source/'bazel-testlogs'/spec.PACKAGE/('opt_'+spec.testcase(index));raw.mkdir(parents=True,exist_ok=True)
                (raw/'test.log').write_text(text);(raw/'test.xml').write_text('<testsuite><testcase name="Bazel wrapper"/></testsuite>')
                status={'exit_code':0,'timed_out':False,'elapsed_seconds':0.0}
                (directory/'test-status.json').write_text(json.dumps(status));(directory/'test.log').write_text('synthetic console ONLY')
                return status
            with patch.object(vm.lv_packet,'load',return_value=bundle),patch.object(vm,'bazel',return_value=['fake-bazel']),patch.object(vm,'query',side_effect=query),\
                 patch.object(vm,'process',side_effect=synthetic_test) as execute,patch('sys.stdout',new=io.StringIO()):
                with self.assertRaisesRegex(ValueError,'probe missing'):vm.run_vm(prepared,1,100)
                self.assertFalse(execute.called)
                probe=vm.run_vm(prepared,4,100)
                self.assertTrue((probe/'bazel-console.log').is_file());self.assertTrue((prepared/'probe-proof.json').is_file())
                with self.assertRaisesRegex(ValueError,'already has a valid probe'):vm.run_vm(prepared,4,100)
                main=vm.run_vm(prepared,1,100)
                self.assertTrue((main/'candidate-probe-evidence.json').is_file());self.assertTrue((main/'result.json').is_file())
                self.assertTrue((prepared/'case1-proof.json').is_file())
                record,_,_,_=vm.checked_preparation(prepared);vm.checked_case(prepared,record,bundle,1)
                rows,_=summarize.collect_vm(prepared,partial=True)
                self.assertEqual([row['case_id'] for row in rows],[1])
                report=summarize.markdown(rows)
                self.assertIn('Validated 1/4',report);self.assertIn('NOT cold-start speedup',report)
                with self.assertRaises(ValueError):summarize.collect_vm(prepared,partial=False)
                with self.assertRaisesRegex(ValueError,'already has a valid probe/case'):vm.run_vm(prepared,1,100)
                (probe/'test.log').write_text((probe/'test.log').read_text()+'\nchanged evidence\n')
                with self.assertRaisesRegex(ValueError,'evidence changed'):vm.run_vm(prepared,2,100)

    def test_instruction_decoder_rejects_desynchronization_and_detects_vset(self):
        # RV32+C alignment walk, not an arbitrary 4-byte substring search.
        vset=0x0d207057;matrix=0xf28800f7
        data=b'\x01\x00'+vset.to_bytes(4,'little')+matrix.to_bytes(4,'little')
        decoded=audit.words(data);self.assertEqual(decoded,[vset,matrix])
        self.assertIn('ordinary_vset_clears_mtype',audit.operations(decoded))
        for bad in (b'\x03',b'\x03\x00',b'\x1f\x00\x00\x00'):
            with self.assertRaises(ValueError):audit.words(bad)

    def test_summary_table_preserves_raw_controls_and_prepack_scope(self):
        rows=[dict(case_id=i,observation=observation(i),comparison=spec.accept(observation(i),i)) for i in range(4)]
        text=summarize.markdown(rows)
        self.assertIn('Validated 4/4',text);self.assertIn('mean of three steady samples',text)
        self.assertIn('Full model: NOT RUN',text);self.assertIn('old v2 or profiling',text)
        for name,_,_,_ in spec.CASES:self.assertIn(name,text)

    def test_configuration_query_change_rejects_before_simulation(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared,study,source,bundle,query,model,generated=fake_preparation(Path(temporary))
            with patch.object(vm.lv_packet,'load',return_value=bundle),patch.object(vm.source_prepare,'prepare'),\
                 patch.object(vm,'bazel',return_value=['fake-bazel']),patch.object(vm,'query',side_effect=query),\
                 patch.object(vm,'process',return_value={'exit_code':0,'timed_out':False}),patch('sys.stdout',new=io.StringIO()):
                vm.prepare_vm(study,source,prepared)
                record,_,_,_=vm.checked_preparation(prepared)
                changed=model.parent/'different'/spec.TOP;changed.parent.mkdir();changed.write_bytes(model.read_bytes())
                execution=study/'execroot'
                def changed_query(prefix,cwd,args):
                    return str(execution) if args[:2]==['info','execution_root'] else changed.relative_to(execution).as_posix()
                with patch.object(vm,'query',side_effect=changed_query):
                    with self.assertRaisesRegex(ValueError,'configured test model changed'):
                        vm.checked_configured_model(study,source,record,4)

    def test_tomorrow_shell_default_prepare_and_failure_stop_with_stubbed_children(self):
        bash=os.environ.get('LLM_TEST_BASH')
        if not bash:self.skipTest('Set LLM_TEST_BASH')
        # Intercept EVERY child bash/python call. No Bazel, compiler, RISC-V
        # process or RTL executable is launched by this orchestration test.
        program=r'''
bash() { printf 'MOCK_BASH:%s\n' "$1"; if [[ "${MOCK_FAIL:-}" == prepare && "$1" == */prepare_tomorrow.sh ]]; then return 7; fi; return 0; }
python3() { printf 'MOCK_PYTHON:%s\n' "$*"; }
uname() { printf 'Linux\n'; }
unit_script=$1
shift
source "$unit_script" "$@"
'''
        with tempfile.TemporaryDirectory() as temporary:
            study=Path(temporary).as_posix();script=(HERE/'tomorrow.sh').as_posix()
            default=subprocess.run([bash,'-c',program,'unit-test',script],capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(default.returncode,0,default.stderr)
            self.assertIn('prepare_tomorrow.sh',default.stdout);self.assertNotIn('run_vm.sh',default.stdout)
            run=subprocess.run([bash,'-c',program,'unit-test',script,'quick',study],capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(run.stdout.count('MOCK_BASH:'),2)
            self.assertIn('run_vm.sh',run.stdout);self.assertIn('summarize.py',run.stdout)
            env=os.environ.copy();env['MOCK_FAIL']='prepare'
            failure=subprocess.run([bash,'-c',program,'unit-test',script,'quick',study],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertNotEqual(failure.returncode,0);self.assertNotIn('run_vm.sh',failure.stdout)
            self.assertNotIn('MOCK_PYTHON:',failure.stdout)

    def test_failed_vm_attempt_keeps_logs_and_never_registers_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared,study,source,bundle,query,model,generated=fake_preparation(Path(temporary))
            with patch.object(vm.lv_packet,'load',return_value=bundle),patch.object(vm.source_prepare,'prepare'),\
                 patch.object(vm,'bazel',return_value=['fake-bazel']),patch.object(vm,'query',side_effect=query),\
                 patch.object(vm,'process',return_value={'exit_code':0,'timed_out':False}),patch('sys.stdout',new=io.StringIO()):
                vm.prepare_vm(study,source,prepared)
            def failure(argv,cwd,directory,label,timeout):
                status={'exit_code':1,'timed_out':False};(directory/'test.log').write_text('synthetic build/test failure')
                (directory/'test-status.json').write_text(json.dumps(status));return status
            with patch.object(vm.lv_packet,'load',return_value=bundle),patch.object(vm,'bazel',return_value=['fake-bazel']),\
                 patch.object(vm,'query',side_effect=query),patch.object(vm,'process',side_effect=failure),patch('sys.stdout',new=io.StringIO()):
                with self.assertRaisesRegex(ValueError,'failed/incomplete'):vm.run_vm(prepared,4,100)
            self.assertFalse((prepared/'probe-proof.json').exists())
            attempts=list((prepared/'runs').iterdir());self.assertEqual(len(attempts),1)
            self.assertTrue((attempts[0]/'test.log').is_file());self.assertFalse((attempts[0]/'result.json').exists())


if __name__=='__main__':unittest.main()
