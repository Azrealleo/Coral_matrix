"""Static/native tests, never claim RVV execution from a host mirror."""
import ast
import copy
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import materialize as gen


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=os.environ.get('GELU_TEST_TEMP_ROOT'))
        cls.root = Path(cls.temp.name)
        cls.tools = gen.materialize(cls.root/'tools')
        sys.path.insert(0, str(cls.tools))
        import lv_spec, lv_audit, prepare
        cls.spec, cls.audit, cls.prepare = lv_spec, lv_audit, prepare
        cls.files = prepare.expected(gen.REPO/'.upstream-git/coralnpu-google.git')
        cls.native = cls.root/'native'; cls.native.mkdir()
        for name, data in cls.files.items(): (cls.native/name).write_bytes(data)
        if os.environ.get('LLM_TEST_CXX'):
            os.environ['PATH'] = str(Path(os.environ['LLM_TEST_CXX']).parent)+os.pathsep+os.environ['PATH']

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_fixture_seed_and_original_sources_preserved(self):
        path = self.tools/'tx_reference.py'
        m = importlib.util.module_from_spec(importlib.util.spec_from_file_location('old', path))
        m.__spec__.loader.exec_module(m)
        m.CASES = (('residual256','RESIDUAL',(256,0,0,0,0)),('rms64','RMS',(1,64,0,0,0)),
                   ('rms_tail37','RMS',(3,37,0,0,0)),*self.spec.CASES)
        for i in range(3):
            new = self.spec.fixture(i); old = m.fixture(i+3)
            for field in ('x','w','y','vector_sha256'): self.assertEqual(new[field], old[field])
            self.assertEqual(new['algorithm'], new['y'])
        probe = self.spec.fixture(self.spec.PROBE_INDEX)
        self.assertEqual((probe['kind'],probe['x'],probe['y']), ('GEGLU',[0.],[0.]))
        for name in self.prepare.OFFICIAL:
            raw = subprocess.check_output(['git','--git-dir='+str(gen.REPO/'.upstream-git/coralnpu-google.git'),
                'show',self.spec.UPSTREAM+':'+self.prepare.ROOT+name])
            self.assertEqual(self.files[name], raw)

    def test_generator_syntax_and_index_range(self):
        self.assertEqual(gen.verify(self.root/'tools'), self.tools)
        for path in self.tools.glob('*.py'): ast.parse(path.read_text(encoding='utf-8'))
        vm = (self.tools/'vm.py').read_text(encoding='utf-8')
        shell = (self.tools/'run_vm.sh').read_text(encoding='utf-8')
        self.assertIn('choices=range(4),default=spec.PROBE_INDEX', vm)
        self.assertIn('--case 3', shell); self.assertNotIn('--case 6', shell)
        self.assertNotIn('0|1|2|3|4|5)', shell)
        self.assertIn('candidate.cc', self.files['BUILD'].decode())
        self.assertIn('host_accuracy_test', self.files['BUILD'].decode())
        self.assertIn('Copyright (c) Microsoft', self.files['LICENSE-MLAS.txt'].decode())

    def test_host_reference_and_bounded_accuracy(self):
        compiler = os.environ.get('LLM_TEST_CXX')
        if not compiler: self.skipTest('Set LLM_TEST_CXX')
        flags = ['-std=c++17','-O2','-ffp-contract=off','-fno-tree-vectorize',
                 '-DTX_HOST','-Wall','-Wextra','-Werror']
        logs = ''
        for label, names in (('fixture',('candidate.cc','linear_bench.cc','kernels.cc','fixtures.cc','host_mirrors.cc')),
                             ('dense',('candidate.cc','host_accuracy.cc'))):
            exe = self.root/(label+'.exe')
            r = subprocess.run([compiler,*flags,*[str(self.native/n) for n in names],'-o',str(exe)],capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
            r = subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr); logs += r.stdout
        self.spec.checked_host(logs)
        with self.assertRaises(ValueError): self.spec.checked_host(logs.split('[GELU_MLAS_HOST_NUMERICS_PASS]')[0])
        with self.assertRaises(ValueError): self.spec.checked_host(logs+'\nFAIL\n')

    def test_strict_failure_cannot_be_accepted_as_diagnostic(self):
        s = self.spec; d = s.fixture(0)
        row = dict(schema=1,scope=s.SCOPE,case_id=0,case=d['name'],kind=d['kind'],shape=d['shape'],
            itcm_kib=256,dtcm_kib=512,rtl_sha256=s.RTL_SHA,elf_sha256='a'*64,
            vector_sha256=d['vector_sha256'],algorithm_sha256=d['algorithm_sha256'],atol=s.ATOL,rtol=s.RTOL,
            fault=False,natural_halt=True,firmware_status=3,checked_elements=12*len(d['y']),algorithm_mismatches=0,
            guard_ok=True,scalar_calls=4,project_calls=4,official_calls=4,input_readback_equal=True,
            mathematical_baselines_check=True,official_algorithm_output_check=True,stack_low_canary_intact=True,
            requested_cycles=10000000,empty_boundary_cycles=3,observation_elapsed_cycles=100000,
            scalar_cycles=[1000]*4,project_cycles=[500]*4,official_cycles=[250]*4,
            strict_math_quality_pass=True,strict_math_quality_mismatches=0,
            official_max_math_abs_error=0.,official_max_algorithm_abs_error=0.)
        accepted = s.accept(row,0)
        self.assertEqual(accepted['candidate_cycles'],[250]*4)
        self.assertNotIn('official_cycles',accepted)
        bad = copy.deepcopy(row);bad.update(strict_math_quality_pass=False,
            strict_math_quality_mismatches=4,official_max_math_abs_error=0.04)
        with self.assertRaises(ValueError): s.accept(bad,0)
        for key,value in (('fault',True),('official_calls',0),('guard_ok',False),('natural_halt',False)):
            bad = dict(row);bad[key]=value
            with self.assertRaises(ValueError): s.accept(bad,0)

    def test_actual_candidate_rv32_object_not_execution(self):
        compiler = os.environ.get('LLM_TEST_CROSS')
        if not compiler: self.skipTest('Set LLM_TEST_CROSS')
        obj = self.root/'candidate.o'
        r = subprocess.run([compiler,'-std=c++17','-O2','-ffp-contract=off',
            '-fno-tree-vectorize','-fno-tree-slp-vectorize','-Wall','-Wextra','-Werror',
            '-march=rv32imf_zve32f_zicsr','-mabi=ilp32','-c',str(self.native/'candidate.cc'),'-o',str(obj)],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        from elftools.elf.elffile import ELFFile
        with obj.open('rb') as stream:
            elf = ELFFile(stream)
            symbol = elf.get_section_by_name('.symtab').get_symbol_by_name('candidate_gelu_f32')[0]
            section = elf.get_section(symbol['st_shndx'])
            instructions = self.audit.words(section.data()[symbol['st_value']:symbol['st_value']+symbol['st_size']])
            self.assertTrue(any(w&127==0x57 and (w>>26)&63==32 and (w>>12)&7==1 for w in instructions))
        objdump = str(Path(compiler).with_name('riscv64-unknown-elf-objdump.exe' if os.name=='nt' else 'riscv64-unknown-elf-objdump'))
        dis = subprocess.check_output([objdump,'-dr',str(obj)],text=True)
        self.assertNotIn('R_RISCV_CALL',dis)
        self.assertIn('vfmacc',dis); self.assertIn('vfdiv',dis)

    def test_gc_link_audits_live_candidate_and_rejects_missing_division(self):
        compiler=os.environ.get('LLM_TEST_CROSS')
        if not compiler:self.skipTest('Set LLM_TEST_CROSS')
        flags=['-std=c++17','-O2','-ffp-contract=off','-fno-tree-vectorize','-fno-tree-slp-vectorize',
            '-ffunction-sections','-fdata-sections','-fno-exceptions','-fno-rtti','-fno-lto',
            '-march=rv32imf_zve32f_zicsr_zfbfmin_zvfbfmin_zvfbfwma','-mabi=ilp32','-I'+str(self.native)]
        objects=[]
        for name in ('candidate.cc','linear_bench.cc','kernels.cc','fixtures.cc',
                     *[n for n in self.prepare.OFFICIAL if n.endswith('.cc')]):
            obj=self.root/('gc_'+name+'.o');objects.append(obj)
            r=subprocess.run([compiler,*flags,'-c',str(self.native/name),'-o',str(obj)],capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        # Link/resource fixture ONLY; math stubs are never executed.
        stubs=self.root/'gc_stubs.cc'
        stubs.write_text('''extern "C" float sqrtf(float x){return x;}
extern "C" float expf(float x){return x;}
extern "C" float tanhf(float x){return x;}
extern "C" void* memset(void* p,int v,unsigned n){volatile unsigned char* q=(volatile unsigned char*)p;for(unsigned i=0;i<n;++i)q[i]=v;return p;}
extern "C" void* memcpy(void* p,const void* s,unsigned n){volatile unsigned char* q=(volatile unsigned char*)p;const unsigned char* r=(const unsigned char*)s;for(unsigned i=0;i<n;++i)q[i]=r[i];return p;}
''')
        linker=self.root/'gc_link.ld'
        linker.write_text('''MEMORY {
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
        output=self.root/'gc_link.elf'
        r=subprocess.run([compiler,*flags,'-nostdlib',*[str(p) for p in objects],str(stubs),
            '-Wl,--gc-sections','-Wl,-e,main','-Wl,-T,'+str(linker),'-o',str(output)],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        data=output.read_bytes();report=self.audit.inspect(data)
        self.assertEqual(set(report['instruction_audit']),{'candidate_gelu_f32'})
        from elftools.elf.elffile import ELFFile
        elf=ELFFile(io.BytesIO(data));table=elf.get_section_by_name('.symtab')
        self.assertFalse(table.get_symbol_by_name('rvv_tanh_gelu_mul_f32'))
        symbol=table.get_symbol_by_name('candidate_gelu_f32')[0]
        section=elf.get_section(symbol['st_shndx']);offset=section['sh_offset']+symbol['st_value']-section['sh_addr']
        bad=bytearray(data);patched=0
        for at in range(offset,offset+symbol['st_size']-3,2):
            w=int.from_bytes(data[at:at+4],'little')
            if w&127==0x57 and (w>>26)&63==32 and (w>>12)&7==1:
                bad[at:at+4]=b'\x13\x00\x00\x00';patched+=1
        self.assertGreater(patched,0)
        with self.assertRaisesRegex(ValueError,'Missing actual candidate vector FP32 division'):
            self.audit.inspect(bytes(bad))


if __name__ == '__main__': unittest.main()
