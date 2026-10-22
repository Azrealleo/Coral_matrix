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

HERE=Path(__file__).resolve().parent


def observation(index=0):
    name,m,k,n=spec.CASES[index]
    return dict(schema=1,scope=spec.SCOPE,case_id=index,case=name,M=m,K=k,N=n,itcm_kib=256,dtcm_kib=512,
        fault=False,natural_halt=True,firmware_status=3,mismatches=0,guard_ok=True,stack_low_canary_intact=True,
        input_readback_equal=True,output_readback_equal=True,packed_readback_equal=True,workspace_readback_equal=True,
        checked_elements=16*m*n,signature=spec.expected_signature(index),rvv_calls=4,complete_calls=4,reuse_calls=4,
        profile_calls=4,profile_commands=4*spec.commands(index),profile_cycles=[4000]*4,
        profile_segment_cycles=[100]*20,profile_segment_counts=([1]+[(n+15)//16]*4)*4,
        prepack_calls=1,complete_commands=4*spec.commands(index),reuse_commands=4*spec.commands(index),
        vector_sha256=spec.vectors(index)['vector_sha256'],elf_sha256='a'*64,rtl_sha256=spec.RTL_SHA,
        requested_cycles=10000000,observation_elapsed_cycles=100000,empty_boundary_cycles=3,prepack_once_cycles=1000,
        rvv_cycles=[2000]*4,complete_cycles=[1000]*4,reuse_cycles=[500]*4)


def host_text():
    return ''.join(f'[LV_HOST_REFERENCE] id={i} checked={16*c[1]*c[3]} signature={spec.expected_signature(i)} commands_each={4*spec.commands(i)} VME_RVV=NOT_RUN\n'
        for i,c in enumerate(spec.CASES))+'[LV_PACK_HOST_PASS] cases=735 hardware=NOT_RUN\n'


class Checks(unittest.TestCase):
    def test_original_reference_and_qualified_tile_are_byte_identical(self):
        self.assertEqual(spec.sha(spec.reference_path()),spec.REFERENCE_SHA)
        self.assertEqual(spec.sha(HERE.parent/'google_person_vme/vme_tile.h'),spec.TILE_SHA)
        for i,c in enumerate(spec.CASES):
            gold=spec.vectors(i);self.assertEqual(len(gold['y']),c[1]*c[3])
            self.assertEqual(len(spec.packed_weights(i)),4384);self.assertEqual(len(spec.workspace(i)),2080)

    def test_unsigned_bias_transform_matches_signed_dot_all_four(self):
        import struct
        for i,(_,m,k,n) in enumerate(spec.CASES):
            v=spec.vectors(i);x=list(struct.unpack('<'+'b'*len(v['x']),v['x']))
            packed=spec.packed_weights(i);w=list(struct.unpack('<4096b',packed[16:4112]));bias=struct.unpack('<64i',packed[4112:-16])
            for r in range(m):
                for c in range(n):
                    first=c//16*16;value=bias[c]+sum(w[first*k+d*16+c%16]*(x[r*k+d]+128) for d in range(k))
                    self.assertEqual(value,v['y'][r*n+c])

    def test_actual_native_main_and_735_boundary_arithmetic_cases(self):
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
                built=subprocess.run([compiler,'-std=c++17','-march=rv32imafcv_zicsr','-mabi=ilp32f','-O2',
                    '-fno-tree-vectorize','-fno-tree-slp-vectorize','-fno-lto','-I'+str(HERE),
                    '-I'+str(HERE.parent/'google_person_vme'),'-c',str(source),'-o',str(source.with_suffix('.o'))],capture_output=True,text=True,encoding='utf-8',errors='replace')
                self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            output=subprocess.check_output([objdump,'-d','-C',str(root/'linear_bench.o')],text=True)
            self.assertIn('f28800f7',output);self.assertIn('vle8.v',output);self.assertIn('vse32.v',output)
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

    def test_amortized_prepack_is_charged_and_slow_vme_is_valid(self):
        row=observation();result=spec.accept(row,0)
        self.assertEqual(result['reuse_first_including_prepack_cycles'],1500)
        self.assertEqual(result['reuse_four_calls_including_prepack_cycles'],3000)
        self.assertEqual(result['rvv_over_vme_reuse_four_calls_including_prepack'],8000/3000)
        row['complete_cycles']=[4000]*4;row['reuse_cycles']=[3000]*4
        self.assertLess(spec.accept(row,0)['steady_rvv_over_vme_complete'],1)
        self.assertLess(spec.accept(row,0)['steady_rvv_over_vme_reuse_excluding_prepack'],1)

    def test_no_false_pass_missing_paths_corrupt_data_or_cycle_windows(self):
        row=observation()
        for name,value in dict(fault=True,natural_halt=False,firmware_status=2,mismatches=1,signature=0,
            guard_ok=False,packed_readback_equal=False,workspace_readback_equal=False,output_readback_equal=False,
            rvv_calls=0,reuse_calls=0,prepack_calls=0,complete_calls=0,complete_commands=0,reuse_commands=0,
            prepack_once_cycles=0,rvv_cycles=[2000]*3,complete_cycles=[0]*4,observation_elapsed_cycles=100,
            requested_cycles=2000000,rtl_sha256='b'*64,vector_sha256='c'*64).items():
            bad=copy.deepcopy(row);bad[name]=value
            with self.subTest(name=name),self.assertRaises(ValueError):spec.accept(bad,0)

    def test_native_log_requires_both_tests_and_all_signatures(self):
        text=host_text();spec.checked_host(text)
        for bad in (text*2,text.replace('cases=735','cases=734'),text.replace('id=0','id=1'),text+'FAILED\n',text.splitlines()[0]):
            with self.assertRaises(ValueError):spec.checked_host(bad)

    def test_build_rules_do_not_repeat_cc_test_hdrs_mistake(self):
        tree=ast.parse(prepare.build_text());tests=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='cc_test']
        self.assertEqual(len(tests),2)
        for node in tests:
            attrs={kw.arg:ast.literal_eval(kw.value) for kw in node.keywords}
            self.assertNotIn('hdrs',attrs);self.assertIn('linear_core.h',attrs['srcs'])
        shell=(HERE/'build_export.sh').read_text();self.assertNotIn(':model',shell);self.assertNotIn('--test_timeout',shell)
        self.assertIn('host_packing_test',shell)
        self.assertIn('llm_vme_profile_v1',shell)
        self.assertIn("choices=range(4),default=3",(HERE/'server.py').read_text())
        binary=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='coralnpu_v2_binary')
        headers=next(ast.literal_eval(kw.value) for kw in binary.keywords if kw.arg=='hdrs')
        for name in ('profile_core.h','profile_timing.h','profile_tile.h'):self.assertIn(name,headers)

    def test_install_is_idempotent_and_refuses_overwrite(self):
        files={'rvv_int8_matmul.cc':b'official','linear_bench.cc':b'bench'}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);a=prepare.install(root,files);self.assertEqual(a,prepare.install(root,files))
            path=root/spec.PACKAGE/'linear_bench.cc';path.write_bytes(b'user edit')
            with self.assertRaises(ValueError):prepare.install(root,files)
            self.assertEqual(path.read_bytes(),b'user edit')

    def test_profile_uses_crt_exit_and_preserves_measured_v2_artifacts(self):
        source=(HERE/'linear_bench.cc').read_text().split('#else\n  const unsigned selected=lv_case;',1)[1]
        self.assertIn('if(selected>=4){lv_status=99;return 1;}',source)
        self.assertIn('return Run(selected);',source)
        self.assertNotIn('asm volatile(',source)
        self.assertEqual(spec.PACKAGE,'tests/cocotb/llm_vme_profile_v1')
        self.assertEqual(prepare.MANIFEST,'llm_vme_profile_v1_manifest.json')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);old=root/'tests/cocotb/llm_vme_linear_v2';old.mkdir(parents=True)
            (old/'linear_bench.cc').write_bytes(b'v2 measured source must stay')
            marker=root/'llm_vme_linear_v2_manifest.json';marker.write_bytes(b'original sealed v2 manifest')
            prepare.install(root,{'rvv_int8_matmul.cc':b'official','linear_bench.cc':b'new profile source'})
            self.assertEqual((old/'linear_bench.cc').read_bytes(),b'v2 measured source must stay')
            self.assertEqual(marker.read_bytes(),b'original sealed v2 manifest')
            self.assertEqual((root/spec.PACKAGE/'linear_bench.cc').read_bytes(),b'new profile source')
        bad=observation();bad['fault']=True
        with self.assertRaisesRegex(ValueError,r': fault$'):spec.accept(bad,0)

    def test_profile_coverage_boundaries_and_scheduling_perturbation(self):
        row=observation();result=spec.accept(row,0)
        self.assertEqual(result['profile_unassigned_cycles'],[3500]*4)
        self.assertEqual(result['profile_minus_uninstrumented_reuse_cycles'],[3500]*4)
        self.assertAlmostEqual(sum(result['profile_stage_fraction_of_instrumented_call'].values()),0.125)
        for field,value in dict(profile_calls=0,profile_commands=0,profile_cycles=[100]*4,
            profile_segment_cycles=[10000]*20,profile_segment_counts=[1]*20).items():
            bad=copy.deepcopy(row);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):spec.accept(bad,0)
        # Negative paired difference may be a compiler/layout effect: report it,
        # never clamp to zero or deduct it to fabricate an uninstrumented time.
        row['profile_cycles']=[600]*4
        self.assertEqual(spec.accept(row,0)['profile_minus_uninstrumented_reuse_cycles'],[100]*4)
        row['reuse_cycles']=[800]*4
        self.assertEqual(spec.accept(row,0)['profile_minus_uninstrumented_reuse_cycles'],[-200]*4)

    def test_instrumented_tile_keeps_original_instruction_schedule(self):
        raw=(HERE/'profile_tile.h').read_text()
        raw=raw.replace('#include "profile_timing.h"\n','').replace('namespace llm_vme {','namespace person_vme {')
        raw=raw.replace('struct ProfileTile {\n  ProfileStats& stats;','struct HardwareTile {')
        raw=raw.replace('ProfileTile(uint32_t* count, ProfileStats& measured) : stats(measured), commands(count) {}',
            'explicit HardwareTile(uint32_t* count) : commands(count) {}')
        raw=raw.replace('    uint32_t begin=ProfileCycle();\n','')
        for phase in ('kAccumulatorInit','kLoadIssue'):
            raw=raw.replace('    stats.Add('+phase+',ProfileCycle()-begin);\n    begin=ProfileCycle();\n','')
        raw=raw.replace('    stats.Add(kReadback,ProfileCycle()-begin);\n','')
        raw=raw.replace('}  // namespace llm_vme','}  // namespace person_vme')
        original=(HERE.parent/'google_person_vme/vme_tile.h').read_text()
        self.assertEqual(raw.strip(),original.strip())

    def test_raw_xml_and_exit_state_gate(self):
        helper=SimpleNamespace(json_row=lambda text,marker:json.loads(next(s.split(marker,1)[1] for s in text.splitlines() if marker in s)))
        with tempfile.TemporaryDirectory() as temporary,patch.object(server,'helper',return_value=helper):
            root=Path(temporary);bundle=SimpleNamespace(root=root,report={'elf_sha256':'a'*64})
            (root/'_test-status.json').write_text('{"exit_code":0,"timed_out":false}')
            (root/'results.xml').write_text('<testsuite><testcase name="llm_vme_profile_test"/></testsuite>')
            (root/'_test.log').write_text(spec.MARKER+json.dumps(observation())+'\x1b[39m\nTESTS=1 PASS=1 FAIL=0 SKIP=0')
            server.checked_results(root,bundle,0)
            for tag in ('failure','error','skipped'):
                (root/'results.xml').write_text('<testsuite><testcase name="llm_vme_profile_test"><'+tag+'/></testcase></testsuite>')
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
        with patch.object(audit,'ELFFile',return_value=elf):audit.inspect(b'synthetic')
        failures=[]
        bad=copy.deepcopy(elf);bad.elfclass=64;failures.append(bad)
        bad=copy.deepcopy(elf);bad.segments[1]['p_filesz']=0;failures.append(bad)
        bad=copy.deepcopy(elf);bad.symbols[1]['st_value']=bad.symbols[0]['st_value'];failures.append(bad)
        bad=copy.deepcopy(elf);bad.symbols.pop();failures.append(bad)
        bad=copy.deepcopy(elf);bad.segments[1]['p_memsz']=1024*1024;failures.append(bad)
        for bad in failures:
            with patch.object(audit,'ELFFile',return_value=bad),self.assertRaises(ValueError):audit.inspect(b'synthetic')

    def test_all_python_sources_and_cli_compile_without_simulator(self):
        for path in HERE.glob('*.py'):compile(path.read_text(encoding='utf-8'),str(path),'exec')
        for name in ('server.py','prepare.py','export.py','lv_audit.py'):
            result=subprocess.run([sys.executable,'-B',str(HERE/name),'--help'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_synthetic_packet_export_roundtrip_and_corruption_rejection(self):
        import export as exporter
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'source';root.mkdir();job=Path(temporary)/'job';job.mkdir()
            files={n:(HERE/n).read_bytes() for n in ('linear_core.h','linear_bench.cc','lv_spec.py','lv_audit.py')}
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
            with patch.object(prepare,'prepare',return_value=manifest),patch.object(audit,'inspect',return_value=report):
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


if __name__=='__main__':unittest.main()
