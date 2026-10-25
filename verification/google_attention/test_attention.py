"""Native/reference and real RV32 static audits, never claimed as RTL."""
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

class AttentionTests(unittest.TestCase):
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

    def test_closed_form_causality_and_absolute_rope_table(self):
        shape=(1,2,0,0,0);x=[1.,2.,3.,4.]
        w=[0.]*2+[0.]*8+[1.,0.,0.,1.]*2+[1.,0.,fixture.f32(math.cos(1)),fixture.f32(math.sin(1))]
        y=fixture.golden(shape,x,w);parts={name:y[at:at+n] for name,at,n in fixture.layout(shape)}
        norm=[fixture.f32(v/math.sqrt((1+4)/2+1e-5)) for v in x[:2]]+[
              fixture.f32(v/math.sqrt((9+16)/2+1e-5)) for v in x[2:]]
        context=norm[:2]+[fixture.f32((a+b)/2) for a,b in zip(norm[:2],norm[2:])]
        self.assertEqual(parts['norm'],norm);self.assertEqual(parts['context'],context)
        self.assertEqual(parts['projected'],context)
        self.assertEqual(parts['output'],[fixture.f32(a+b) for a,b in zip(x,context)])
        other=fixture.golden(shape,x[:2]+[-100.,2.],w)
        at=fixture.layout(shape)[10][1]
        self.assertEqual(y[at:at+2],other[at:at+2])
        self.assertEqual(parts['prefill_k'][2:],[fixture.KEY_POISON]*2)
        for index in range(4):
            d=fixture.fixture(index);self.assertEqual(d,self.spec.fixture(index))
            p,h,base,*_=d['shape'];coeff=d['w'][h+4*h*h:]
            self.assertEqual(coeff[p*h],fixture.f32(math.cos(base+p)))
            for _,at,n in fixture.layout(d['shape'])[:-1]:
                self.assertEqual(fixture.packed(d['y'][at+n:at+n+4]),self.spec.GUARD*4)
            self.assertLessEqual(max(len(d['x']),len(d['w']),len(d['y'])),1024)
        for shape in ((1,3,0,0,0),(0,2,0,0,0),(1,2,-1,0,0)):
            with self.assertRaises(ValueError):fixture.layout(shape)

    def test_frozen_sources_and_runtime_inventory(self):
        self.assertEqual(gen.verify(self.root/'tools'),self.tools)
        for path in self.tools.glob('*.py'):ast.parse(path.read_text(encoding='utf-8'))
        for name in self.prepare.OFFICIAL:
            raw=subprocess.check_output(['git','--git-dir='+str(gen.REPO/'.upstream-git/coralnpu-google.git'),
                'show',self.spec.UPSTREAM+':'+self.prepare.ROOT+name])
            self.assertEqual(self.files[name],raw)
        self.assertNotIn('candidate.cc',self.files)
        self.assertNotIn('host_accuracy_test',self.files['BUILD'].decode())
        for name,_,_ in fixture.CASES:
            self.assertIn('candidate_'+name+'_test',(self.tools/'vm_bench.py').read_text())
        for name in ('export.py','lv_packet.py'):
            self.assertIn("'attention_fixture.py'",(self.tools/name).read_text())
        self.assertIn('attention_layout.h',self.files['BUILD'].decode())

    def run_native(self,code=None,kernels=None):
        compiler=os.environ.get('LLM_TEST_CXX')
        if not compiler:self.skipTest('Set LLM_TEST_CXX')
        sources=[]
        for name in ('attention.cc','linear_bench.cc','kernels.cc','fixtures.cc','host_mirrors.cc'):
            raw=code if name=='attention.cc' else kernels if name=='kernels.cc' else None
            if raw is not None:
                path=self.root/('broken_'+name);path.write_text(raw)
            else:path=self.native/name
            sources.append(str(path))
        exe=self.root/'host.exe'
        r=subprocess.run([compiler,'-std=c++17','-O2','-ffp-contract=off','-fno-tree-vectorize','-DTX_HOST',
                          '-Wall','-Wextra','-Werror','-I'+str(self.native),*sources,'-o',str(exe)],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        return subprocess.run([str(exe)],capture_output=True,text=True)

    def test_native_stream_bulk_and_cache_fault_rejection(self):
        run=self.run_native();self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.spec.checked_host(run.stdout)
        with self.assertRaises(ValueError):self.spec.checked_host(run.stdout.splitlines()[0])
        code=self.files['attention.cc'].decode()
        bad=code.replace('Copy(path,y+l.offset[KR]+p*h,h,cache.data+p*h);',
            'Copy(path,y+l.offset[KR]+p*h,h,cache.data+p*h);cache.data[0]=0;')
        self.assertNotEqual(self.run_native(code=bad).returncode,0)

    def test_native_future_leak_and_wrong_decode_rope_rejected(self):
        code=self.files['attention.cc'].decode()
        bad=code.replace('const float* coeff=w+h+4*h*h+at;','const float* coeff=w+h+4*h*h;')
        self.assertNotEqual(self.run_native(code=bad).returncode,0)
        kernels=self.files['kernels.cc'].decode().replace('std::min(t.c,t.p+q+1)','t.c')
        self.assertNotEqual(self.run_native(kernels=kernels).returncode,0)

    def test_accept_requires_cache_bulk_and_all_stages(self):
        s=self.spec;d=s.fixture(0);names=list(fixture.NAMES)
        row=dict(schema=1,scope=s.SCOPE,case_id=0,case=d['name'],kind=d['kind'],shape=list(d['shape']),
                 itcm_kib=256,dtcm_kib=512,rtl_sha256=s.RTL_SHA,vector_sha256=d['vector_sha256'],
                 algorithm_sha256=d['algorithm_sha256'],atol=s.ATOL,rtol=s.RTOL,fault=False,natural_halt=True,
                 firmware_status=3,checked_elements=12*len(d['y']),algorithm_mismatches=0,guard_ok=True,
                 scalar_calls=4,project_calls=4,official_calls=4,input_readback_equal=True,
                 mathematical_baselines_check=True,official_algorithm_output_check=True,stack_low_canary_intact=True,
                 requested_cycles=10000000,elf_sha256='0'*64,empty_boundary_cycles=3,observation_elapsed_cycles=100000,
                 scalar_cycles=[100]*4,project_cycles=[100]*4,official_cycles=[100]*4,
                 strict_math_quality_pass=True,strict_math_quality_mismatches=0,official_max_math_abs_error=0.,
                 official_max_algorithm_abs_error=0.,attention_stage_math_pass=dict.fromkeys(names,True),
                 attention_stage_max_abs_error=dict.fromkeys(names,0.),attention_stage_guards_exact=True,
                 cache_prefix_bitwise_retained=True,cache_local_guards=True,bulk_math_pass=True,
                 bulk_stream_math_pass=True,bulk_guards_exact=True,bulk_calls=1,bulk_mismatches=0,
                 bulk_checked=len(d['y']),stream_stage_counts=[[8,32,16,8,8,8]]*3)
        self.assertEqual(s.accept(row,0)['qualification'],'STRICT_MATH_PASS')
        for key,value in (('cache_prefix_bitwise_retained',False),('bulk_stream_math_pass',False),
                          ('bulk_math_pass',False),('bulk_calls',0),('bulk_checked',0),('cache_local_guards',False),
                          ('stream_stage_counts',[[8,36,16,8,8,8]]*3),('bulk_guards_exact',False)):
            bad=dict(row);bad[key]=value
            with self.assertRaises(ValueError):s.accept(bad,0)
        for name in names:
            bad=dict(row,attention_stage_math_pass=dict(row['attention_stage_math_pass'],**{name:False}))
            with self.assertRaises(ValueError):s.accept(bad,0)

    def test_actual_rv32_gc_link_and_vector_entry_rejection(self):
        compiler=os.environ.get('LLM_TEST_CROSS')
        if not compiler:self.skipTest('Set LLM_TEST_CROSS')
        flags=['-std=c++17','-O2','-ffp-contract=off','-fno-tree-vectorize','-fno-tree-slp-vectorize',
               '-ffunction-sections','-fdata-sections','-fno-exceptions','-fno-rtti','-fno-lto',
               '-march=rv32imf_zve32f_zicsr_zfbfmin_zvfbfmin_zvfbfwma','-mabi=ilp32','-I'+str(self.native)]
        objects=[]
        for name in ('attention.cc','linear_bench.cc','kernels.cc','fixtures.cc',
                     *[n for n in self.prepare.OFFICIAL if n.endswith('.cc')]):
            obj=self.root/(name+'.o');objects.append(str(obj))
            r=subprocess.run([compiler,*flags,'-c',str(self.native/name),'-o',str(obj)],capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        # Link/resource test ONLY. Stubs are never executed.
        stubs=self.root/'stubs.cc';stubs.write_text('''extern "C" float sqrtf(float x){return x;}
extern "C" float expf(float x){return x;}
extern "C" float tanhf(float x){return x;}
extern "C" void* memset(void* p,int v,unsigned n){volatile unsigned char* q=(volatile unsigned char*)p;for(unsigned i=0;i<n;++i)q[i]=v;return p;}
extern "C" void* memcpy(void* p,const void* s,unsigned n){volatile unsigned char* q=(volatile unsigned char*)p;const unsigned char* r=(const unsigned char*)s;for(unsigned i=0;i<n;++i)q[i]=r[i];return p;}
extern "C" int memcmp(const void* a,const void* b,unsigned n){const unsigned char* p=(const unsigned char*)a;const unsigned char* q=(const unsigned char*)b;for(unsigned i=0;i<n;++i)if(p[i]!=q[i])return p[i]-q[i];return 0;}
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
        r=subprocess.run([compiler,*flags,'-nostdlib',*objects,str(stubs),'-Wl,--gc-sections','-Wl,-e,main',
                          '-Wl,-T,'+str(linker),'-o',str(output)],capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        raw=output.read_bytes();report=self.audit.inspect(raw)
        self.assertEqual(set(report['instruction_audit']),{'RmsNormF','rvv_residual_add_f32',
            'rvv_gemv_1d_f32','rvv_tiled_matmul_2d_f32','project_Vector'})
        from elftools.elf.elffile import ELFFile
        elf=ELFFile(io.BytesIO(raw));sym=elf.get_section_by_name('.symtab').get_symbol_by_name('rvv_gemv_1d_f32')[0]
        sec=elf.get_section(sym['st_shndx']);at=sec['sh_offset']+sym['st_value']-sec['sh_addr'];end=at+sym['st_size']
        bad=bytearray(raw);patched=0
        while at<end:
            half=int.from_bytes(raw[at:at+2],'little');size=4 if half&3==3 else 2
            word=int.from_bytes(raw[at:at+size],'little')
            if size==4 and word&127==0x57 and (word>>12)&7!=7:
                bad[at:at+4]=b'\x13\x00\x00\x00';patched+=1
            at+=size
        self.assertGreater(patched,0)
        with self.assertRaisesRegex(ValueError,'No vector arithmetic in rvv_gemv_1d_f32'):
            self.audit.inspect(bytes(bad))

if __name__=='__main__':unittest.main()
