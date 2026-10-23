"""Real native/cross static checks and mocked runner gates. NO RTL execution."""
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


class SweepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        cls.tools=gen.materialize(cls.root/'tools')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def child(self,code):
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        env['PYTHONPATH']=str(self.tools)
        result=subprocess.run([sys.executable,'-B','-c',code],env=env,capture_output=True,text=True,
                              encoding='utf-8',errors='replace',timeout=240)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result.stdout

    def test_identity_and_no_parent_or_old_preparation_overwrite(self):
        self.assertEqual(gen.verify(self.root/'tools'),self.tools)
        with self.assertRaisesRegex(ValueError,'already exists'):gen.materialize(self.root/'tools')
        marker=json.loads((self.root/'tools/tool-manifest.json').read_text())
        self.assertEqual(marker['parent_revision'],gen.PARENT)
        self.assertNotIn('verification/google_llm_vme_opt/optimized_core.h',marker['files'])
        for path in gen.REPO.joinpath('verification/google_llm_vme_opt').glob('*'):
            if path.is_file() and path.name not in ('test_lv.py','README.md'):
                raw=subprocess.check_output(['git','-C',str(gen.REPO),'show',gen.PARENT+':'+path.relative_to(gen.REPO).as_posix()])
                # read_text normalizes Windows checkout CRLF; immutable Git
                # source, not the editor's newline policy, defines provenance.
                self.assertEqual(path.read_text(),raw.decode())

    def test_strict_template_replacement(self):
        with self.assertRaisesRegex(ValueError,'template mismatch'):gen.replace('a a','a','b')
        with self.assertRaisesRegex(ValueError,'template mismatch'):gen.replace('a','missing','b')

    def test_materialized_sources_parse_and_shell_syntax(self):
        for path in self.tools.glob('*.py'):ast.parse(path.read_text(),filename=str(path))
        shell=os.environ.get('LLM_TEST_BASH')
        if not shell:self.skipTest('Set LLM_TEST_BASH')
        for path in [*self.tools.glob('*.sh'),*gen.HERE.glob('*.sh')]:
            result=subprocess.run([shell,'-n',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,str(path)+result.stderr)
        self.child('import prepare,lv_spec as s; b=prepare.build_text(); '
                   'assert s.PROBE_INDEX==6 and len(s.CASES)==6; '
                   'assert all(s.testcase(i) in b for i in range(7)); '
                   'assert "tests/cocotb/llm_vme_sweep_v1"==s.PACKAGE; '
                   'assert ":model" in b and "hdrs" not in b[b.index("cc_test"):b.index("py_library")]; '
                   'assert "case_id=4" not in open(s.__file__).read()')

    def test_shape_and_probe_golden_independent(self):
        self.child('''
import hashlib,struct
import lv_spec as s
assert [c[1] for c in s.CASES]==[1,2,4,8,12,16]
assert len(s.PROBE_SHAPES)==13
for i,(_,m,k,n) in enumerate(s.CASES):
    v=s.vectors(i);x=struct.unpack('<'+'b'*len(v['x']),v['x']);w=struct.unpack('<'+'b'*len(v['w']),v['w'])
    assert all(-127<=a<=127 for a in w) and x[0]==-128
    gold=[sum(x[r*k+d]*w[d*n+c] for d in range(k)) for r in range(m) for c in range(n)]
    assert gold==v['y'] and hashlib.sha256(v['x']+v['w']).hexdigest()==v['vector_sha256']
    assert s.commands(i)==64
contract=s.probe_contract()
assert contract['probe_fast_tiles']==sum((n+15)//16 for m,k,n in s.PROBE_SHAPES)
assert contract['probe_fallback_tiles']==0 and contract['probe_cases']==13
assert set([2,4,8,12]).issubset({p[0] for p in s.PROBE_SHAPES})
''')

    def test_all_M_use_direct_stores_without_ordinary_vset(self):
        code=(self.tools/'optimized_core.h').read_text()
        self.assertIn('if(m>=1 && m<=16)',code)
        self.assertNotIn('if(m==1 || m==16)',code)
        direct=code.split('void FastTileToRowMajor',1)[1].split('#endif',1)[0]
        self.assertNotIn('"vset',direct)
        self.assertIn('if(tokens==1)',direct)
        self.assertIn('"r"(tokens)',direct)
        self.assertIn('"r"(full_width)',direct)

    def test_generated_probe_indexes_and_sequential_gate(self):
        self.child('''
import ast,lv_spec as s,vm
assert vm.proof_name(6)=='probe-proof.json'
assert vm.proof_name(4)=='case4-proof.json'
assert vm.model_query()==vm.model_query(6)
assert s.testcase(6)=='candidate_probe_test'
tree=ast.parse(open(vm.__file__).read())
assert not any(isinstance(n,ast.Compare) and any(isinstance(x,ast.Constant) and x.value==4 for x in n.comparators) for n in ast.walk(tree))
text=open(vm.__file__).read()
assert 'sequence=(spec.PROBE_INDEX,3)' in text
assert 'checked_probe(prepared,record,packet)' in text
assert 'choices=range(7),default=6' in text
''')

    def test_generated_tree_tampering_and_extra_file_are_rejected(self):
        target=self.tools/'optimized_core.h';raw=target.read_bytes()
        try:
            target.write_bytes(raw+b'\n// tampered\n')
            with self.assertRaisesRegex(ValueError,'generated tool files'):gen.verify(self.root/'tools')
        finally:target.write_bytes(raw)
        extra=self.tools/'extra.txt'
        try:
            extra.write_text('not in inventory')
            with self.assertRaisesRegex(ValueError,'generated tool files'):gen.verify(self.root/'tools')
        finally:extra.unlink()
        gen.verify(self.root/'tools')

    def test_reused_strict_native_target_and_evidence_regressions(self):
        # Reuse selected parent test METHODS, but run against the GENERATED
        # candidate modules. All fake simulation paths remain mocked, while
        # native and RV32 compiler tests execute real compilers.
        test_source=subprocess.check_output(['git','-C',str(gen.REPO),'show',
            gen.PARENT+':verification/google_llm_vme_opt/test_lv.py']).decode()
        test_source=test_source.replace('HERE=Path(__file__).resolve().parent','HERE=Path('+repr(str(self.tools))+')')
        test_source=test_source.replace('repo=HERE.parent.parent','repo=Path('+repr(str(gen.REPO))+')')
        test_source=test_source.replace("HERE.parent/'google_person_vme'","Path("+repr(str(gen.REPO/'verification/google_person_vme'))+")")
        test_source=test_source.replace("case_id=4,case='optimized_instruction_probe'","case_id=6,case='optimized_instruction_probe'")
        test_source=test_source.replace('probe_current_case=8,probe_step=6','probe_current_case=12,probe_step=6')
        test_source=test_source.replace('llm_vme_opt_', 'llm_vme_sweep_').replace('LLM_VME_OPT','LLM_VME_SWEEP')
        test_source=test_source.replace('spec.testcase(4)', 'spec.testcase(6)')
        test_source=test_source.replace('vm.checked_results(root,bundle,4)', 'vm.checked_results(root,bundle,6)')
        test_source=test_source.replace('vm.run_vm(prepared,4,100)', 'vm.run_vm(prepared,6,100)')
        test_source=test_source.replace('for index in (4,0,1,2,3)', 'for index in (6,0,1,2,3,4,5)')
        test_source=test_source.replace('for i in range(5) if spec.target(i)', 'for i in range(7) if spec.target(i)')
        test_source=test_source.replace('if index==4 else observation(index)', 'if index==6 else observation(index)')
        test_source=test_source.replace('Validated 1/4', 'Validated 1/6')
        harness=self.root/'parent_regressions.py';harness.write_text(test_source,encoding='utf-8')
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
        # Pinned methods assert constants not changed by this sweep. New shape,
        # probe-index and controller coverage is implemented above/below.
        output=self.child('''
import importlib.util,unittest,sys
s=importlib.util.spec_from_file_location('parent_regressions',%r)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
suite=unittest.TestSuite(m.Checks(name) for name in %r)
r=unittest.TextTestRunner(verbosity=2).run(suite)
assert not r.skipped, 'Required compiler/static checks skipped'
sys.exit(0 if r.wasSuccessful() else 1)
''' % (str(harness),names))
        self.assertNotIn('RTL_PASS',output)

    def test_entry_default_prepare_quick_failfast_and_resume_with_stubbed_children(self):
        bash=os.environ.get('LLM_TEST_BASH')
        if not bash:self.skipTest('Set LLM_TEST_BASH')
        # Intercept every child, including the materializer. No actual Bazel,
        # model, Python test runner or simulator is launched by this test.
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
            result=subprocess.run([bash,'-c',program,'unit',str(gen.HERE/'run.sh'),mode,str(self.root)],
                                  env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('prepare_tomorrow.sh',result.stdout)
            self.assertEqual('run_vm.sh' in result.stdout,mode=='quick')
            self.assertEqual('summarize.py' in result.stdout,mode=='quick')
        env['MOCK_FAIL']='prepare'
        failure=subprocess.run([bash,'-c',program,'unit',str(gen.HERE/'run.sh'),'quick',str(self.root)],
                               env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
        self.assertNotEqual(failure.returncode,0)
        self.assertNotIn('run_vm.sh',failure.stdout)
        env.pop('MOCK_FAIL')
        resumed=subprocess.run([bash,'-c',program,'unit',str(gen.HERE/'resume.sh'),str(self.root),'all'],
                               env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
        self.assertEqual(resumed.returncode,0,resumed.stdout+resumed.stderr)
        self.assertEqual(resumed.stdout.count('MOCK_BASH:'),1)
        self.assertIn('--existing',resumed.stdout)
        self.assertIn('run_vm.sh',resumed.stdout)
        self.assertNotIn('prepare_tomorrow.sh',resumed.stdout)

    def test_probe_early_fault_and_bad_signature_rejected(self):
        self.child('''
import lv_spec as s
c=s.probe_contract()
row=dict(schema=1,scope=s.PROBE_SCOPE,case_id=6,case='optimized_instruction_probe',M=16,K=64,N=64,
itcm_kib=256,dtcm_kib=512,fault=False,natural_halt=True,firmware_status=3,guard_ok=True,
input_readback_equal=True,output_readback_equal=True,packed_readback_equal=True,workspace_readback_equal=True,
stack_low_canary_intact=True,probe_mismatches=0,probe_fail_case=0xffffffff,probe_current_case=12,probe_step=6,
probe_first_element=0xffffffff,probe_first_actual=0,probe_first_expected=0,rtl_sha256=s.RTL_SHA,
requested_cycles=5000000,observation_elapsed_cycles=10000,elf_sha256='a'*64,**c)
assert s.accept(row,6)['probe_cases']==13
for key,value in [('fault',True),('probe_current_case',8),('probe_fast_tiles',0),('probe_fallback_tiles',1),('probe_signature',0),('case_id',4)]:
    bad=dict(row);bad[key]=value
    try:s.accept(bad,6)
    except ValueError:pass
    else:raise AssertionError(key)
''')


if __name__=='__main__':unittest.main()
