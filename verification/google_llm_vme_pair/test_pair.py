"""Local native, real RV32 static and mocked fail-closed checks; NEVER RTL."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
import materialize as gen


class PairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name=='nt' and os.environ.get('LLM_TEST_CXX'):
            os.environ['PATH']=str(Path(os.environ['LLM_TEST_CXX']).parent)+os.pathsep+os.environ['PATH']
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.tools=gen.materialize(cls.root/'tools')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def child(self,code,timeout=300):
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        env['PYTHONPATH']=str(self.tools)+os.pathsep+env.get('PYTHONPATH','')
        result=subprocess.run([sys.executable,'-B','-c',code],env=env,capture_output=True,text=True,
                              encoding='utf-8',errors='replace',timeout=timeout)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result.stdout

    def test_frozen_baseline_provenance_and_tamper_rejection(self):
        self.assertEqual(gen.verify(self.root/'tools'),self.tools)
        with self.assertRaisesRegex(ValueError,'Destination exists'):gen.materialize(self.root/'tools')
        parent,_=gen.pinned();files,_=parent.sources(gen.REPO)
        baseline=parent.qualified_header(files[parent.GENERATED+'/optimized_core.h'].decode())
        self.assertEqual((self.tools/'qualified_core.h').read_text(),baseline)
        path=self.tools/'pair_loop.h';original=path.read_bytes()
        try:
            path.write_bytes(original+b'changed')
            with self.assertRaisesRegex(ValueError,'changed pair'):gen.verify(self.root/'tools')
        finally:path.write_bytes(original)
        extra=self.tools/'unexpected.txt';extra.write_text('extra')
        try:
            with self.assertRaisesRegex(ValueError,'changed pair'):gen.verify(self.root/'tools')
        finally:extra.unlink()
        diff=subprocess.check_output(['git','-C',str(gen.REPO),'diff','HEAD','--',
            'verification/google_llm_vme_mature','verification/google_llm_vme_opt'])
        self.assertEqual(diff,b'')

    def test_generated_syntax_inventory_and_scope(self):
        for path in self.tools.glob('*.py'):ast.parse(path.read_text(),filename=str(path))
        self.child('''
import ast,re,prepare,lv_spec as s,lv_audit as a
from pathlib import Path
root=Path(%r);files=prepare.expected(Path(%r));build=prepare.build_text()
for name,raw in files.items():
    if name.endswith(('.cc','.h')):
        for header in re.findall(r'^#include "([^\\"]+)"',raw.decode(),re.M):
            assert header in files,(name,header)
for node in ast.walk(ast.parse(build)):
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='cc_test':
        fields={k.arg:ast.literal_eval(k.value) for k in node.keywords}
        assert 'hdrs' not in fields
        if fields['name']=='host_reference_test':assert 'qualified_core.h' in fields['srcs']
        for h in ('hoisted_loop.h','pair_loop.h','pair_tile.h'):assert h in fields['srcs']
assert s.PACKAGE=='tests/cocotb/llm_vme_pair_v2'
assert len(s.CASES)==6 and s.PROBE_INDEX==6 and len(s.PROBE_SHAPES)==13
assert 'paired_mt0_mt4' in s.SCOPE
assert s.RTL_SHA=='477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2'
for i in range(6):assert s.workspace(i)==s.optimized_workspace(i)
for n in ('lv_opt_complete_tiles','lv_opt_reuse_tiles','lv_probe_tiles'):assert a.SIZES[n]==16
assert "sequence=(spec.PROBE_INDEX,5)" in (root/'vm.py').read_text()
assert 'opt_cases=(5);' in (root/'run_server.sh').read_text()
assert 'Configure-once VME complete' in (root/'summarize.py').read_text()
''' % (str(self.tools),str(gen.REPO/'.upstream-git/coralnpu-google.git')))

    def test_v2_kernel_sources_are_byte_identical_to_failed_v1(self):
        revision='c9edb85cc8c16f79469deeeb2e3b7c5dc6a556c9'
        class PriorPath:
            def __init__(self,path):self.path=path
            def __truediv__(self,name):return PriorPath(self.path+'/'+name)
            def read_bytes(self):return subprocess.check_output(['git','-C',str(gen.REPO),'show',revision+':'+self.path])
            def read_text(self):return self.read_bytes().decode()
        raw=subprocess.check_output(['git','-C',str(gen.REPO),'show',
            revision+':verification/google_llm_vme_pair/materialize.py'])
        old=types.ModuleType('_failed_v1');old.__file__=str(gen.HERE/'materialize.py')
        exec(compile(raw,old.__file__,'exec'),old.__dict__)
        old.HERE=PriorPath('verification/google_llm_vme_pair')
        before,_=old.sources(gen.REPO);after,_=gen.sources(gen.REPO)
        kernel=lambda files,prefix:{Path(n).name:b for n,b in files.items()
            if n.startswith(prefix+'/') and n.endswith(('.cc','.h'))}
        self.assertEqual(kernel(before,old.GENERATED),kernel(after,gen.GENERATED))
        self.assertIn('pair_tile.h',kernel(after,gen.GENERATED))

    def test_vm_machine_code_constant_shift_regression_and_fail_closed_cases(self):
        fixture=json.loads((gen.HERE/'selector_fixture.json').read_text())
        self.assertEqual(fixture['elf_sha256'],'03d464f6dc77b986585516f0335c2082885c806730a7a68b69a2f7ebf0976874')
        self.child('''
import lv_audit as a
fixture=%r;raw=bytes.fromhex(fixture['bytes_hex'])
assert len(raw)==464
assert 0x20000537 not in a.words(raw),'Fixture must reproduce the old false rejection'
producers=a.pair_tile_constant_producers(raw)
assert any(p['instruction']=='0x01949e93' for p in producers),producers
class Symbol(dict):
    name=fixture['symbol']
class Section:
    def __getitem__(self,key):assert key=='sh_addr';return fixture['address']
    def data(self):return raw
class Table:
    def iter_symbols(self):return [Symbol(st_size=len(raw),st_info={'type':'STT_FUNC'},st_shndx=1,st_value=fixture['address'])]
class Elf:
    def get_section_by_name(self,name):assert name=='.symtab';return Table()
    def get_section(self,index):assert index==1;return Section()
report=a.audit_pair_tile_selector(Elf())
assert report['tile4_tss_constant']=='0x20000000' and report['dynamic_selection_proof'] is False
bad=bytearray(raw)
for offset in range(0,len(raw),4):
    w=int.from_bytes(raw[offset:offset+4],'little')
    if w&127==0x13 and (w>>12)&7==1 and w>>25==0 and (w>>20)&31==25:
        bad[offset:offset+4]=((w&~(31<<20))|(23<<20)).to_bytes(4,'little')
assert not a.pair_tile_constant_producers(bytes(bad)),'mt1 shift was accepted as mt4'
def code(*ws):return b''.join(w.to_bytes(4,'little') for w in ws)
li=0x01000493;slli=0x01949e93
assert a.pair_tile_constant_producers(code(li,slli))
assert a.pair_tile_constant_producers(code(0x20000eb7))  # same constant in t4, not fixed a0
for bad in (code(0x00400493,slli),code(slli),code(li,0x00052483,slli),
            code(li,0x0000006f,slli),code(li,0x00000063,slli),
            code(li)+bytes.fromhex('8144')+code(slli),
            code(0x01000013,0x01901e93)):
    assert not a.pair_tile_constant_producers(bad),bad.hex()
for bad in (b'\\x03',b'\\x03\\x00',b'\\x1f\\x00\\x00\\x00'):
    try:a.pair_tile_constant_producers(bad)
    except ValueError:pass
    else:raise AssertionError('Truncated/unsupported encoding accepted')
''' % fixture)

    def test_shell_and_default_prepare_never_launch_rtl(self):
        shell=os.environ.get('LLM_TEST_BASH')
        if not shell:self.skipTest('Set LLM_TEST_BASH')
        for path in [*self.tools.glob('*.sh'),*gen.HERE.glob('*.sh')]:
            result=subprocess.run([shell,'-n',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,str(path)+result.stderr)
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
            result=subprocess.run([shell,'-c',program,'unit',str(gen.HERE/'run.sh'),mode,str(self.root)],
                env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual('run_vm.sh' in result.stdout,mode=='quick')
        env['MOCK_FAIL']='yes'
        result=subprocess.run([shell,'-c',program,'unit',str(gen.HERE/'run.sh'),'quick',str(self.root)],
            env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
        self.assertNotEqual(result.returncode,0);self.assertNotIn('run_vm.sh',result.stdout)

    def test_native_five_paths_980_edges_and_probe_signatures(self):
        compiler=os.environ.get('LLM_TEST_CXX')
        if not compiler:self.skipTest('Set LLM_TEST_CXX')
        logs=[]
        for name in ('linear_bench.cc','core_test.cc'):
            executable=self.root/(name+('.exe' if os.name=='nt' else '.out'))
            result=subprocess.run([compiler,'-std=c++17','-O2','-DLV_HOST=1','-Wall','-Wextra','-Werror',
                '-I'+str(self.tools),str(self.tools/name),'-o',str(executable)],
                capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(executable)],capture_output=True,text=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);logs.append(result.stdout)
        self.child('import lv_spec as s;s.checked_host('+repr(''.join(logs))+')')

    def test_real_rv32_shared_loads_and_mutation_rejections(self):
        compiler=os.environ.get('LLM_TEST_CROSS')
        if not compiler:self.skipTest('Set LLM_TEST_CROSS')
        obj=self.root/'bench.o'
        result=subprocess.run([compiler,'-std=c++17','-march=rv32imf_zve32f_zicsr','-mabi=ilp32',
            '-O2','-Wall','-Wextra','-Werror','-fno-tree-vectorize','-fno-tree-slp-vectorize','-fno-lto',
            '-I'+str(self.tools),'-I'+str(self.tools.parent/'google_person_vme'),
            '-c',str(self.tools/'linear_bench.cc'),'-o',str(obj)],capture_output=True,text=True,
            encoding='utf-8',errors='replace')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.child('''
import io
from pathlib import Path
from elftools.elf.elffile import ELFFile
import lv_audit as a
raw=Path(%r).read_bytes();elf=ELFFile(io.BytesIO(raw));report=a.instruction_audit(elf)
loops=report['components']['PairKLoop']['loop_structure']
assert len(loops)==2 and sorted(l['mset_dimension_in_body'] for l in loops)==[0,2]
assert all(l['vector_loads_per_Tk4_pair']==12 and l['matrix_tiles']==[0,4] for l in loops)
symbols={s.name:s for s in elf.get_section_by_name('.symtab').iter_symbols()}
for name,size in a.SIZES.items():assert symbols[name]['st_size']==size,(name,size)
def instructions(symbol):
    sec=elf.get_section(symbol['st_shndx']);off=int(sec['sh_offset'])+int(symbol['st_value'])-int(sec['sh_addr'])
    end=off+int(symbol['st_size']);result=[]
    while off<end:
        half=int.from_bytes(raw[off:off+2],'little');size=4 if half&3==3 else 2
        if size==4:result.append((off,int.from_bytes(raw[off:off+4],'little')))
        off+=size
    return result
target=next(s for s in symbols.values() if 'PairKLoop' in s.name and s['st_size'])
positions=instructions(target);matrix=next(at for at,w in positions if w==0xf38804f7)
mutations=[(matrix,w) for w in (0xf28800f7,0xf28804f7,0xf38800f7,0x0d207057,0x0000006f,0x00000013)]
load,word=next((at,w) for at,w in positions if w&127==7 and (w>>7)&31==24)
mutations.append((load,(word&~(31<<7))|(16<<7)))
tile=next(s for s in symbols.values() if 'PairTileToRowMajor' in s.name and s['st_size'])
selectors=[(at,w) for at,w in instructions(tile) if w==0x20000537]
assert selectors,'No mt4 TSS constant emitted'
for at,word in mutations:
    bad=bytearray(raw);bad[at:at+4]=word.to_bytes(4,'little')
    try:a.instruction_audit(ELFFile(io.BytesIO(bad)))
    except ValueError:pass
    else:raise AssertionError('Corrupt paired body accepted: '+hex(word))
bad=bytearray(raw)
for at,w in selectors:bad[at:at+4]=(0x08000537).to_bytes(4,'little')
try:a.instruction_audit(ELFFile(io.BytesIO(bad)))
except ValueError:pass
else:raise AssertionError('All mt4 selectors changed to mt1 but accepted')
print('[PAIR_RV32_STATIC_PASS] full_partial_loops=2 mutation_rejections=8 RTL=NOT_RUN')
''' % str(obj))

    def test_inherited_resource_export_and_fail_closed_gates(self):
        parent,_=gen.pinned();base,_=parent.pinned(gen.REPO)
        raw=subprocess.check_output(['git','-C',str(gen.REPO),'show',
            base.PARENT+':verification/google_llm_vme_opt/test_lv.py']).decode()
        raw=raw.replace('HERE=Path(__file__).resolve().parent','HERE=Path('+repr(str(self.tools))+')')
        raw=raw.replace('repo=HERE.parent.parent','repo=Path('+repr(str(gen.REPO))+')')
        raw=raw.replace('llm_vme_opt_','llm_vme_pair_').replace('LLM_VME_OPT','LLM_VME_PAIR')
        raw=raw.replace("case_id=4,case='optimized_instruction_probe'","case_id=6,case='optimized_instruction_probe'")
        raw=raw.replace('probe_current_case=8,probe_step=6','probe_current_case=12,probe_step=6')
        raw=raw.replace('requested_cycles=5000000','requested_cycles=10000000')
        raw=raw.replace('spec.testcase(4)','spec.testcase(6)').replace('vm.checked_results(root,bundle,4)','vm.checked_results(root,bundle,6)')
        raw=raw.replace('vm.run_vm(prepared,4,100)','vm.run_vm(prepared,6,100)')
        raw=raw.replace('for index in (4,0,1,2,3)','for index in (6,0,1,2,3,4,5)')
        raw=raw.replace('for i in range(5) if spec.target(i)','for i in range(7) if spec.target(i)')
        raw=raw.replace('if index==4 else observation(index)','if index==6 else observation(index)')
        raw=raw.replace('Validated 1/4','Validated 1/6')
        raw=raw.replace("'optimized_core.h','vm_bench.py')}",
            "'optimized_core.h','vm_bench.py','hoisted_loop.h','qualified_core.h','pair_loop.h','pair_tile.h')}")
        # Fixtures remain explicitly synthetic. Add new REQUIRED counter fields
        # to valid fixtures, never relax the actual acceptance predicate.
        raw=raw.replace('def observation(index=0):','def original_observation(index=0):',1)
        raw+='''
def observation(index=0):
    row=original_observation(index);n=spec.CASES[index][3]
    for label in ('opt_complete','opt_reuse'):
        row[label+'_pair_groups']=4*(n//32)
        row[label+'_single_groups']=4*((n+15)//16-2*(n//32))
    return row
'''
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
import copy,importlib.util,unittest,sys
s=importlib.util.spec_from_file_location('inherited',%r);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
for index in range(6):
    row=m.observation(index);m.spec.accept(row,index)
    for label in ('opt_complete','opt_reuse'):
        for suffix in ('_pair_groups','_single_groups'):
            field=label+suffix;bad=copy.deepcopy(row);bad[field]+=1
            try:m.spec.accept(bad,index)
            except ValueError:pass
            else:raise AssertionError('Changed path count accepted: '+field)
            del bad[field]
            try:m.spec.accept(bad,index)
            except ValueError:pass
            else:raise AssertionError('Missing path count accepted: '+field)
row=m.probe_observation();m.spec.accept(row,6)
for field in ('probe_pair_groups','probe_single_groups'):
    bad=copy.deepcopy(row);bad[field]+=1
    try:m.spec.accept(bad,6)
    except ValueError:pass
    else:raise AssertionError('Changed probe count accepted: '+field)
suite=unittest.TestSuite(m.Checks(name) for name in %r)
result=unittest.TextTestRunner(verbosity=2).run(suite)
assert not result.skipped
sys.exit(0 if result.wasSuccessful() else 1)
''' % (str(harness),names))


if __name__=='__main__':unittest.main()
