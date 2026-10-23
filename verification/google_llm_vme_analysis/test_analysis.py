"""Pure arithmetic and mocked collection tests; NEVER RTL evidence."""
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import analyze as a


def arithmetic_fixture():
    # Reproduce published numbers for arithmetic regression only. This is NOT
    # an accepted run/proof, and the CLI never accepts fixtures or summary copies.
    return dict(scope=a.SCOPE,case='m16_k64_n64',case_id=5,M=16,K=64,N=64,
        rvv_cycles=[9141]*4,complete_cycles=[8051]*4,opt_complete_cycles=[7380]*4,
        reuse_cycles=[5563]*4,opt_reuse_cycles=[4887]*4,
        prepack_once_cycles=2442,opt_prepack_once_cycles=2443,elf_sha256='a'*64)


class AnalysisTests(unittest.TestCase):
    def test_exact_m16_arithmetic_without_promoting_fixture(self):
        result=a.case_analysis(arithmetic_fixture());new=result['paired'];old=result['single']
        self.assertEqual(new['observed_prefix_costs'][0]['vme_cycles_including_prepack'],7330)
        self.assertEqual(new['observed_prefix_costs'][3]['vme_cycles_including_prepack'],21991)
        self.assertEqual(old['observed_prefix_costs'][3]['vme_cycles_including_prepack'],24694)
        self.assertEqual(new['observed_prefix_costs'][3]['rvv_cycles'],36564)
        self.assertAlmostEqual(new['observed_prefix_costs'][3]['rvv_over_vme'],1.6626801873493702)
        self.assertEqual(new['modeled_strict_vme_winning_call_range']['first'],1)
        self.assertNotEqual(7380-4887,new['one_time_prepack_cycles'])

    def test_strict_integer_boundaries_and_non_eventual_win(self):
        self.assertEqual(a.winning_range(0,1),dict(first=2,last=None,eventually_faster=True))
        self.assertEqual(a.winning_range(-10,5),dict(first=4,last=None,eventually_faster=True))
        self.assertEqual(a.winning_range(-10,Fraction(4,3))['first'],9)
        self.assertEqual(a.winning_range(10,-5),dict(first=1,last=2,eventually_faster=False))
        self.assertEqual(a.winning_range(11,-5)['last'],3)
        self.assertIsNone(a.winning_range(0,0));self.assertIsNone(a.winning_range(-1,-1))
        self.assertEqual(a.winning_range(1,0)['first'],1)
        self.assertEqual(a.amortization([6872]*4,[5343]*4,2443)['modeled_strict_vme_winning_call_range']['first'],2)
        self.assertIsNone(a.amortization([4604]*4,[4767]*4,2443)['modeled_strict_vme_winning_call_range'])

    def test_measured_prefixes_are_not_mean_extrapolations(self):
        result=a.amortization([100,10,20,30],[50,8,9,10],1)
        self.assertEqual(result['observed_prefix_costs'][1]['rvv_cycles'],110)
        self.assertEqual(result['observed_prefix_costs'][1]['vme_cycles_including_prepack'],59)
        self.assertEqual(result['mean_steady_rvv_cycles'],dict(numerator=20,denominator=1))
        self.assertEqual(result['steady_vme_sample_range'],[8,10])

    def test_all_sign_cases_agree_with_integer_brute_force(self):
        for first in range(-20,21):
            for numerator in range(-12,13):
                delta=Fraction(numerator,3);result=a.winning_range(first,delta)
                for count in range(1,80):
                    predicted=result is not None and count>=result['first'] and (result['last'] is None or count<=result['last'])
                    self.assertEqual(predicted,first+(count-1)*delta>0,(first,delta,count))

    def test_invalid_cycle_values_never_look_like_measurements(self):
        for values in ([1]*3,[1]*5,[True]*4,[0]*4,[-1]*4,[1.2]*4,'1234'):
            with self.assertRaises(ValueError):a.amortization(values,[1]*4,1)
            with self.assertRaises(ValueError):a.amortization([1]*4,values,1)
        for pack in (0,-1,True,1.2):
            with self.assertRaises(ValueError):a.amortization([1]*4,[1]*4,pack)
        with self.assertRaises(ValueError):a.winning_range(1.1,2)

    def test_report_refuses_mixed_scopes_elfs_duplicates_and_probe_only(self):
        row=arithmetic_fixture();item=dict(observation=row,evidence={'fixture_only':True})
        with patch.object(a,'collect_verified',return_value=([item],Path('mock'))):
            result=a.report(Path('mock'));self.assertEqual(result['full_model'],'NOT_RUN')
            self.assertIn('No new simulation',a.markdown(result));json.dumps(result)
        for rows in ([],[item,item],
                     [item,dict(observation=dict(row,case_id=3,elf_sha256='b'*64),evidence={})],
                     [dict(observation=dict(row,scope='other candidate'),evidence={})]):
            with patch.object(a,'collect_verified',return_value=(rows,Path('mock'))):
                with self.assertRaises(ValueError):a.report(Path('mock'))

    def test_cli_has_no_skip_proof_or_simulation_option(self):
        for args in (['--help'],['--job','nonexistent'],['--job','nonexistent','--skip-validation']):
            result=subprocess.run([sys.executable,'-B',str(a.HERE/'analyze.py'),*args],capture_output=True,text=True)
            self.assertEqual(result.returncode==0,args==['--help'])
        text=(a.HERE/'analyze.py').read_text()
        self.assertNotIn('run_vm(',text);self.assertNotIn('prepare_vm(',text)

    def test_sealed_snapshot_is_verified_and_missing_run_stays_failure(self):
        generator=a.HERE.parent/'google_llm_vme_pair/materialize.py'
        spec=importlib.util.spec_from_file_location('_analysis_test_generator',generator)
        gen=importlib.util.module_from_spec(spec);spec.loader.exec_module(gen)
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);tools=gen.materialize(job/'tools')
            self.assertEqual(a.verify_tools(job),tools)
            before={p.relative_to(job).as_posix():p.read_bytes() for p in job.rglob('*') if p.is_file()}
            result=subprocess.run([sys.executable,'-B',str(a.HERE/'analyze.py'),'--job',str(job)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('LLM_VME_ANALYSIS_STOP',result.stderr)
            after={p.relative_to(job).as_posix():p.read_bytes() for p in job.rglob('*') if p.is_file()}
            self.assertEqual(before,after)
            path=tools/'pair_tile.h';path.write_bytes(path.read_bytes()+b'changed')
            with self.assertRaises(ValueError):a.verify_tools(job)


if __name__=='__main__':unittest.main()
