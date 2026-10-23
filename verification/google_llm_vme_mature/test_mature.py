"""Native, real RV32 static audits and mocked rejection tests; NEVER RTL."""
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import materialize as gen


class MatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # MinGW cc1plus/runtime DLLs need its bin directory on PATH on Windows.
        # This changes the test process only, never the user's system settings.
        if os.name=='nt' and os.environ.get('LLM_TEST_CXX'):
            os.environ['PATH']=str(Path(os.environ['LLM_TEST_CXX']).parent)+os.pathsep+os.environ['PATH']
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.tools=gen.materialize(cls.root/'tools')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def child(self,code,timeout=240):
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        env['PYTHONPATH']=str(self.tools)+os.pathsep+env.get('PYTHONPATH','')
        r=subprocess.run([sys.executable,'-B','-c',code],env=env,capture_output=True,text=True,
                         encoding='utf-8',errors='replace',timeout=timeout)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        return r.stdout

    def test_provenance_and_qualified_baseline_only_renamed(self):
        self.assertEqual(gen.verify(self.root/'tools'),self.tools)
        with self.assertRaisesRegex(ValueError,'Destination exists'):gen.materialize(self.root/'tools')
        base,_=gen.pinned();files,_=base.sources()
        old=files[base.GENERATED+'/optimized_core.h'].decode()
        self.assertEqual((self.tools/'qualified_core.h').read_text(),gen.qualified_header(old))
        for directory in ('google_llm_vme_opt','google_llm_vme_sweep','google_llm_vme_large'):
            diff=subprocess.check_output(['git','-C',str(gen.REPO),'diff','HEAD','--','verification/'+directory])
            self.assertEqual(diff,b'')

    def test_tampered_tools_and_incomplete_manifest_are_rejected(self):
        path=self.tools/'hoisted_loop.h';raw=path.read_bytes()
        try:
            path.write_bytes(raw+b'changed')
            with self.assertRaisesRegex(ValueError,'changed generated'):gen.verify(self.root/'tools')
        finally:path.write_bytes(raw)
        path=self.tools/'unexpected.txt';path.write_text('extra')
        try:
            with self.assertRaisesRegex(ValueError,'changed generated'):gen.verify(self.root/'tools')
        finally:path.unlink()

    def test_all_source_syntax_build_includes_and_baseline_identity(self):
        for path in self.tools.glob('*.py'):ast.parse(path.read_text(),filename=str(path))
        self.child('''
import ast,re,prepare,lv_spec as s,lv_audit as a
from pathlib import Path
root=Path(%r);files=prepare.expected(Path(%r));build=prepare.build_text()
for name,raw in files.items():
    if name.endswith(('.cc','.h')):
        for header in re.findall(r'^#include "([^\"]+)"',raw.decode(),re.M):
            assert header in files,(name,header)
tree=ast.parse(build)
for node in ast.walk(tree):
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='cc_test':
        fields={k.arg:ast.literal_eval(k.value) for k in node.keywords}
        assert 'hdrs' not in fields
        if fields['name']=='host_reference_test':assert 'qualified_core.h' in fields['srcs']
        assert 'hoisted_loop.h' in fields['srcs']
assert len(s.CASES)==6 and s.PROBE_INDEX==6 and len(s.PROBE_SHAPES)==13
assert 'mature' in s.SCOPE or 'configure_once' in s.SCOPE
assert s.PACKAGE=='tests/cocotb/llm_vme_mature_v1'
assert s.RTL_SHA=='477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2'
for i in range(6):assert s.workspace(i)==s.optimized_workspace(i)
assert 'Qualified VME complete' in (root/'summarize.py').read_text()
assert 'HoistedKLoop' in (root/'lv_audit.py').read_text()
''' % (str(self.tools),str(gen.REPO/'.upstream-git/coralnpu-google.git')))

    def test_shell_syntax_and_build_only_default(self):
        shell=os.environ.get('LLM_TEST_BASH')
        if not shell:self.skipTest('Set LLM_TEST_BASH')
        for path in [*self.tools.glob('*.sh'),*gen.HERE.glob('*.sh')]:
            r=subprocess.run([shell,'-n',str(path)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,str(path)+r.stderr)
        program=r'''
bash() { printf 'MOCK_BASH:%s\n' "$*"; if [[ "${MOCK_FAIL:-}" == yes ]];then return 7;fi; }
python3() { printf 'MOCK_PYTHON:%s\n' "$*"; }
uname() { printf 'Linux\n'; }
mktemp() { mkdir -p "$MOCK_JOB"; printf '%s\n' "$MOCK_JOB"; }
entry=$1;shift
source "$entry" "$@"
'''
        env=os.environ.copy();env['MOCK_JOB']=(self.root/'mock_job').as_posix()
        for mode in ('prepare','quick'):
            r=subprocess.run([shell,'-c',program,'unit',str(gen.HERE/'run.sh'),mode,str(self.root)],
                             env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertEqual('run_vm.sh' in r.stdout,mode=='quick')
            self.assertEqual('summarize.py' in r.stdout,mode=='quick')
        env['MOCK_FAIL']='yes'
        r=subprocess.run([shell,'-c',program,'unit',str(gen.HERE/'run.sh'),'quick',str(self.root)],
                         env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
        self.assertNotEqual(r.returncode,0);self.assertNotIn('run_vm.sh',r.stdout)

    def test_native_five_paths_and_980_extreme_cases(self):
        compiler=os.environ.get('LLM_TEST_CXX')
        if not compiler:self.skipTest('Set LLM_TEST_CXX')
        logs=[]
        for name in ('linear_bench.cc','core_test.cc'):
            executable=self.root/(name+'.exe' if os.name=='nt' else name+'.out')
            r=subprocess.run([compiler,'-std=c++17','-O2','-DLV_HOST=1','-Wall','-Wextra','-Werror',
                              '-I'+str(self.tools),str(self.tools/name),'-o',str(executable)],
                             capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            r=subprocess.run([str(executable)],capture_output=True,text=True,timeout=120)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr);logs.append(r.stdout)
        self.child('import lv_spec as s;s.checked_host('+repr(''.join(logs))+')')

    def test_real_rv32_loop_structure_resources_and_mutations(self):
        compiler=os.environ.get('LLM_TEST_CROSS')
        if not compiler:self.skipTest('Set LLM_TEST_CROSS')
        obj=self.root/'bench.o'
        r=subprocess.run([compiler,'-std=c++17','-march=rv32imf_zve32f_zicsr','-mabi=ilp32',
            '-O2','-Wall','-Wextra','-Werror','-fno-tree-vectorize','-fno-tree-slp-vectorize','-fno-lto',
            '-I'+str(self.tools),'-I'+str(self.tools.parent/'google_person_vme'),
            '-c',str(self.tools/'linear_bench.cc'),'-o',str(obj)],capture_output=True,text=True,
            encoding='utf-8',errors='replace')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.child('''
import io,json
from pathlib import Path
from elftools.elf.elffile import ELFFile
import lv_audit as a
raw=Path(%r).read_bytes();elf=ELFFile(io.BytesIO(raw));report=a.instruction_audit(elf)
loops=report['components']['HoistedKLoop']['loop_structure']
assert len(loops)==2 and sorted(l['mset_dimension_in_body'] for l in loops)==[0,2]
symbols={s.name:s for s in elf.get_section_by_name('.symtab').iter_symbols()}
for name,size in a.SIZES.items():assert symbols[name]['st_size']==size,(name,size)
target=next(s for s in symbols.values() if 'HoistedKLoop' in s.name and s['st_size'])
section=elf.get_section(target['st_shndx']);start=int(section['sh_offset'])+int(target['st_value'])
end=start+int(target['st_size']);positions=[];off=start
while off<end:
    half=int.from_bytes(raw[off:off+2],'little');size=4 if half&3==3 else 2
    if size==4:positions.append((off,int.from_bytes(raw[off:off+4],'little')))
    off+=size
matrix=next(at for at,w in positions if w==0xf28800f7)
mutations=(0x0d207057,0x0000006f,0x82007057,0x00000013)
for word in mutations:
    bad=bytearray(raw);bad[matrix:matrix+4]=word.to_bytes(4,'little')
    try:a.instruction_audit(ELFFile(io.BytesIO(bad)))
    except ValueError:pass
    else:raise AssertionError('Corrupt matrix body accepted: '+hex(word))
print('[MATURE_RV32_STATIC_PASS] full_partial_loops=2 mutation_rejections=4 RTL=NOT_RUN')
''' % str(obj))

    def test_inherited_fail_closed_result_probe_and_resource_gates(self):
        # Execute established control-flow regression tests against THIS generated
        # implementation. Synthetic observations are NEVER accepted as RTL runs.
        base,_=gen.pinned()
        raw=subprocess.check_output(['git','-C',str(gen.REPO),'show',
            base.PARENT+':verification/google_llm_vme_opt/test_lv.py']).decode()
        raw=raw.replace('HERE=Path(__file__).resolve().parent','HERE=Path('+repr(str(self.tools))+')')
        raw=raw.replace('repo=HERE.parent.parent','repo=Path('+repr(str(gen.REPO))+')')
        raw=raw.replace('llm_vme_opt_','llm_vme_mature_').replace('LLM_VME_OPT','LLM_VME_MATURE')
        raw=raw.replace("case_id=4,case='optimized_instruction_probe'","case_id=6,case='optimized_instruction_probe'")
        raw=raw.replace('probe_current_case=8,probe_step=6','probe_current_case=12,probe_step=6')
        raw=raw.replace('spec.testcase(4)','spec.testcase(6)').replace('vm.checked_results(root,bundle,4)','vm.checked_results(root,bundle,6)')
        raw=raw.replace('vm.run_vm(prepared,4,100)','vm.run_vm(prepared,6,100)')
        raw=raw.replace('for index in (4,0,1,2,3)','for index in (6,0,1,2,3,4,5)')
        raw=raw.replace('for i in range(5) if spec.target(i)','for i in range(7) if spec.target(i)')
        raw=raw.replace('if index==4 else observation(index)','if index==6 else observation(index)')
        raw=raw.replace('Validated 1/4','Validated 1/6')
        raw=raw.replace("'optimized_core.h','vm_bench.py')}",
                        "'optimized_core.h','vm_bench.py','hoisted_loop.h','qualified_core.h')}")
        harness=self.root/'inherited.py';harness.write_text(raw,encoding='utf-8')
        names=('test_real_rv32_objects_and_vme_encodings_not_hardware_execution',
               'test_exhaustive_native_dimensions_1_16_by_1_64_by_1_64',
               'test_synthetic_packet_export_roundtrip_and_corruption_rejection',
               'test_amortized_prepack_is_charged_and_slow_vme_is_valid',
               'test_no_false_pass_missing_paths_corrupt_data_or_cycle_windows',
               'test_native_log_requires_both_tests_and_all_signatures',
               'test_raw_xml_and_exit_state_gate','test_elf_audit_rejects_wrong_map_missing_selector_or_overlap',
               'test_child_cleans_waves_and_uses_owned_process_group',
               'test_server_performance_requires_this_elf_probe_on_same_model',
               'test_vm_xml_log_status_and_elf_all_gate_acceptance',
               'test_vm_prepare_builds_configured_test_executables_without_running_them',
               'test_vm_probe_then_case_evidence_and_tampering_gate',
               'test_instruction_decoder_rejects_desynchronization_and_detects_vset',
               'test_configuration_query_change_rejects_before_simulation',
               'test_failed_vm_attempt_keeps_logs_and_never_registers_pass')
        self.child('''
import importlib.util,unittest,sys
s=importlib.util.spec_from_file_location('inherited',%r);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
suite=unittest.TestSuite(m.Checks(name) for name in %r)
r=unittest.TextTestRunner(verbosity=2).run(suite)
assert not r.skipped
sys.exit(0 if r.wasSuccessful() else 1)
''' % (str(harness),names))


if __name__=='__main__':unittest.main()
