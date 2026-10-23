"""Native and real RV32 static checks, plus mocked execution gates. NO RTL."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import materialize as gen


class LargeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.tools=gen.materialize(cls.root/'tools')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def child(self,code):
        env=os.environ.copy();env['PYTHONPATH']=str(self.tools);env['PYTHONDONTWRITEBYTECODE']='1'
        result=subprocess.run([sys.executable,'-B','-c',code],env=env,capture_output=True,text=True,
                              encoding='utf-8',errors='replace',timeout=240)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result.stdout

    def test_immutable_versioned_generator_and_parent_sources(self):
        self.assertEqual(gen.verify(self.root/'tools'),self.tools)
        with self.assertRaisesRegex(ValueError,'Destination exists'):gen.materialize(self.root/'tools')
        record=json.loads((self.root/'tools/tool-manifest.json').read_text())
        self.assertEqual(record['provenance']['sweep_revision'],gen.SWEEP_PIN)
        self.assertNotIn('verification/google_llm_vme_sweep_v1/optimized_core.h',record['files'])
        for directory in ('google_llm_vme_opt','google_llm_vme_sweep'):
            diff=subprocess.check_output(['git','-C',str(gen.REPO),'diff',gen.SWEEP_PIN,'--','verification/'+directory])
            self.assertEqual(diff,b'')

    def test_generated_syntax_and_required_host_build(self):
        for path in self.tools.glob('*.py'):ast.parse(path.read_text(),filename=str(path))
        shell=os.environ.get('LLM_TEST_BASH')
        if not shell:self.skipTest('Set LLM_TEST_BASH')
        for path in [*self.tools.glob('*.sh'),*gen.HERE.glob('*.sh')]:
            r=subprocess.run([shell,'-n',str(path)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,str(path)+r.stderr)
        self.child('''
import prepare,lv_spec as s,lv_audit as a
b=prepare.build_text()
assert s.PROBE_INDEX==8 and len(s.CASES)==8 and s.PACKAGE=='tests/cocotb/llm_vme_large_v1'
assert all(s.testcase(i) in b for i in range(9))
assert 'host_blocked_test' in b and 'blocked_core.h' in b and 'blocked_test.cc' in b
assert 'blocked_core.h' in b.split('cc_test(name="host_reference_test"',1)[1].split('cc_test(name="host_packing_test"',1)[0]
assert a.SIZES['lv_gold']==16416 and a.SIZES['lv_x']==8192 and a.SIZES['lv_w']==32768
assert a.SIZES['lv_opt_workspace']==5152 and a.SIZES['lv_opt_reuse_weights']==33312
assert all(n%64==0 and k%4==0 for _,m,k,n in s.CASES)
''')

    def test_prepared_include_inventory_and_versioned_install(self):
        self.child('''
import re,tempfile
from pathlib import Path
import prepare
files=prepare.expected(Path(%r))
for name in ('linear_bench.cc','blocked_test.cc','blocked_core.h','optimized_core.h'):
    for header in re.findall(r'^#include "([^"]+)"',files[name].decode(),re.M):
        assert header in files,(name,header)
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    manifest=prepare.install(root,files)
    assert prepare.install(root,files)==manifest
    assert manifest['kind']=='llm_vme_large_preparation_v1'
    target=root/prepare.spec.PACKAGE/'blocked_core.h'
    target.write_bytes(b'changed')
    try:prepare.install(root,files)
    except ValueError:pass
    else:raise AssertionError('must not overwrite candidate')
''' % str(gen.REPO/'.upstream-git/coralnpu-google.git'))

    def test_gold_is_once_outside_all_timing_windows_and_prepack_outside_M_loop(self):
        text=(self.tools/'linear_bench.cc').read_text()
        self.assertLess(text.index('Reset(lv_gold)'),text.index('const uint32_t empty=Cycle()'))
        self.assertIn('const int64_t expected=lv_gold.data[at]',text)
        self.assertIn('if(!OutputGuard(lv_gold,m*n)',text)
        blocked=(self.tools/'blocked_core.h').read_text()
        self.assertEqual(blocked.count('PrepareOptimizedWeights('),1)
        self.assertEqual(blocked.count('PrepareWeights('),1)
        self.assertEqual(blocked.count('first+=16'),2)
        self.assertIn('y+first*n',blocked)
        self.assertIn('RunBlockedLegacyComplete',text)
        self.assertIn('RunBlockedOptimizedComplete',text)

    def test_last_M_block_and_N_tail_reference_layout(self):
        self.child('''
import struct,lv_spec as s
for index,(_,m,k,n) in enumerate(s.CASES):
    v=s.vectors(index);actual=s.workspace(index);direct=s.optimized_workspace(index)
    assert len(actual)==len(direct)==5152 and len(s.packed_weights(index))==33312
    base=((m-1)//16)*16;tokens=m-base
    x=struct.unpack('<'+'b'*len(v['x']),v['x'])
    encoded=bytes(x[(base+lane)*k+d]+128 if d<k and lane<tokens else 0 for d in range((k+3)&~3) for lane in range(16))
    assert actual[16:16+len(encoded)]==encoded
    assert direct[-1040:-16]==s.GUARD*256
    assert s.commands(index)==((m+15)//16)*((n+15)//16)*((k+3)//4)
for index,(m,k,n) in enumerate(s.PROBE_SHAPES):
    v=s.probe_vectors(index)
    if k==256:
        w=struct.unpack('<'+'b'*len(v['w']),v['w'])
        assert sum(w[d*n] for d in range(k))==32512
        assert sum(w[d*n+1] for d in range(k))==-32512
assert s.probe_contract()['probe_cases']==8 and s.probe_contract()['probe_fallback_tiles']==0
''')

    def test_cpp_python_buffer_layout_agree_for_all_logical_shapes(self):
        compiler=os.environ.get('LLM_TEST_CXX')
        if not compiler:self.skipTest('Set LLM_TEST_CXX')
        helper=self.root/'layout.cc'
        helper.write_text('''#define main candidate_main
#include "linear_bench.cc"
#undef main
#include <cstdio>
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif
int main() {
#ifdef _WIN32
  _setmode(_fileno(stdout),_O_BINARY);
#endif
  for(unsigned i=0;i<8;++i) {
    if(Run(i))return 1;
    std::fwrite(&lv_workspace,1,sizeof(lv_workspace),stdout);
    std::fwrite(&lv_opt_workspace,1,sizeof(lv_opt_workspace),stdout);
    std::fwrite(&lv_reuse_weights,1,sizeof(lv_reuse_weights),stdout);
    std::fwrite(&lv_opt_reuse_weights,1,sizeof(lv_opt_reuse_weights),stdout);
    std::fwrite(&lv_gold,1,sizeof(lv_gold),stdout);
  }
  return 0;
}
''')
        executable=self.root/('layout.exe' if os.name=='nt' else 'layout')
        build=subprocess.run([compiler,'-std=c++17','-O2','-DLV_HOST=1','-Wall','-Wextra','-Werror',
                              '-I'+str(self.tools),str(helper),'-o',str(executable)],capture_output=True,text=True)
        self.assertEqual(build.returncode,0,build.stdout+build.stderr)
        run=subprocess.run([str(executable)],capture_output=True,timeout=180)
        self.assertEqual(run.returncode,0,run.stderr)
        dump=self.root/'layout.bin';dump.write_bytes(run.stdout)
        self.child('''
import struct,pathlib,lv_spec as s
data=pathlib.Path(%r).read_bytes();at=0
for i,(_,m,k,n) in enumerate(s.CASES):
    v=s.vectors(i)
    gold=s.GUARD*4+struct.pack('<'+'i'*(m*n),*v['y'])+s.GUARD*(4096-m*n)+s.GUARD*4
    for expected in (s.workspace(i),s.optimized_workspace(i),s.packed_weights(i),s.packed_weights(i),gold):
        assert data[at:at+len(expected)]==expected,(i,at)
        at+=len(expected)
assert at==len(data)
''' % str(dump))

    def test_tamper_and_extra_manifest_name_rejected(self):
        path=self.tools/'blocked_core.h';raw=path.read_bytes()
        try:
            path.write_bytes(raw+b'\n// invalid\n')
            with self.assertRaisesRegex(ValueError,'generated tools'):gen.verify(self.root/'tools')
        finally:path.write_bytes(raw)
        path=self.tools/'tool-manifest.json'
        try:
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError,'generated tools'):gen.verify(self.root/'tools')
        finally:path.unlink()

    def test_entry_prepare_quick_failure_and_resume_with_stubbed_children(self):
        shell=os.environ.get('LLM_TEST_BASH')
        if not shell:self.skipTest('Set LLM_TEST_BASH')
        program=r'''
bash() { printf 'MOCK_BASH:%s\n' "$*"; if [[ "${MOCK_FAIL:-}" == prepare && "$1" == */prepare_tomorrow.sh ]];then return 7;fi; }
python3() { printf 'MOCK_PYTHON:%s\n' "$*"; }
uname() { printf 'Linux\n'; }
mktemp() { mkdir -p "$MOCK_JOB"; printf '%s\n' "$MOCK_JOB"; }
entry_script=$1
shift
source "$entry_script" "$@"
'''
        env=os.environ.copy();env['MOCK_JOB']=(self.root/'entry_job').as_posix()
        for mode in ('prepare','quick'):
            r=subprocess.run([shell,'-c',program,'unit',str(gen.HERE/'run.sh'),mode,str(self.root)],
                             env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertIn('prepare_tomorrow.sh',r.stdout)
            self.assertEqual('run_vm.sh' in r.stdout,mode=='quick')
            self.assertEqual('summarize.py' in r.stdout,mode=='quick')
        env['MOCK_FAIL']='prepare'
        r=subprocess.run([shell,'-c',program,'unit',str(gen.HERE/'run.sh'),'quick',str(self.root)],
                         env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
        self.assertNotEqual(r.returncode,0);self.assertNotIn('run_vm.sh',r.stdout)
        env.pop('MOCK_FAIL')
        r=subprocess.run([shell,'-c',program,'unit',str(gen.HERE/'resume.sh'),str(self.root),'all'],
                         env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual(r.stdout.count('MOCK_BASH:'),1)
        self.assertIn('--existing',r.stdout);self.assertIn('run_vm.sh',r.stdout)
        self.assertNotIn('prepare_tomorrow.sh',r.stdout)

    def test_real_native_cross_ELF_and_mocked_probe_evidence_regressions(self):
        base,_=gen.pinned_sweep(gen.REPO)
        source=subprocess.check_output(['git','-C',str(gen.REPO),'show',
            base.PARENT+':verification/google_llm_vme_opt/test_lv.py']).decode()
        source=source.replace('HERE=Path(__file__).resolve().parent','HERE=Path('+repr(str(self.tools))+')')
        source=source.replace('repo=HERE.parent.parent','repo=Path('+repr(str(gen.REPO))+')')
        source=source.replace('llm_vme_opt_','llm_vme_large_').replace('LLM_VME_OPT','LLM_VME_LARGE')
        source=source.replace('M=16,K=64,N=64,','M=17,K=65,N=17,')
        source=source.replace("case_id=4,case='optimized_instruction_probe'","case_id=8,case='optimized_instruction_probe'")
        source=source.replace('probe_current_case=8,probe_step=6','probe_current_case=7,probe_step=6')
        source=source.replace("rtl_sha256=spec.RTL_SHA,elf_sha256='a'*64,requested_cycles=5000000,",
                              "rtl_sha256=spec.RTL_SHA,elf_sha256='a'*64,requested_cycles=20000000,")
        source=source.replace('requested_cycles=10000000,observation_elapsed_cycles=100000',
                              'requested_cycles=30000000,observation_elapsed_cycles=100000')
        source=source.replace('opt_complete_fast_tiles=4*((n+15)//16),opt_reuse_fast_tiles=4*((n+15)//16)',
                              'opt_complete_fast_tiles=4*((m+15)//16)*((n+15)//16),opt_reuse_fast_tiles=4*((m+15)//16)*((n+15)//16)')
        source=source.replace("+'[LV_OPT_PACK_HOST_PASS]",
                              "+'[LV_LARGE_BLOCK_HOST_PASS] cases=1008 hardware=NOT_RUN\\n'+'[LV_OPT_PACK_HOST_PASS]")
        source=source.replace("('core_test.cc',['-DLV_HOST=1'])):",
                              "('core_test.cc',['-DLV_HOST=1']),('blocked_test.cc',['-DLV_HOST=1'])):")
        source=source.replace('spec.testcase(4)','spec.testcase(8)').replace('vm.checked_results(root,bundle,4)','vm.checked_results(root,bundle,8)')
        source=source.replace('vm.run_vm(prepared,4,100)','vm.run_vm(prepared,8,100)')
        source=source.replace('for index in (4,0,1,2,3)','for index in (8,0,1,2,3,4,5,6,7)')
        source=source.replace('for i in range(5) if spec.target(i)','for i in range(9) if spec.target(i)')
        source=source.replace('if index==4 else observation(index)','if index==8 else observation(index)')
        source=source.replace('Validated 1/4','Validated 1/8')
        source=source.replace('p_memsz=65536,p_filesz=4', 'p_memsz=327680,p_filesz=4')
        source=source.replace('0x01080000,0x01010000,0x0107c000', '0x01080000,0x01050000,0x0107c000')
        harness=self.root/'parent_regressions.py';harness.write_text(source,encoding='utf-8')
        names=(
            'test_actual_native_main_and_980_boundary_arithmetic_cases',
            'test_real_rv32_objects_and_vme_encodings_not_hardware_execution',
            'test_exhaustive_native_dimensions_1_16_by_1_64_by_1_64',
            'test_amortized_prepack_is_charged_and_slow_vme_is_valid',
            'test_no_false_pass_missing_paths_corrupt_data_or_cycle_windows',
            'test_raw_xml_and_exit_state_gate',
            'test_elf_audit_rejects_wrong_map_missing_selector_or_overlap',
            'test_matrix_store_must_preserve_mtype_not_use_standard_vset',
            'test_instruction_decoder_rejects_desynchronization_and_detects_vset',
            'test_configuration_query_change_rejects_before_simulation',
            'test_server_performance_requires_this_elf_probe_on_same_model',
            'test_vm_xml_log_status_and_elf_all_gate_acceptance',
            'test_vm_prepare_builds_configured_test_executables_without_running_them',
            'test_vm_probe_then_case_evidence_and_tampering_gate',
            'test_failed_vm_attempt_keeps_logs_and_never_registers_pass',
            'test_child_cleans_waves_and_uses_owned_process_group',
            'test_tomorrow_shell_default_prepare_and_failure_stop_with_stubbed_children',
        )
        self.child('''
import importlib.util,unittest,sys
s=importlib.util.spec_from_file_location('parent_regressions',%r);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
suite=unittest.TestSuite(m.Checks(name) for name in %r)
r=unittest.TextTestRunner(verbosity=2).run(suite)
assert not r.skipped, 'Required compiler/static checks skipped'
sys.exit(0 if r.wasSuccessful() else 1)
''' % (str(harness),names))


if __name__=='__main__':unittest.main()
