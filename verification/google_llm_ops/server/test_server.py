"""Synthetic tooling tests only; no simulator/NPU execution claims."""
import ast
import copy
from contextlib import nullcontext,redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace,ModuleType
import unittest
from unittest.mock import patch

import packet
import server_ops as runner

HERE=Path(__file__).resolve().parent
LINEAR=HERE.parent
TX=LINEAR/"transformer"


def helpers():
    # Load actual specs/audits with their normal filenames, no fake algorithms.
    l=packet.module("_test_linear",LINEAR/"spec.py");t=packet.module("_test_tx",TX/"tx_spec.py")
    with packet.isolated_modules(dict(spec=l,tx_spec=t)):
        la=packet.module("_test_la",LINEAR/"audit.py");ta=packet.module("_test_ta",TX/"tx_audit.py")
    return SimpleNamespace(linear=l,tx=t,linear_audit=la,tx_audit=ta)


def observation(h,family,index):
    common=dict(schema=1,itcm_kib=256,dtcm_kib=512,fault=False,natural_halt=True,firmware_status=3,
        mismatches=0,guard_ok=True,stack_low_canary_intact=True,input_readback_equal=True,rvv_calls=4,
        elf_sha256="a"*64,rtl_sha256=packet.RTL_SHA,scalar_cycles=[800]*4,rvv_cycles=[200]*4,
        empty_boundary_cycles=3,observation_elapsed_cycles=10000,requested_cycles=runner.budget(family,index))
    if family=="int8":
        s=h.linear;name,m,k,n=s.CASES[index];v=s.vectors(index)
        common.update(scope=s.SCOPE,case_id=index,case=name,M=m,K=k,N=n,checked_elements=4*m*n,
            signature=v["signature"],vector_sha256=v["vector_sha256"],samples=4,output_readback_equal=True)
    else:
        s=h.tx;v=s.fixture(index)
        common.update(scope=s.SCOPE,case_id=index,case=v["name"],kind=v["kind"],shape=v["shape"],
            checked_elements=4*len(v["y"]),vector_sha256=v["vector_sha256"],atol=s.ATOL,rtol=s.RTOL,
            independent_output_check=True,scalar_max_abs_error=0.0,rvv_max_abs_error=0.0)
    return common


def write_raw(directory,h,family,index):
    row=observation(h,family,index);s=h.linear if family=="int8" else h.tx
    (directory/"_test.log").write_text(s.MARKER+json.dumps(row)+"\x1b[39m\nTESTS=1 PASS=1 FAIL=0 SKIP=0\n")
    (directory/"results.xml").write_text('<testsuites><testsuite><testcase name="server_operator_test"/></testsuite></testsuites>')
    (directory/"_test-status.json").write_text(json.dumps(dict(exit_code=0,timed_out=False,elapsed_seconds=1.0)))
    return row


def bundle(root,h):
    return SimpleNamespace(root=root,helpers=h,manifest=dict(firmwares=dict(int8="a"*64,fp32="a"*64)))


def helper_mock():
    return packet.module("_test_qualified",LINEAR.parent/"google_person_pool/model_runner.py")


