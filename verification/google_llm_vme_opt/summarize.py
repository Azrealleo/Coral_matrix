"""Revalidate accepted runs and summarize; never treat preparation as RTL PASS."""
import argparse
import json
from pathlib import Path
import tempfile
import sys
sys.dont_write_bytecode=True
import lv_spec as spec
import lv_packet
import server


def collect_vm(prepared,partial):
    import vm
    prepared=Path(prepared).resolve(strict=True);record,packet,_,_=vm.checked_preparation(prepared)
    vm.checked_probe(prepared,record,packet)
    rows=[]
    for index in range(4):
        if not (prepared/vm.proof_name(index)).exists():
            if partial:continue
            raise ValueError('Missing accepted performance case '+str(index))
        proof=vm.checked_case(prepared,record,packet,index)
        observation,comparison,timing=vm.checked_results(Path(proof['directory']),packet,index)
        rows.append(dict(case_id=index,observation=observation,comparison=comparison,timing=timing,evidence=proof))
    if not rows:raise ValueError('Probe alone is NOT a performance summary')
    return rows,prepared


def collect_server(packet_root,probe,runs,partial):
    packet=lv_packet.load(packet_root);rows=[];seen=set();model=None
    for path in runs:
        path=Path(path).resolve(strict=True)
        saved=json.loads((path/'result.json').read_text());index=saved['observation']['case_id']
        if type(index) is not int or not 0<=index<4 or index in seen:raise ValueError('Wrong/duplicate server performance case')
        seen.add(index)
        observation,comparison,timing=server.checked_results(path,packet,index)
        build=json.loads((path/'producer-build-record.json').read_text())
        proof=server.checked_opt_probe(probe,packet,build)
        if json.loads((path/'candidate-probe-evidence.json').read_text())!=proof:raise ValueError('Server case used a different candidate probe')
        if model is not None and build!=model:raise ValueError('Mixed server model builds')
        model=build
        if saved['observation']!=observation or saved['comparison']!=comparison or saved['timing']!=timing:
            raise ValueError('Saved server result no longer matches raw evidence')
        for filename,key in (('_test.log','raw_log_sha256'),('results.xml','xml_sha256'),('_test-status.json','status_sha256')):
            if spec.sha(path/filename)!=saved[key]:raise ValueError('Server raw evidence changed')
        if saved['packet_manifest_sha256']!=spec.sha(packet.root/'manifest.json'):raise ValueError('Wrong sealed packet')
        rows.append(dict(case_id=index,observation=observation,comparison=comparison,timing=timing,evidence=dict(directory=str(path),candidate_probe=proof)))
    if not rows or (not partial and seen!=set(range(4))):raise ValueError('Need four distinct server cases, or explicitly --partial')
    return sorted(rows,key=lambda item:item['case_id']),Path(str(packet.root)+'_runtime')


def markdown(rows):
    lines=[f"Validated {len(rows)}/4 performance cases plus the candidate instruction probe. Full model: NOT RUN.",
        '', '| Case | RVV | Old VME complete | Old VME reuse | Candidate complete | Candidate reuse | RVV/candidate reuse |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for item in rows:
        row=item['observation'];mean=lambda name:sum(row[name][1:])/3
        lines.append('| '+row['case']+' | '+' | '.join(f'{mean(key):.2f}' for key in
            ('rvv_cycles','complete_cycles','reuse_cycles','opt_complete_cycles','opt_reuse_cycles'))+
            f" | {item['comparison']['steady_rvv_over_opt_reuse_excluding_prepack']:.4f} |")
    lines.extend(['','Cycle columns: mean of three steady samples, raw mcycle (empty boundary not subtracted).',
        'Reuse excludes one-time prepack. This is NOT cold-start speedup. First-use and four-call costs INCLUDING prepack are in summary.json.',
        'Ratios >1 favor the candidate; <1 favor RVV. No requirement that the candidate be faster to pass correctness.',
        'All comparisons use this same new ELF; do not splice old v2 or profiling cycles into these ratios.',
        'VM timing.elapsed_seconds includes Bazel overhead; server timing excludes compilation. Neither is an NPU speedup metric.'])
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--vm-prepared',type=Path);group.add_argument('--packet',type=Path)
    parser.add_argument('--probe-run',type=Path);parser.add_argument('--runs',type=Path,nargs='+')
    parser.add_argument('--partial',action='store_true');args=parser.parse_args()
    if args.vm_prepared:
        if args.probe_run or args.runs:parser.error('Do not mix VM and server evidence')
        rows,parent=collect_vm(args.vm_prepared,args.partial)
    else:
        if args.probe_run is None or not args.runs:parser.error('Server summary needs --probe-run and --runs')
        rows,parent=collect_server(args.packet,args.probe_run,args.runs,args.partial)
    parent.mkdir(exist_ok=True)
    directory=Path(tempfile.mkdtemp(prefix='summary.',dir=parent))
    record=dict(schema=1,scope=spec.SCOPE,validated_cases=len(rows),total_cases=4,full_model='NOT_RUN',rows=rows)
    with (directory/'summary.json').open('x',encoding='utf-8') as stream:json.dump(record,stream,indent=2)
    with (directory/'summary.md').open('x',encoding='utf-8') as stream:stream.write(markdown(rows))
    print(markdown(rows));print('[LLM_VME_OPT_SUMMARY_DIRECTORY] '+str(directory))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('[LLM_VME_OPT_SUMMARY_STOP] '+str(error),file=sys.stderr);sys.exit(1)
