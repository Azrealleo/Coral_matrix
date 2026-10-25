"""Native and RV32 static checks. Neither claims RTL execution."""
import ast
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import materialize as gen
import fixture

class ChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=os.environ.get('GELU_TEST_TEMP_ROOT'))
        cls.root=Path(cls.temp.name);cls.tools=gen.materialize(cls.root/'tools')
        sys.path.insert(0,str(cls.tools))
        import lv_spec,prepare,lv_audit
        cls.spec,cls.prepare,cls.audit=lv_spec,prepare,lv_audit
        cls.files=prepare.expected(gen.REPO/'.upstream-git/coralnpu-google.git')
        cls.native=cls.root/'native';cls.native.mkdir()
        for name,data in cls.files.items():(cls.native/name).write_bytes(data)
        if os.environ.get('LLM_TEST_CXX'):
            os.environ['PATH']=str(Path(os.environ['LLM_TEST_CXX']).parent)+os.pathsep+os.environ['PATH']

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_independent_stages_and_row_broadcast(self):
        import math
        x=[3.,4.,0.,0.];w=[0.,1.]+[0.]*4+[1.,-1.,2.,-2.]
        y=fixture.golden(2,2,x,w)
        self.assertEqual(y[:4],[fixture.f32(3/math.sqrt(12.5+1e-5)),
                               fixture.f32(8/math.sqrt(12.5+1e-5)),0.,0.])
        self.assertEqual(y[8:12],[0.]*4);self.assertEqual(y[16:],[1.,-1.,2.,-2.])
        self.assertEqual(y[4:8]+y[12:16],[fixture.GUARD]*8)
        for i in range(4):
            d=fixture.fixture(i);self.assertEqual(d,self.spec.fixture(i))
            n=d['shape'][0]*d['shape'][1]
            self.assertEqual(len(d['y']),3*n+8)
            self.assertEqual(d['y'],d['algorithm']);self.assertLessEqual(len(d['y']),1024)
        with self.assertRaises(ValueError):fixture.golden(1,2,[0.],[0.])
        for i in (-1,4,True):
            with self.assertRaises(ValueError):fixture.fixture(i)

    def test_frozen_sources_and_runtime_dependencies(self):
        self.assertEqual(gen.verify(self.root/'tools'),self.tools)
        for path in self.tools.glob('*.py'):ast.parse(path.read_text(encoding='utf-8'))
        self.assertEqual(self.files['candidate.cc'],gen.read('verification/google_gelu_rvv_mlas/candidate.cc'))
        for name in self.prepare.OFFICIAL:
            raw=subprocess.check_output(['git','--git-dir='+str(gen.REPO/'.upstream-git/coralnpu-google.git'),
                                         'show',self.spec.UPSTREAM+':'+self.prepare.ROOT+name])
            self.assertEqual(self.files[name],raw)
        build=self.files['BUILD'].decode()
        self.assertIn('"chain_fixture.py"',build);self.assertIn("'chain.cc'",build)
        vm=(self.tools/'vm_bench.py').read_text()
        for name,_,_ in fixture.CASES:self.assertIn('candidate_'+name+'_test',vm)
        for name in ('lv_packet.py','export.py'):
            self.assertIn("'chain_fixture.py'",(self.tools/name).read_text())

    def run_native(self,chain=None):
        compiler=os.environ.get('LLM_TEST_CXX')
        if not compiler:self.skipTest('Set LLM_TEST_CXX')
        names=['chain.cc','candidate.cc','linear_bench.cc','kernels.cc','fixtures.cc','host_mirrors.cc']
        sources=[str(self.native/n) for n in names]
        if chain is not None:
            path=self.root/'bad_chain.cc';path.write_text(chain);sources[0]=str(path)
        exe=self.root/('bad.exe' if chain else 'native.exe')
        r=subprocess.run([compiler,'-std=c++17','-O2','-ffp-contract=off','-fno-tree-vectorize',
                          '-DTX_HOST','-Wall','-Wextra','-Werror','-I'+str(self.native),*sources,'-o',str(exe)],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        return subprocess.run([str(exe)],capture_output=True,text=True)

    def test_native_chain_and_guard_rejection(self):
        run=self.run_native();self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        for i in range(4):self.assertIn('id='+str(i)+' checked='+str(12*len(fixture.fixture(i)['y'])),run.stdout)
        compiler=os.environ['LLM_TEST_CXX'];exe=self.root/'accuracy.exe'
        r=subprocess.run([compiler,'-std=c++17','-O2','-ffp-contract=off','-fno-tree-vectorize','-DTX_HOST',
                          str(self.native/'candidate.cc'),str(self.native/'host_accuracy.cc'),'-o',str(exe)],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        dense=subprocess.run([str(exe)],capture_output=True,text=True)
        self.assertEqual(dense.returncode,0,dense.stdout+dense.stderr)
        self.spec.checked_host(run.stdout+dense.stdout)
        with self.assertRaises(ValueError):self.spec.checked_host(run.stdout)
        # Native execution of an injected boundary write must fail, even though
        # the float guard is large and a relative-tolerance comparison could hide it.
        text='#include <cstring>\n'+self.files['chain.cc'].decode().replace('RmsNormF(rows,cols,1e-5f,x,w,y);',
            'RmsNormF(rows,cols,1e-5f,x,w,y);unsigned broken=0x55aa7710;std::memcpy(y+n,&broken,4);')
        self.assertNotEqual(self.run_native(text).returncode,0)

    def test_accept_requires_each_stage_and_exact_guards(self):
        s=self.spec;d=s.fixture(0)
        row=dict(schema=1,scope=s.SCOPE,case_id=0,case=d['name'],kind=d['kind'],shape=list(d['shape']),
                 itcm_kib=256,dtcm_kib=512,rtl_sha256=s.RTL_SHA,vector_sha256=d['vector_sha256'],
                 algorithm_sha256=d['algorithm_sha256'],atol=s.ATOL,rtol=s.RTOL,
                 fault=False,natural_halt=True,firmware_status=3,checked_elements=12*len(d['y']),
                 algorithm_mismatches=0,guard_ok=True,scalar_calls=4,project_calls=4,official_calls=4,
                 input_readback_equal=True,mathematical_baselines_check=True,official_algorithm_output_check=True,
                 stack_low_canary_intact=True,requested_cycles=10000000,elf_sha256='0'*64,
                 empty_boundary_cycles=3,observation_elapsed_cycles=100000,
                 scalar_cycles=[100]*4,project_cycles=[100]*4,official_cycles=[100]*4,
                 strict_math_quality_pass=True,strict_math_quality_mismatches=0,
                 official_max_math_abs_error=0.,official_max_algorithm_abs_error=0.,
                 chain_stage_math_pass=dict(norm=True,activation=True,output=True),
                 chain_stage_max_abs_error=dict(norm=0.,activation=0.,output=0.),chain_stage_guards_exact=True)
        self.assertEqual(s.accept(row,0)['qualification'],'STRICT_MATH_PASS')
        for key,value in (('chain_stage_math_pass',dict(norm=False,activation=True,output=True)),
                          ('chain_stage_guards_exact',False),('chain_stage_max_abs_error',{}),
                          ('fault',True),('natural_halt',False),('strict_math_quality_pass',False)):
            bad=dict(row);bad[key]=value
            with self.assertRaises(ValueError):s.accept(bad,0)

    def test_actual_rv32_gc_link_and_live_entries(self):
        compiler=os.environ.get('LLM_TEST_CROSS')
        if not compiler:self.skipTest('Set LLM_TEST_CROSS')
        flags=['-std=c++17','-O2','-ffp-contract=off','-fno-tree-vectorize','-fno-tree-slp-vectorize',
               '-ffunction-sections','-fdata-sections','-fno-exceptions','-fno-rtti','-fno-lto',
               '-march=rv32imf_zve32f_zicsr_zfbfmin_zvfbfmin_zvfbfwma','-mabi=ilp32','-I'+str(self.native)]
        objects=[]
        for name in ('chain.cc','candidate.cc','linear_bench.cc','kernels.cc','fixtures.cc',
                     *[n for n in self.prepare.OFFICIAL if n.endswith('.cc')]):
            obj=self.root/(name+'.o');objects.append(str(obj))
            r=subprocess.run([compiler,*flags,'-c',str(self.native/name),'-o',str(obj)],capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        # Static link fixture only. These math stubs are NEVER executed.
        stubs=self.root/'stubs.cc';stubs.write_text('''extern "C" float sqrtf(float x){return x;}
extern "C" float expf(float x){return x;}
extern "C" float tanhf(float x){return x;}
extern "C" void* memset(void* p,int v,unsigned n){volatile unsigned char* q=(volatile unsigned char*)p;for(unsigned i=0;i<n;++i)q[i]=v;return p;}
extern "C" void* memcpy(void* p,const void* s,unsigned n){volatile unsigned char* q=(volatile unsigned char*)p;const unsigned char* r=(const unsigned char*)s;for(unsigned i=0;i<n;++i)q[i]=r[i];return p;}
''')
        linker=self.root/'link.ld';linker.write_text('''MEMORY {
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
        output=self.root/'linked.elf'
        r=subprocess.run([compiler,*flags,'-nostdlib',*objects,str(stubs),'-Wl,--gc-sections',
                          '-Wl,-e,main','-Wl,-T,'+str(linker),'-o',str(output)],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        raw=output.read_bytes();report=self.audit.inspect(raw)
        self.assertEqual(set(report['instruction_audit']),{'candidate_gelu_f32','RmsNormF','rvv_residual_add_f32'})
        from elftools.elf.elffile import ELFFile
        elf=ELFFile(io.BytesIO(raw));sym=elf.get_section_by_name('.symtab').get_symbol_by_name('candidate_gelu_f32')[0]
        sec=elf.get_section(sym['st_shndx']);at=sec['sh_offset']+sym['st_value']-sec['sh_addr']
        bad=bytearray(raw);patched=0
        for i in range(at,at+sym['st_size']-3,2):
            word=int.from_bytes(raw[i:i+4],'little')
            if word&127==0x57 and (word>>26)&63==32 and (word>>12)&7==1:
                bad[i:i+4]=b'\x13\x00\x00\x00';patched+=1
        self.assertGreater(patched,0)
        with self.assertRaisesRegex(ValueError,'Missing actual candidate vector FP32 division'):
            self.audit.inspect(bytes(bad))

if __name__=='__main__':unittest.main()
