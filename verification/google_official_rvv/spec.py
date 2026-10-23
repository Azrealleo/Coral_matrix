"""Existing official FP32 RVV operators: execution and math quality are separate."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import struct

UPSTREAM='8e4df09b4ea7e065e02d14ce3ae033d40dfd973a'
PACKAGE='tests/cocotb/official_rvv_v1'
PACKET_NAME='coral_official_rvv_i256_d512_v1'
TOP='VmeCoreMini_ITCM256KB_DTCM512KBAxi'
BASE_RTL_PACKAGE='tests/cocotb/llm_linear_v1'
RTL_SHA='477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2'
# Existing export/model-checker provenance; these helpers are NOT executed as VME kernels.
TILE_SHA='dd932fd04265528f979eba32d7fdb1403a05c5efeb6abe994177c2eaaa973c45'
REFERENCE_SHA='0dbdd0f29be48c78b90f0a6df970fcee050092441b5d218db2278a8b9b94b54f'
QUALIFIED_SHA='3d6753e12b348d8816ca377156233f9ce0b544c773ece8b4376e54b1b78d8d7e'
SCOPE='resident_FP32_scalar_project_RVV_vs_unmodified_official_RVV_diagnostic_not_model'
PROBE_SCOPE='official_RVV_residual_safety_probe_not_performance'
MARKER='[OFFICIAL_RVV_OBSERVATION] '
CASES=(('residual256','RESIDUAL',(256,0,0,0,0)),('rms64','RMS',(1,64,0,0,0)),
       ('rms_tail37','RMS',(3,37,0,0,0)),('gelu32','GEGLU',(32,0,0,0,0)),
       ('gelu_tail37','GEGLU',(37,0,0,0,0)),('gelu256','GEGLU',(256,0,0,0,0)))
PROBE_INDEX=6
PROBE_CASE=('safety_probe','RESIDUAL',(1,0,0,0,0))
ATOL=2e-5;RTOL=2e-4;CAPACITY=1024
GUARD=struct.pack('<I',0x55aa7711)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def testcase(index):return 'candidate_probe_test' if index==6 else 'candidate_'+CASES[index][0]+'_test'
def target(index):return '//'+PACKAGE+':opt_'+testcase(index)
def eta(index):return {6:'1-5 minutes',0:'2-8 minutes',1:'2-8 minutes',2:'3-10 minutes',3:'2-8 minutes',4:'2-8 minutes',5:'5-15 minutes'}[index]
def packed(values):return struct.pack('<'+'f'*len(values),*values)
def f32(value):return struct.unpack('<f',struct.pack('<f',value))[0]


def reference_path():
    local=Path(__file__).with_name('baseline_spec.py')
    path=local if local.is_file() else Path(__file__).parent.parent/'google_llm_ops/spec.py'
    if sha(path)!=REFERENCE_SHA:raise ValueError('Frozen export helper reference changed')
    return path


def fixture(index):
    path=Path(__file__).with_name('tx_reference.py')
    module_spec=importlib.util.spec_from_file_location('_official_reference',path)
    m=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(m)
    m.CASES=CASES+(PROBE_CASE,);data=m.fixture(index)
    algorithm=data['y'][:]
    if data['kind']=='GEGLU':
        algorithm=[]
        for x,up in zip(data['x'],data['w']):
            z=x*(f32(0.79788456)+f32(0.035677408)*x*x)
            t=max(-3.,min(3.,z));approx=t*(t*t+27.)/(9.*t*t+27.)
            algorithm.append(f32(0.5*x*up*(1.+approx)))
    data['algorithm']=algorithm
    data['algorithm_sha256']=hashlib.sha256(packed(algorithm)).hexdigest()
    return data


def signature(values):
    h=2166136261
    for b in packed(values):h=((h^b)*16777619)&0xffffffff
    return h


def checked_xml(tree,expected_name=None):
    tests=list(tree.iter('testcase'))
    if not tests or (expected_name and (len(tests)!=1 or tests[0].get('name')!=expected_name)):
        raise ValueError('Wrong/missing XML testcase')
    if any(list(tree.iter(t)) for t in ('failure','error','skipped')):raise ValueError('Failed/skipped XML testcase')
    for node in tree.iter():
        for k in ('failures','errors','skipped'):
            if node.get(k) is not None and int(node.get(k))!=0:raise ValueError('Nonzero XML failures')


def checked_host(text):
    rows=re.findall(r'^\[OFFICIAL_HOST\] id=(\d+) checked=(\d+) algorithms_ok=1 hardware=NOT_RUN$',text,re.M)
    if len(rows)!=7 or re.search(r'\bFAIL(?:ED)?\b',text):raise ValueError('Incomplete native algorithm reference')
    for i,(index,count) in enumerate(rows):
        if (int(index),int(count))!=(i,12*len(fixture(i)['y'])):raise ValueError('Wrong native case/signature')


def accept(row,index):
    data=fixture(index);probe=index==PROBE_INDEX
    expected=dict(schema=1,scope=PROBE_SCOPE if probe else SCOPE,case_id=index,case=data['name'],kind=data['kind'],
        shape=list(data['shape']),itcm_kib=256,dtcm_kib=512,rtl_sha256=RTL_SHA,
        vector_sha256=data['vector_sha256'],algorithm_sha256=data['algorithm_sha256'],
        atol=ATOL,rtol=RTOL,fault=False,natural_halt=True,firmware_status=3,
        checked_elements=12*len(data['y']),algorithm_mismatches=0,guard_ok=True,
        scalar_calls=4,project_calls=4,official_calls=4,input_readback_equal=True,
        mathematical_baselines_check=True,official_algorithm_output_check=True,
        stack_low_canary_intact=True,requested_cycles=10000000)
    wrong=[k for k,v in expected.items() if type(row.get(k)) is not type(v) or row[k]!=v]
    if wrong:raise ValueError('Incomplete/wrong official RVV execution: '+', '.join(wrong))
    if not re.fullmatch('[a-f0-9]{64}',row.get('elf_sha256','')):raise ValueError('Missing ELF identity')
    empty,total=row.get('empty_boundary_cycles'),row.get('observation_elapsed_cycles')
    if type(empty) is not int or empty<0 or type(total) is not int or not 0<total<=10000001:raise ValueError('Invalid cycle window')
    arrays=[row.get(k) for k in ('scalar_cycles','project_cycles','official_cycles')]
    if any(not isinstance(a,list) or len(a)!=4 or any(type(x) is not int or not empty<x<=total for x in a) for a in arrays):
        raise ValueError('Invalid four-sample cycles')
    if sum(map(sum,arrays))>total:raise ValueError('Kernel windows exceed observation')
    q=row.get('strict_math_quality_pass');miss=row.get('strict_math_quality_mismatches');err=row.get('official_max_math_abs_error')
    if type(q) is not bool or type(miss) is not int or not 0<=miss<=4*len(data['y']) or q!=(miss==0):raise ValueError('Missing/contradictory strict math quality')
    if type(err) not in (float,int) or not math.isfinite(err) or err<0:raise ValueError('Missing finite error measurement')
    if q and err>ATOL+RTOL*max(map(abs,data['y'])):raise ValueError('Error contradicts strict quality PASS')
    if not q and err<ATOL:raise ValueError('Error contradicts strict quality failure')
    ae=row.get('official_max_algorithm_abs_error')
    if type(ae) not in (float,int) or not math.isfinite(ae) or not 0<=ae<=ATOL+RTOL*max(map(abs,data['algorithm'])):
        raise ValueError('Missing/invalid independent algorithm error')
    # RMS/residual do not intentionally approximate transcendental functions.
    if data['kind']!='GEGLU' and not q:raise ValueError('Non-approximate official kernel fails strict math reference')
    if probe and row.get('probe_signature')!=signature(data['algorithm']):raise ValueError('Wrong safety probe signature')
    return dict(case_id=index,case=data['name'],scope=expected['scope'],full_model='NOT_RUN',VME='NOT_RUN',
        scalar_cycles=arrays[0],project_cycles=arrays[1],official_cycles=arrays[2],
        steady_scalar_over_official=sum(arrays[0][1:])/sum(arrays[2][1:]),
        steady_project_over_official=sum(arrays[1][1:])/sum(arrays[2][1:]),
        strict_math_quality_pass=q,official_max_math_abs_error=err,
        qualification='STRICT_MATH_PASS' if q else 'ALGORITHM_DIAGNOSTIC_ONLY_NOT_STRICT_MATH_QUALIFIED',
        approximation='official_clamped_rational_tanh' if data['kind']=='GEGLU' else 'none_intended')
