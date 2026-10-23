"""Native mirrors, true source provenance and fail-closed tools. NEVER RTL."""
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
import unittest
from unittest.mock import patch
import materialize as gen


class OfficialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name=='nt' and os.environ.get('LLM_TEST_CXX'):
            os.environ['PATH']=str(Path(os.environ['LLM_TEST_CXX']).parent)+os.pathsep+os.environ['PATH']
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.tools=gen.materialize(cls.root/'tools')
        sys.path.insert(0,str(cls.tools))
        import lv_spec,lv_audit,prepare
        cls.spec=lv_spec;cls.audit=lv_audit;cls.prepare=prepare
        cls.files=prepare.expected(gen.REPO/'.upstream-git/coralnpu-google.git')
        cls.source=cls.root/'native';cls.source.mkdir()
        for name,data in cls.files.items():(cls.source/name).write_bytes(data)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def observation(self,index):
        s=self.spec;d=s.fixture(index)
        return dict(schema=1,scope=s.PROBE_SCOPE if index==6 else s.SCOPE,case_id=index,case=d['name'],kind=d['kind'],
            shape=list(d['shape']),itcm_kib=256,dtcm_kib=512,rtl_sha256=s.RTL_SHA,elf_sha256='a'*64,
            vector_sha256=d['vector_sha256'],algorithm_sha256=d['algorithm_sha256'],atol=s.ATOL,rtol=s.RTOL,
            fault=False,natural_halt=True,firmware_status=3,checked_elements=12*len(d['y']),algorithm_mismatches=0,
            guard_ok=True,scalar_calls=4,project_calls=4,official_calls=4,input_readback_equal=True,
            mathematical_baselines_check=True,official_algorithm_output_check=True,stack_low_canary_intact=True,
            requested_cycles=10000000,empty_boundary_cycles=3,observation_elapsed_cycles=100000,
            scalar_cycles=[1000]*4,project_cycles=[500]*4,official_cycles=[250]*4,
            strict_math_quality_pass=True,strict_math_quality_mismatches=0,
            official_max_math_abs_error=0.,official_max_algorithm_abs_error=0.,probe_signature=s.signature(d['algorithm']))

    def test_actual_rv32_original_sources_and_resource_link_not_execution(self):
        compiler=os.environ.get('LLM_TEST_CROSS')
        if not compiler:self.skipTest('Set LLM_TEST_CROSS with BF16 intrinsic support')
        flags=['-std=c++17','-march=rv32imf_zve32f_zicsr_zfbfmin_zvfbfmin_zvfbfwma','-mabi=ilp32',
            '-O2','-ffp-contract=off','-fno-tree-vectorize','-fno-tree-slp-vectorize','-fno-lto',
            '-fno-exceptions','-fno-rtti','-Wall','-Wextra','-Werror','-I'+str(self.source)]
        objects=[]
        for name in ('linear_bench.cc','kernels.cc','fixtures.cc',*[n for n in self.prepare.OFFICIAL if n.endswith('.cc')]):
            obj=self.root/(name+'.o');objects.append(obj)
            result=subprocess.run([compiler,*flags,'-c',str(self.source/name),'-o',str(obj)],capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(result.returncode,0,name+'\n'+result.stdout+result.stderr)
        # These stubs support ONLY a synthetic resource/encoding link. This ELF
        # is NEVER executed and is NOT the official VM CRT/libm build.
        support=self.root/'static_link_stubs.cc';support.write_text('''
extern "C" void* memset(void* p,int v,unsigned n){volatile unsigned char* q=(volatile unsigned char*)p;for(unsigned i=0;i<n;++i)q[i]=v;return p;}
extern "C" void* memcpy(void* p,const void* s,unsigned n){volatile unsigned char* q=(volatile unsigned char*)p;const unsigned char* r=(const unsigned char*)s;for(unsigned i=0;i<n;++i)q[i]=r[i];return p;}
extern "C" float sqrtf(float x){return x;}
extern "C" float expf(float x){return x;}
extern "C" float tanhf(float x){return x;}
''')
        linker=self.root/'static_link.ld';linker.write_text('''MEMORY {
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
        elf=self.root/'static_link.elf'
        result=subprocess.run([compiler,*flags,'-nostdlib',*[str(o) for o in objects],str(support),
            '-Wl,-e,main','-Wl,-T,'+str(linker),'-o',str(elf)],capture_output=True,text=True,encoding='utf-8',errors='replace')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        report=self.audit.inspect(elf.read_bytes());self.assertEqual(report['NPU_RTL'],'NOT_RUN')
        self.assertEqual(len(report['instruction_audit']),3)
        self.assertLess(report['itcm_occupied_extent_bytes'],262144)
        self.assertLess(report['dtcm_static_extent_bytes'],512*1024-16384)

    def test_export_packet_roundtrip_is_integrity_not_rtl(self):
        import export as exporter
        import lv_packet
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'source';root.mkdir();job=Path(temp)/'job';job.mkdir()
            base=type('Base',(),{'prepare':lambda root:None})
            loader=type('Loader',(),{'loader':type('L',(),{'exec_module':lambda self,m:None})()})()
            with patch.object(importlib.util,'module_from_spec',return_value=base),patch.object(importlib.util,'spec_from_file_location',return_value=loader),\
                 patch.object(self.prepare,'expected',return_value=self.files):source=self.prepare.prepare(root)
            (root/'LICENSE').write_text('Synthetic fixture for export integrity ONLY')
            (job/'source-manifest.json').write_text(json.dumps(source))
            data=b'NOT EXECUTABLE: packet integrity fixture only';(job/'probe_program.elf').write_bytes(data)
            report={'elf_sha256':self.spec.sha(job/'probe_program.elf'),'NPU_RTL':'NOT_RUN'}
            (job/'resources.json').write_text(json.dumps(report));(job/'build.log').write_text('mock build; NOT RTL')
            host=''.join(f'[OFFICIAL_HOST] id={i} checked={12*len(self.spec.fixture(i)["y"])} algorithms_ok=1 hardware=NOT_RUN\n' for i in range(7))
            (job/'host.log').write_text(host)
            params=dict(xlen='32',itcmSizeKBytes='256',dtcmSizeKBytes='512',axi2IdBits='6',rvvVlen='128',
                fetchDataBits='128',lsuDataBits='128',enableFetchL0='false',enableRvv='true',enableVme='true',
                enableFloat='true',enableZfbfmin='true',enableVectorBf16='true',enableAxiInstructionFetch='true',enableVerification='false')
            (job/'parameters.h').write_text(''.join('#define KP_'+k+' '+v+'\n' for k,v in params.items()))
            (job/'rtl-identity.json').write_text(json.dumps(dict(rtl_sha256=self.spec.RTL_SHA,parameters=params)))
            with patch.object(self.prepare,'prepare',return_value=source),patch.object(self.audit,'inspect',return_value=report),patch('sys.stdout',new=io.StringIO()):
                exporter.export(root,job);packet=job/self.spec.PACKET_NAME;lv_packet.load(packet)
                self.assertFalse((packet/'rtl').exists())
                (packet/'tx_reference.py').write_text('corrupt')
                with self.assertRaises(ValueError):lv_packet.load(packet)

    def test_snapshot_syntax_official_and_project_bytes(self):
        self.assertEqual(gen.verify(self.root/'tools'),self.tools)
        for path in self.tools.glob('*.py'):ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
        for name in self.prepare.OFFICIAL:
            raw=subprocess.check_output(['git','--git-dir='+str(gen.REPO/'.upstream-git/coralnpu-google.git'),
                'show',self.spec.UPSTREAM+':'+self.prepare.ROOT+name])
            self.assertEqual(self.files[name],raw)
        for name in ('kernels.cc','kernels.h'):
            self.assertEqual(self.files[name],gen.read('verification/google_llm_ops/transformer/'+name))
        changes=subprocess.check_output(['git','-C',str(gen.REPO),'diff','HEAD','--',
            'verification/google_llm_vme_pair','verification/google_llm_ops'])
        self.assertEqual(changes,b'')
        path=self.tools/'lv_spec.py';raw=path.read_bytes()
        try:
            path.write_bytes(raw+b'changed')
            with self.assertRaises(ValueError):gen.verify(self.root/'tools')
        finally:path.write_bytes(raw)

    def test_build_dependencies_and_no_fake_host_rvv(self):
        tree=ast.parse(self.prepare.build_text());calls={n.func.id+':'+next(k.value.value for k in n.keywords if k.arg=='name'):n
            for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and any(k.arg=='name' for k in n.keywords)}
        host={k.arg:ast.literal_eval(k.value) for k in calls['cc_test:host_reference_test'].keywords}
        self.assertNotIn('hdrs',host);self.assertIn('host_mirrors.cc',host['srcs'])
        binary={k.arg:ast.literal_eval(k.value) for k in calls['coralnpu_v2_binary:probe_program'].keywords}
        self.assertNotIn('host_mirrors.cc',binary['srcs'])
        for name in self.prepare.OFFICIAL:
            if name.endswith('.cc'):self.assertIn(name,binary['srcs'])
        self.assertEqual(binary['itcm_size_kbytes'],256);self.assertEqual(binary['dtcm_size_kbytes'],512)
        shell=(self.tools/'build_export.sh').read_text()
        self.assertNotIn('host_packing_test',shell)
        self.assertIn("sequence=(spec.PROBE_INDEX,0)",(self.tools/'vm.py').read_text())
        self.assertNotIn('run_vm.sh',(gen.HERE/'run.sh').read_text())

    def test_native_three_paths_against_independent_fixtures(self):
        compiler=os.environ.get('LLM_TEST_CXX')
        if not compiler:self.skipTest('Set LLM_TEST_CXX')
        exe=self.root/('native.exe' if os.name=='nt' else 'native')
        build=subprocess.run([compiler,'-std=c++17','-O2','-DTX_HOST=1','-ffp-contract=off','-Wall','-Wextra','-Werror',
            '-I'+str(self.source),*[str(self.source/n) for n in ('linear_bench.cc','kernels.cc','fixtures.cc','host_mirrors.cc')],
            '-o',str(exe)],capture_output=True,text=True,encoding='utf-8',errors='replace')
        self.assertEqual(build.returncode,0,build.stdout+build.stderr)
        result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.spec.checked_host(result.stdout)

    def test_gelu_approximation_is_detected_not_relabelled(self):
        found=False
        for index in (3,4,5):
            d=self.spec.fixture(index)
            failures=sum(abs(a-b)>self.spec.ATOL+self.spec.RTOL*abs(b) for a,b in zip(d['algorithm'],d['y']))
            found=found or failures>0
            row=self.observation(index);row['strict_math_quality_pass']=failures==0
            row['strict_math_quality_mismatches']=4*failures
            row['official_max_math_abs_error']=max(abs(a-b) for a,b in zip(d['algorithm'],d['y']))
            result=self.spec.accept(row,index)
            if failures:self.assertEqual(result['qualification'],'ALGORITHM_DIAGNOSTIC_ONLY_NOT_STRICT_MATH_QUALIFIED')
        self.assertTrue(found,'Fixtures must expose the known approximation, not hide it')
        row=self.observation(1);row.update(strict_math_quality_pass=False,strict_math_quality_mismatches=4,official_max_math_abs_error=.1)
        with self.assertRaises(ValueError):self.spec.accept(row,1)

    def test_failed_paths_bad_cycles_and_quality_cannot_pass(self):
        valid=self.observation(0);self.spec.accept(valid,0)
        for name,value in dict(fault=True,natural_halt=False,firmware_status=2,algorithm_mismatches=1,
            scalar_calls=0,project_calls=0,official_calls=0,guard_ok=False,input_readback_equal=False,
            mathematical_baselines_check=False,official_algorithm_output_check=False,stack_low_canary_intact=False,
            vector_sha256='bad',algorithm_sha256='bad',rtl_sha256='b'*64,
            official_cycles=[1]*4,official_max_algorithm_abs_error=.5,official_max_math_abs_error=1.,
            strict_math_quality_mismatches=4,requested_cycles=100).items():
            bad=copy.deepcopy(valid);bad[name]=value
            with self.subTest(name=name),self.assertRaises(ValueError):self.spec.accept(bad,0)

    def test_model_geometry_malformed_elf_and_xml_fail_closed(self):
        with self.assertRaises(Exception):self.audit.inspect(b'not an ELF')
        import xml.etree.ElementTree as ET
        for xml in ('<testsuite/>','<testsuite><testcase><failure/></testcase></testsuite>',
                    '<testsuite skipped="1"><testcase/></testsuite>'):
            with self.assertRaises(ValueError):self.spec.checked_xml(ET.fromstring(xml))
        self.spec.checked_xml(ET.fromstring('<testsuite><testcase/></testsuite>'))

    def test_raw_probe_gate_and_exit_state_retained(self):
        import vm
        from types import SimpleNamespace
        probe=self.observation(6)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);packet=SimpleNamespace(report={'elf_sha256':'a'*64})
            (root/'test-status.json').write_text('{"exit_code":0,"timed_out":false}')
            (root/'test.xml').write_text('<testsuite><testcase/></testsuite>')
            text='running vm_bench.candidate_probe_test (1/1)\n'+self.spec.MARKER+json.dumps(probe)+'\nTESTS=1 PASS=1 FAIL=0 SKIP=0'
            (root/'test.log').write_text(text);vm.checked_results(root,packet,6)
            (root/'test-status.json').write_text('{"exit_code":1,"timed_out":false}')
            with self.assertRaises(ValueError):vm.checked_results(root,packet,6)
            with self.assertRaises(ValueError):vm.checked_probe(root,{},packet)

    def test_install_refuses_any_existing_source_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);base=type('Base',(),{'prepare':lambda root:None})
            # Only installation state is mocked; no fake ELF/proof is accepted.
            with patch.object(importlib.util,'module_from_spec',return_value=base),patch.object(importlib.util,'spec_from_file_location',
                return_value=type('Loader',(),{'loader':type('L',(),{'exec_module':lambda self,m:None})()})()),patch.object(self.prepare,'expected',return_value=self.files):
                before=self.prepare.prepare(root);self.assertEqual(before,self.prepare.prepare(root))
                path=root/self.spec.PACKAGE/'rvv_rms_norm.cc';path.write_bytes(b'changed')
                with self.assertRaises(ValueError):self.prepare.prepare(root)
                self.assertEqual(path.read_bytes(),b'changed')

    def test_shell_syntax(self):
        shell=os.environ.get('LLM_TEST_BASH')
        if not shell:self.skipTest('Set LLM_TEST_BASH')
        for path in [*self.tools.glob('*.sh'),*gen.HERE.glob('*.sh')]:
            result=subprocess.run([shell,'-n',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,str(path)+result.stderr)


if __name__=='__main__':unittest.main()