class Checks(unittest.TestCase):
    def setUp(self):self.h=helpers()

    def test_seal_inventory_includes_nested_manifest_and_detects_extra_or_changed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/"nested").mkdir();(root/"nested/manifest.json").write_text('{}')
            (root/"qualified_model.py").write_bytes((LINEAR.parent/"google_person_pool/model_runner.py").read_bytes())
            m=dict(schema=1,kind="llm_operator_firmware_packet_v1",upstream=packet.UPSTREAM,
                itcm_kib=256,dtcm_kib=512,rtl_sha256=packet.RTL_SHA,hdl_top=packet.TOP,simulation="NOT_RUN")
            sealed=packet.seal(root,m);self.assertIn("nested/manifest.json",sealed["files"])
            self.assertEqual(packet.verify(root),sealed)
            (root/"extra").write_text('x')
            with self.assertRaises(ValueError):packet.verify(root)

    def test_packet_does_not_accept_wrong_qualified_checker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/"qualified_model.py").write_text('changed')
            packet.seal(root,dict(schema=1,kind="llm_operator_firmware_packet_v1",upstream=packet.UPSTREAM,
                itcm_kib=256,dtcm_kib=512,rtl_sha256=packet.RTL_SHA,hdl_top=packet.TOP,simulation="NOT_RUN"))
            with self.assertRaisesRegex(ValueError,"checker"):packet.verify(root)

    def test_unsafe_names_rejected(self):
        for name in ('../outside','/absolute','C:/escape','a\\b',''):
            with self.subTest(name=name),self.assertRaises(ValueError):packet.safe_name(name)

    def test_isolated_imports_restore_old_person_spec_even_on_exception(self):
        sentinel=ModuleType('spec');sentinel.PERSON=True
        with patch.dict(sys.modules,spec=sentinel):
            with self.assertRaises(RuntimeError):
                with packet.isolated_modules(dict(spec=self.h.linear)):
                    self.assertIs(sys.modules['spec'],self.h.linear);raise RuntimeError()
            self.assertIs(sys.modules['spec'],sentinel)
            text=''.join(f'[TX_HOST_REFERENCE] id={i} name={c[0]} checked={4*len(self.h.tx.fixture(i)["y"])} errors=0 RVV=NOT_RUN\n'
                for i,c in enumerate(self.h.tx.CASES))
            packet.checked_host(self.h,'fp32',text)
            self.assertIs(sys.modules['spec'],sentinel)

    def test_ast_projection_preserves_exact_measured_function_and_removes_tests_only(self):
        for path,names,count in ((LINEAR/'linear_rtl_bench.py',{'runfile'},4),(TX/'tx_bench.py',{'locate'},17)):
            tree=ast.parse(path.read_text());projected=packet.projected_bench(path.read_text(),names)
            measured=lambda t:ast.dump(next(n for n in t.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='run_case'))
            self.assertEqual(measured(tree),measured(projected))
            self.assertEqual(sum(isinstance(n,ast.AsyncFunctionDef) for n in tree.body),count+1)
            self.assertEqual(sum(isinstance(n,ast.AsyncFunctionDef) for n in projected.body),1)
        with self.assertRaises(ValueError):packet.projected_bench('async def changed(dut,index): pass',{'locate'})

    def test_all_21_raw_results_accepted_and_slower_rvv_is_not_failure(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(runner,'helper',return_value=helper_mock()):
            root=Path(temporary);b=bundle(root,self.h)
            for family,index in runner.plan():
                directory=root/(family+str(index));directory.mkdir();write_raw(directory,self.h,family,index)
                self.assertEqual(runner.checked_results(directory,b,family,index)['case_id'],index)
            row=observation(self.h,'fp32',0);row['rvv_cycles']=[900]*4
            self.assertLess(self.h.tx.accept(row,0)['steady_scalar_over_rvv'],1)

    def test_results_reject_xml_failure_skip_timeout_identity_budget_and_duplicate(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(runner,'helper',return_value=helper_mock()):
            root=Path(temporary);b=bundle(root,self.h)
            for key,value in dict(elf_sha256='c'*64,rtl_sha256='c'*64,requested_cycles=1,
                observation_elapsed_cycles=10000002,fault=True,guard_ok=False).items():
                row=write_raw(root,self.h,'fp32',0);row[key]=value
                (root/'_test.log').write_text(self.h.tx.MARKER+json.dumps(row)+'\nTESTS=1 PASS=1 FAIL=0 SKIP=0')
                with self.subTest(key=key),self.assertRaises(ValueError):runner.checked_results(root,b,'fp32',0)
            for tag in ('failure','skipped','error'):
                write_raw(root,self.h,'fp32',0)
                (root/'results.xml').write_text(f'<testsuite><testcase name="server_operator_test"><{tag}/></testcase></testsuite>')
                with self.assertRaises(ValueError):runner.checked_results(root,b,'fp32',0)
            write_raw(root,self.h,'fp32',0)
            (root/'_test-status.json').write_text('{"exit_code":0,"timed_out":true}')
            with self.assertRaises(ValueError):runner.checked_results(root,b,'fp32',0)
            write_raw(root,self.h,'fp32',0);raw=(root/'_test.log').read_text();(root/'_test.log').write_text(raw*2)
            with self.assertRaises(ValueError):runner.checked_results(root,b,'fp32',0)

    def test_summary_partial_and_completed_evidence_tampering(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(runner,'helper',return_value=helper_mock()):
            root=Path(temporary);(root/'attempts').mkdir();(root/'completed').mkdir();b=bundle(root,self.h)
            first=runner.summarize(root,b,runner.plan());self.assertFalse(first['all_pass']);self.assertEqual(first['completed'],0)
            attempt=root/'attempts/int8_0.abc';attempt.mkdir();write_raw(attempt,self.h,'int8',0)
            result=runner.checked_results(attempt,b,'int8',0);(attempt/'result.json').write_text(json.dumps(result))
            (root/'completed/int8_0.json').write_text(json.dumps(dict(family='int8',case_id=0,attempt=attempt.name,
                result_sha256=packet.sha(attempt/'result.json'))))
            report=runner.summarize(root,b,runner.plan());self.assertEqual(report['completed'],1);self.assertFalse(report['all_pass'])
            self.assertTrue(runner.summarize(root,b,runner.plan('int8',0))['all_pass'])
            (attempt/'_test.log').write_text('corrupted')
            with self.assertRaises(ValueError):runner.evidence(root,'int8_0',b)

    def test_vm_script_never_builds_model_or_invokes_rtl_test(self):
        text=(LINEAR/'export_server.sh').read_text()
        self.assertNotIn(':model',text);self.assertNotIn('--test_timeout',text)
        for line in text.splitlines():
            if 'host_reference_test' in line:self.assertNotIn('workset',line)
        self.assertIn('"$llm_tx:probe_program.elf"',text)
        self.assertIn('server/export_packet.py',text)

    def test_all_new_python_sources_compile_and_cli_help_needs_no_simulator(self):
        for path in HERE.glob('*.py'):compile(path.read_text(),str(path),'exec')
        import subprocess
        result=subprocess.run([sys.executable,'-B',str(HERE/'server_ops.py'),'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('resume',result.stdout)

    def test_child_cleans_trace_and_only_runs_selected_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);b=bundle(root,self.h);rtl=SimpleNamespace(root=root/'old_model')
            def write(path,value):path.write_text(json.dumps(value))
            base=SimpleNamespace(write_json=write,child_environment=lambda *args:dict(WAVES='0',GUI='0',COCOTB_ENABLE_PROFILING='1'))
            process=SimpleNamespace(wait=lambda **kwargs:0)
            with patch.object(runner.subprocess,'Popen',return_value=process) as popen:
                runner.execute(b,rtl,{},base,root,root/'build','fp32',16,100)
            kwargs=popen.call_args.kwargs;env=kwargs['env']
            for key in ('WAVES','GUI','COCOTB_ENABLE_PROFILING'):self.assertNotIn(key,env)
            self.assertEqual(env['LLM_CASE'],'16');self.assertEqual(env['COCOTB_USE_FRONTDOOR'],'1')
            self.assertTrue(kwargs['start_new_session'])

    def test_canonical_resolvers_allowlist_files_with_unchanged_test_body(self):
        cocotb=ModuleType('cocotb');cocotb.test=lambda:lambda fn:fn
        triggers=ModuleType('cocotb.triggers')
        for n in ('ClockCycles','First','ReadOnly','RisingEdge'):setattr(triggers,n,object())
        utils=ModuleType('cocotb.utils');utils.get_sim_time=lambda **kwargs:0
        fixture=ModuleType('coralnpu_test_utils.sim_backends.verilator_test_fixture');fixture.VerilatorTestFixture=object()
        fake={'cocotb':cocotb,'cocotb.triggers':triggers,'cocotb.utils':utils,fixture.__name__:fixture}
        with tempfile.TemporaryDirectory() as temporary,patch.dict(sys.modules,fake):
            bench=packet.module('_test_server_bench',HERE/'server_bench.py');root=Path(temporary)
            (root/'linear').mkdir();(root/'transformer').mkdir();(root/'rtl').mkdir()
            for folder,name,source in (('linear','linear_rtl_bench.py',LINEAR),('transformer','tx_bench.py',TX)):
                (root/folder/name).write_bytes((source/name).read_bytes())
            for family in ('int8','fp32'):
                path=root/'firmware'/family;path.mkdir(parents=True);(path/'probe_program.elf').write_bytes(b'fake')
            (root/'parameters.h').write_text('fake');(root/'rtl'/(packet.TOP+'.sv')).write_text('fake')
            b=bundle(root,self.h)
            linear=bench.canonical(b,'int8',root);tx=bench.canonical(b,'fp32',root)
            self.assertEqual(linear.runfile('probe_program.elf'),root/'firmware/int8/probe_program.elf')
            self.assertEqual(tx.locate(self.h.tx.PACKAGE,'probe_program.elf'),root/'firmware/fp32/probe_program.elf')
            self.assertEqual(tx.locate(self.h.linear.PACKAGE,packet.TOP+'.sv'),root/'rtl'/(packet.TOP+'.sv'))
            with self.assertRaises(ValueError):tx.locate(self.h.tx.PACKAGE,packet.TOP+'.sv')
            with self.assertRaises(ValueError):linear.runfile('../arbitrary')

    def test_synthetic_export_packet_roundtrip_preserves_actual_input_bytes(self):
        import export_packet
        original_helpers=packet.helpers
        def audited(root):
            h=original_helpers(root)
            for family,audit in (('int8',h.linear_audit),('fp32',h.tx_audit)):
                audit.inspect=lambda raw:dict(elf_sha256=__import__('hashlib').sha256(raw).hexdigest(),NPU_RTL='NOT_RUN')
            return h
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);root=directory/'source';root.mkdir();job=directory/'job';job.mkdir()
            (root/'LICENSE').write_text('synthetic fixture, NOT RTL')
            # Use the exact parameter contract, no bypass of header checks.
            fields=dict(xlen='32',itcmSizeKBytes='256',dtcmSizeKBytes='512',axi2IdBits='6',rvvVlen='128',
                fetchDataBits='128',lsuDataBits='128',enableFetchL0='false',enableRvv='true',enableVme='true',
                enableFloat='true',enableZfbfmin='true',enableVectorBf16='true',enableAxiInstructionFetch='true',enableVerification='false')
            header=''.join('#define KP_'+n+' '+v+'\n' for n,v in fields.items())
            for family,source,names,marker in (
                ('int8',LINEAR,('spec.py','audit.py','linear_rtl_bench.py'),'llm_linear_v1_manifest.json'),
                ('fp32',TX,('tx_spec.py','tx_audit.py','tx_bench.py'),'llm_transformer_v1_manifest.json')):
                installed=root/family;installed.mkdir();run=job/family;run.mkdir();files={}
                for name in names:
                    path=installed/name;path.write_bytes((source/name).read_bytes());files[family+'/'+name]=packet.sha(path)
                manifest=dict(upstream=packet.UPSTREAM,files=files)
                for path in (root/marker,run/'manifest.json'):path.write_text(json.dumps(manifest))
                data=('synthetic '+family+' ELF; not linked').encode();(run/'probe_program.elf').write_bytes(data)
                report=dict(elf_sha256=__import__('hashlib').sha256(data).hexdigest(),NPU_RTL='NOT_RUN')
                (run/'resources.json').write_text(json.dumps(report));(run/'build.log').write_text('synthetic')
                identity=dict(rtl_sha256=packet.RTL_SHA,parameters=fields)
                if family=='int8':identity['top']=packet.TOP
                (run/'rtl-identity.json').write_text(json.dumps(identity))
                (run/'parameters.h').write_text(header)
                if family=='int8':
                    text=''.join(f'[LLM_LINEAR_HOST_REFERENCE] case={i} checked={4*c[1]*c[3]} signature={self.h.linear.vectors(i)["signature"]} RVV=NOT_RUN\n'
                        for i,c in enumerate(self.h.linear.CASES))
                else:
                    text=''.join(f'[TX_HOST_REFERENCE] id={i} name={c[0]} checked={4*len(self.h.tx.fixture(i)["y"])} errors=0 RVV=NOT_RUN\n'
                        for i,c in enumerate(self.h.tx.CASES))
                (run/'host.log').write_text(text)
            fake_prepare=SimpleNamespace(MANIFEST='llm_transformer_v1_manifest.json',prepare=lambda root:None)
            with patch.dict(sys.modules,tx_prepare=fake_prepare),patch.object(packet,'helpers',side_effect=audited),redirect_stdout(io.StringIO()):
                export_packet.export(root,job)
                exported=job/'coral_llm_ops_i256_d512_v1';loaded=packet.load(exported)
                self.assertEqual(loaded.manifest['simulation'],'NOT_RUN')
                self.assertEqual((exported/'firmware/fp32/probe_program.elf').read_bytes(),(job/'fp32/probe_program.elf').read_bytes())
                self.assertFalse((exported/'rtl').exists())
                self.assertTrue((job/'coral_llm_ops_i256_d512_v1.tar.gz').is_file())

    def test_synthetic_fail_stop_then_resume_skips_only_evidence_complete_case(self):
        with tempfile.TemporaryDirectory() as temporary,redirect_stdout(io.StringIO()):
            root=Path(temporary)/'packet';root.mkdir();(root/'manifest.json').write_text('{}')
            old=root.parent/'old';old.mkdir();(old/'manifest.json').write_text('{}')
            b=bundle(root,self.h);rtl=SimpleNamespace(root=old,manifest=dict(rtl_sha256=packet.RTL_SHA),
                library=SimpleNamespace(verify=lambda root:None))
            def write(path,value):path.write_text(json.dumps(value))
            base=SimpleNamespace(environment=lambda common:{},write_json=write)
            common=SimpleNamespace(state_lock=lambda path:nullcontext(),state_directory=lambda root:root)
            q=SimpleNamespace(load_runtime=lambda path:(None,base,common,rtl),checked_build=lambda *args:({},root/'model'),
                checked_probe=lambda *args:{},json_row=helper_mock().json_row)
            calls=[]
            def execute(bundle,rtl,env,base,directory,model,family,index,timeout):
                calls.append((family,index));write_raw(directory,self.h,family,index)
            argv=['server_ops.py','--packet',str(root),'--rtl-package',str(old),'all','--probe-run',str(old)]
            with patch.object(runner,'HERE',root),patch.object(packet,'load',return_value=b),patch.object(runner,'helper',return_value=q):
                def fail_second(*args):
                    if len(calls)==1:raise ValueError('synthetic interruption')
                    execute(*args)
                with patch.object(runner,'execute',side_effect=fail_second),patch.object(sys,'argv',argv):
                    with self.assertRaisesRegex(ValueError,'synthetic interruption'):runner.main()
                jobs=Path(str(root)+'_server_runtime')/'jobs';job=next(jobs.iterdir())
                self.assertEqual(len(list((job/'completed').iterdir())),1)
                resume=argv.copy();resume[5]='resume';resume.extend(['--job',str(job)])
                with patch.object(runner,'execute',side_effect=execute),patch.object(sys,'argv',resume):runner.main()
                self.assertEqual(calls,[tuple(x) for x in runner.plan()])
                report=json.loads((job/'summary.json').read_text());self.assertTrue(report['all_pass']);self.assertEqual(report['completed'],21)


if __name__=='__main__':unittest.main()
