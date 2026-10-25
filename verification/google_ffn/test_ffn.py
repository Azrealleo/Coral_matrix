"""Native FFN semantics and RV32 static verification; not RTL evidence."""
import ast
import io
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import fixture
import materialize as gen

class FFNTests(unittest.TestCase):
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

    def test_reference_has_three_distinct_projections_and_residual(self):
        shape=(1,1,2,0,0);x=[1.];w=[0.,1.,-1.,2.,3.,4.,5.]
        y=fixture.golden(shape,x,w);layout=fixture.layout(shape)
        stage={name:y[at:at+n] for name,at,n in layout}
        norm=fixture.f32(1/math.sqrt(1+1e-5))
        self.assertEqual(stage['norm'],[norm]);self.assertEqual(stage['gate'],[norm,-norm])
        self.assertEqual(stage['up'],[fixture.f32(2*norm),fixture.f32(3*norm)])
        self.assertEqual(stage['down'],[fixture.f32(4*stage['activation'][0]+5*stage['activation'][1])])
        self.assertEqual(stage['output'],[fixture.f32(stage['down'][0]+1)])
        changed=w[:];changed[3]=0.
        other=fixture.golden(shape,x,changed)
        self.assertEqual(other[:7],y[:7]);self.assertNotEqual(other,y)
        for index in range(4):
            d=fixture.fixture(index);self.assertEqual(d,self.spec.fixture(index))
            self.assertEqual(d['y'],d['algorithm'])
            for _,at,n in fixture.layout(d['shape'])[:-1]:
                self.assertEqual(fixture.packed(d['y'][at+n:at+n+4]),self.spec.GUARD*4)
            self.assertLessEqual(max(len(d['x']),len(d['w']),len(d['y'])),1024)
        with self.assertRaises(ValueError):fixture.golden(shape,x,[0.])
        for index in (-1,4,True):
            with self.assertRaises(ValueError):fixture.fixture(index)

    def test_frozen_sources_and_runtime_dependencies(self):
        self.assertEqual(gen.verify(self.root/'tools'),self.tools)
        for path in self.tools.glob('*.py'):ast.parse(path.read_text(encoding='utf-8'))
        self.assertEqual(self.files['candidate.cc'],gen.read('verification/google_gelu_rvv_mlas/candidate.cc'))
        for name in self.prepare.OFFICIAL:
            expected=subprocess.check_output(['git','--git-dir='+str(gen.REPO/'.upstream-git/coralnpu-google.git'),
                                             'show',self.spec.UPSTREAM+':'+self.prepare.ROOT+name])
            self.assertEqual(self.files[name],expected)
        build=self.files['BUILD'].decode()
        self.assertIn('"ffn_fixture.py"',build);self.assertIn("'ffn.cc'",build)
        self.assertIn('ffn_layout.h',build)
        for name,_,_ in fixture.CASES:
            self.assertIn('candidate_'+name+'_test',(self.tools/'vm_bench.py').read_text())
        for name in ('export.py','lv_packet.py'):
            self.assertIn("'ffn_fixture.py'",(self.tools/name).read_text())

    def test_native_semantics_guard_and_swapped_projection_rejection(self):
        run=self.run_native();self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        compiler=os.environ['LLM_TEST_CXX'];exe=self.root/'accuracy.exe'
        r=subprocess.run([compiler,'-std=c++17','-O2','-ffp-contract=off','-DTX_HOST',str(self.native/'candidate.cc'),
                          str(self.native/'host_accuracy.cc'),'-o',str(exe)],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        dense=subprocess.run([str(exe)],capture_output=True,text=True)
        self.assertEqual(dense.returncode,0,dense.stdout+dense.stderr)
        self.spec.checked_host(run.stdout+dense.stdout)
        with self.assertRaises(ValueError):self.spec.checked_host(run.stdout)
        code=self.files['ffn.cc'].decode()
        swapped=code.replace('Linear(m,h,f,y+l.offset[0],wu,y+l.offset[2]);','Linear(m,h,f,y+l.offset[0],wg,y+l.offset[2]);')
        self.assertNotEqual(self.run_native(swapped).returncode,0)
        corrupt='#include <cstring>\n'+code.replace('RmsNormF(m,h,1e-5f,x,w,y+l.offset[0]);',
            'RmsNormF(m,h,1e-5f,x,w,y+l.offset[0]);unsigned bad=0x55aa7710;std::memcpy(y+l.guard[0],&bad,4);')
        self.assertNotEqual(self.run_native(corrupt).returncode,0)

    def run_native(self,text=None):
        compiler=os.environ.get('LLM_TEST_CXX')
        if not compiler:self.skipTest('Set LLM_TEST_CXX')
        names=('ffn.cc','candidate.cc','linear_bench.cc','kernels.cc','fixtures.cc','host_mirrors.cc')
        sources=[str(self.native/n) for n in names]
        if text:
            path=self.root/'broken_ffn.cc';path.write_text(text);sources[0]=str(path)
        exe=self.root/('broken.exe' if text else 'host.exe')
        r=subprocess.run([compiler,'-std=c++17','-O2','-ffp-contract=off','-fno-tree-vectorize','-DTX_HOST',
                          '-Wall','-Wextra','-Werror','-I'+str(self.native),*sources,'-o',str(exe)],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        return subprocess.run([str(exe)],capture_output=True,text=True)

    def test_accept_requires_all_six_stages(self):
        s=self.spec;d=s.fixture(0);names=[n for n,_,_ in fixture.layout(d['shape'])]
        row=dict(schema=1,scope=s.SCOPE,case_id=0,case=d['name'],kind=d['kind'],shape=list(d['shape']),
                 itcm_kib=256,dtcm_kib=512,rtl_sha256=s.RTL_SHA,vector_sha256=d['vector_sha256'],
                 algorithm_sha256=d['algorithm_sha256'],atol=s.ATOL,rtol=s.RTOL,
                 fault=False,natural_halt=True,firmware_status=3,checked_elements=12*len(d['y']),
                 algorithm_mismatches=0,guard_ok=True,scalar_calls=4,project_calls=4,official_calls=4,
                 input_readback_equal=True,mathematical_baselines_check=True,official_algorithm_output_check=True,
                 stack_low_canary_intact=True,requested_cycles=10000000,elf_sha256='0'*64,
                 empty_boundary_cycles=3,observation_elapsed_cycles=100000,scalar_cycles=[100]*4,
                 project_cycles=[100]*4,official_cycles=[100]*4,strict_math_quality_pass=True,
                 strict_math_quality_mismatches=0,official_max_math_abs_error=0.,official_max_algorithm_abs_error=0.,
                 ffn_stage_math_pass=dict.fromkeys(names,True),ffn_stage_max_abs_error=dict.fromkeys(names,0.),
                 ffn_stage_guards_exact=True)
        self.assertEqual(s.accept(row,0)['qualification'],'STRICT_MATH_PASS')
        for name in names:
            for bad_value in (False,1):
                bad=dict(row,ffn_stage_math_pass=dict(row['ffn_stage_math_pass'],**{name:bad_value}))
                with self.assertRaises(ValueError):s.accept(bad,0)
        for key,value in (('ffn_stage_guards_exact',False),('ffn_stage_max_abs_error',{}),('fault',True),('natural_halt',False)):
            bad=dict(row);bad[key]=value
            with self.assertRaises(ValueError):s.accept(bad,0)

    def test_real_rv32_gc_link_requires_five_vector_entries(self):
        compiler=os.environ.get('LLM_TEST_CROSS')
        if not compiler:self.skipTest('Set LLM_TEST_CROSS')
        flags=['-std=c++17','-O2','-ffp-contract=off','-fno-tree-vectorize','-fno-tree-slp-vectorize',
               '-ffunction-sections','-fdata-sections','-fno-exceptions','-fno-rtti','-fno-lto',
               '-march=rv32imf_zve32f_zicsr_zfbfmin_zvfbfmin_zvfbfwma','-mabi=ilp32','-I'+str(self.native)]
        objects=[]
        for name in ('ffn.cc','candidate.cc','linear_bench.cc','kernels.cc','fixtures.cc',
                     *[n for n in self.prepare.OFFICIAL if n.endswith('.cc')]):
            obj=self.root/(name+'.o');objects.append(str(obj))
            r=subprocess.run([compiler,*flags,'-c',str(self.native/name),'-o',str(obj)],capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        # Static resource fixture ONLY; stubs are never executed.
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
        elf=self.root/'linked.elf'
        r=subprocess.run([compiler,*flags,'-nostdlib',*objects,str(stubs),'-Wl,--gc-sections','-Wl,-e,main',
                          '-Wl,-T,'+str(linker),'-o',str(elf)],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        raw=elf.read_bytes();report=self.audit.inspect(raw)
        self.assertEqual(set(report['instruction_audit']),{'candidate_gelu_f32','RmsNormF','rvv_residual_add_f32',
                                                         'rvv_gemv_1d_f32','rvv_tiled_matmul_2d_f32'})
        from elftools.elf.elffile import ELFFile
        e=ELFFile(io.BytesIO(raw));sym=e.get_section_by_name('.symtab').get_symbol_by_name('candidate_gelu_f32')[0]
        sec=e.get_section(sym['st_shndx']);at=sec['sh_offset']+sym['st_value']-sec['sh_addr'];bad=bytearray(raw);patched=0
        for i in range(at,at+sym['st_size']-3,2):
            word=int.from_bytes(raw[i:i+4],'little')
            if word&127==0x57 and (word>>26)&63==32 and (word>>12)&7==1:
                bad[i:i+4]=b'\x13\x00\x00\x00';patched+=1
        self.assertGreater(patched,0)
        with self.assertRaisesRegex(ValueError,'Missing actual candidate vector FP32 division'):
            self.audit.inspect(bytes(bad))

if __name__=='__main__':unittest.main()
