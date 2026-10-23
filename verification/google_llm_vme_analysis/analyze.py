"""Read-only amortization analysis of fully revalidated pair-v2 VM results.

No kernel, immutable package, accepted proof or running experiment is modified.
No build/simulation is launched. All output goes to stdout.
"""
import argparse
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
SCOPE='resident_INT8_RVV_configure_once_single_VME_vs_paired_mt0_mt4_shared_input_not_model'


def series(values):
    if not isinstance(values,list) or len(values)!=4 or any(type(x) is not int or x<=0 for x in values):
        raise ValueError('Need four positive integer cycle samples, not a timing estimate')
    return values


def winning_range(first_advantage,steady_advantage):
    """Solve A+(R-1)*D > 0 exactly for positive integer R (ties do not win)."""
    if any(type(x) not in (int,Fraction) for x in (first_advantage,steady_advantage)):
        raise ValueError('Use exact integer/rational cycle differences')
    a,d=Fraction(first_advantage),Fraction(steady_advantage)
    if d>0:
        first=1 if a>0 else int((-a)//d)+2
        return dict(first=first,last=None,eventually_faster=True)
    if d==0:
        return dict(first=1,last=None,eventually_faster=True) if a>0 else None
    if a<=0:return None
    limit=a/(-d)
    last=-(-limit.numerator//limit.denominator)
    return dict(first=1,last=last,eventually_faster=False)


def amortization(rvv,reuse,prepack):
    rvv=series(rvv);reuse=series(reuse)
    if type(prepack) is not int or prepack<=0:raise ValueError('Need actual positive one-time prepack cycles')
    rsteady=Fraction(sum(rvv[1:]),3);vsteady=Fraction(sum(reuse[1:]),3)
    first=rvv[0]-prepack-reuse[0];steady=rsteady-vsteady
    observed=[]
    for count in range(1,5):
        r=sum(rvv[:count]);v=prepack+sum(reuse[:count])
        observed.append(dict(calls=count,rvv_cycles=r,vme_cycles_including_prepack=v,
            rvv_over_vme=r/v,winner='VME' if v<r else 'RVV' if r<v else 'tie'))
    fraction=lambda x:dict(numerator=x.numerator,denominator=x.denominator)
    return dict(one_time_prepack_cycles=prepack,observed_prefix_costs=observed,
        mean_steady_rvv_cycles=fraction(rsteady),mean_steady_vme_cycles=fraction(vsteady),
        steady_rvv_sample_range=[min(rvv[1:]),max(rvv[1:])],
        steady_vme_sample_range=[min(reuse[1:]),max(reuse[1:])],
        modeled_strict_vme_winning_call_range=winning_range(first,steady),
        modeled_worst_sample_winning_call_range=winning_range(first,min(rvv[1:])-max(reuse[1:])),
        modeled_best_sample_winning_call_range=winning_range(first,max(rvv[1:])-min(reuse[1:])),
        model_assumption='first sample then constant mean of three steady samples; prepack once',
        further_calls='MODEL_ONLY_NOT_ADDITIONAL_RTL_MEASUREMENTS')


def case_analysis(row):
    rvv=series(row['rvv_cycles']);old_full=series(row['complete_cycles']);new_full=series(row['opt_complete_cycles'])
    return dict(case=row['case'],case_id=row['case_id'],M=row['M'],K=row['K'],N=row['N'],
        single=amortization(rvv,row['reuse_cycles'],row['prepack_once_cycles']),
        paired=amortization(rvv,row['opt_reuse_cycles'],row['opt_prepack_once_cycles']),
        measured_complete_rvv_over_single=sum(rvv[1:])/sum(old_full[1:]),
        measured_complete_rvv_over_paired=sum(rvv[1:])/sum(new_full[1:]),
        complete_scope='each call includes its own prepack; not inferred by adding separate timing windows')


def verify_tools(job):
    path=HERE.parent/'google_llm_vme_pair/materialize.py'
    spec=importlib.util.spec_from_file_location('_pair_readonly_generator',path)
    generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
    tools=generator.verify(job/'tools')
    if tools.name!='google_llm_vme_pair_v2':raise ValueError('Only the sealed pair-v2 experiment is supported')
    return tools


def collect_verified(job):
    job=Path(job).resolve(strict=True);tools=verify_tools(job)
    # Refuse an interpreter polluted with another candidate's generic module
    # names. CLI invocation uses a fresh process, so this normally cannot occur.
    for name in ('lv_spec','lv_audit','lv_packet','vm','server','prepare'):
        if name in sys.modules:raise ValueError('Use a fresh Python process; already loaded '+name)
    sys.path.insert(0,str(tools))
    spec=importlib.util.spec_from_file_location('_pair_readonly_summary',tools/'summarize.py')
    summary=importlib.util.module_from_spec(spec);spec.loader.exec_module(summary)
    if summary.spec.SCOPE!=SCOPE or summary.spec.PACKAGE!='tests/cocotb/llm_vme_pair_v2':
        raise ValueError('Unexpected candidate scope/package')
    # Existing collector rechecks raw logs/XML/exit state, ELF/model/source
    # identity, guards/counters and probe proofs. It does not run main(), which
    # would create a summary directory. No Bazel command is invoked here.
    rows,prepared=summary.collect_vm(job/'prepared',partial=True)
    return rows,prepared


def report(job):
    rows,prepared=collect_verified(job)
    cases=[];elfs=set();seen=set()
    for item in rows:
        row=item['observation'];index=row['case_id']
        if row['scope']!=SCOPE or index in seen:raise ValueError('Mixed scope or duplicate accepted case')
        elfs.add(row['elf_sha256']);seen.add(index)
        case=case_analysis(row);case['raw_evidence']=item['evidence'];cases.append(case)
    if not cases or len(elfs)!=1:raise ValueError('Need accepted cases from one exact ELF')
    return dict(schema=1,scope='read_only_revalidated_pair_v2_amortization_not_model_runtime',
        prepared=str(prepared),elf_sha256=next(iter(elfs)),validated_cases=len(cases),total_cases=6,
        full_model='NOT_RUN',new_RTL_simulation='NOT_RUN',cases=cases,
        cautions=['Only measured M/K/N points; no universal dispatch threshold.',
                  'Inputs/weights resident in TCM; no real DRAM timing or full-model claim.',
                  'Observed prefixes use raw first+three steady kernel mcycle samples, not host time.',
                  'Modeled reuse counts assume stationary per-call cost, not further simulation.',
                  'Weight prepack is charged once using its measured counter; complete minus reuse is NOT prepack.',
                  'No instruction-cache cold-start or model invocation startup claim.'])


def range_text(value):
    if value is None:return 'none in model'
    return 'R >= '+str(value['first']) if value['last'] is None else '1 <= R <= '+str(value['last'])


def markdown(result):
    lines=[f"Revalidated {result['validated_cases']}/6 cases. No new simulation. Full model: NOT RUN.",
        'ELF: '+result['elf_sha256'],'',
        '| Case | Path | One-call cycles incl. prepack | Four-call cycles incl. prepack | RVV/four-call cost | Modeled strict winning R |',
        '|---|---|---:|---:|---:|---|']
    for case in result['cases']:
        for name in ('single','paired'):
            path=case[name];one=path['observed_prefix_costs'][0];four=path['observed_prefix_costs'][3]
            lines.append(f"| {case['case']} | {name} | {one['vme_cycles_including_prepack']} | "
                f"{four['vme_cycles_including_prepack']} | {four['rvv_over_vme']:.4f} | "
                f"{range_text(path['modeled_strict_vme_winning_call_range'])} |")
    lines+=['','R = calls sharing one weight prepack, not an M/N/K dimension.',
        'Model: RVV(R) = first_rvv + (R-1)*mean_steady_rvv;',
        'VME(R) = measured_prepack + first_reuse + (R-1)*mean_steady_reuse.',
        'One/four-call totals above are sums of measured windows; other R predictions are conditional estimates.']
    lines.extend(result['cautions'])
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True);parser.add_argument('--json',action='store_true')
    args=parser.parse_args();result=report(args.job)
    print(json.dumps(result,indent=2) if args.json else markdown(result))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('[LLM_VME_ANALYSIS_STOP] '+str(error),file=sys.stderr);sys.exit(1)
