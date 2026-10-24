"""Read-only revalidation and host error attribution; never runs new RTL."""
import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
ATOL, RTOL = 2e-5, 2e-4
SCOPE = 'host_numerical_attribution_not_new_RTL_not_model_accuracy'


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


CA, CB = f32(0.79788456), f32(0.035677408)


def stages(x, up):
    """FP64 isolation of formula changes, rounded at the output to FP32.

    This is NOT an instruction-accurate FP32/FMA emulator. The existing
    original RTL-to-independent-algorithm check remains the execution gate.
    The mathematical reference is the existing TANH-form GELU, not erf GELU.
    """
    if not math.isfinite(x) or not math.isfinite(up):
        raise ValueError('Non-finite input; finite bounded diagnostics only')
    z_reference = math.sqrt(2 / math.pi) * (x + 0.044715 * x**3)
    z_coefficients = x * (CA + CB * x*x)
    clipped = max(-3.0, min(3.0, z_coefficients))
    rational = clipped * (clipped*clipped + 27) / (9*clipped*clipped + 27)
    output = lambda t: f32(0.5 * x * up * (1 + t))
    return dict(reference=output(math.tanh(z_reference)),
                coefficients_only=output(math.tanh(z_coefficients)),
                clipped_true_tanh=output(math.tanh(clipped)),
                rational=output(rational), z=z_coefficients,
                clipping_active=abs(z_coefficients) > 3)


def errors(actual, reference):
    if not actual or len(actual) != len(reference):
        raise ValueError('Empty or inconsistent vector length')
    if not all(math.isfinite(x) for x in actual + reference):
        raise ValueError('Non-finite output')
    differences = [abs(a-b) for a, b in zip(actual, reference)]
    scaled = [d/(ATOL+RTOL*abs(r)) for d, r in zip(differences, reference)]
    worst = max(range(len(differences)), key=differences.__getitem__)
    return dict(elements=len(actual), failed_elements=sum(s > 1 for s in scaled),
                max_abs_error=max(differences), max_tolerance_multiple=max(scaled),
                rmse=math.sqrt(sum(d*d for d in differences)/len(differences)),
                worst_abs_index=worst)


def attribute_vectors(x, up, reference=None):
    if not x or len(x) != len(up):
        raise ValueError('Empty or inconsistent inputs')
    outputs = [stages(a, b) for a, b in zip(x, up)]
    gold = reference if reference is not None else [v['reference'] for v in outputs]
    vectors = {name: [v[name] for v in outputs] for name in
               ('reference', 'coefficients_only', 'clipped_true_tanh', 'rational')}
    if gold != vectors['reference']:
        raise ValueError('Existing frozen mathematical reference was not reproduced')
    metrics = {name: errors(vectors[name], gold) for name in
               ('coefficients_only', 'clipped_true_tanh', 'rational')}
    worst = metrics['rational']['worst_abs_index']
    return dict(elements=len(x), x_min=min(x), x_max=max(x),
                max_abs_up=max(map(abs, up)),
                max_abs_z=max(abs(v['z']) for v in outputs),
                clipped_elements=sum(v['clipping_active'] for v in outputs),
                metrics=metrics,
                coefficient_delta_max=metrics['coefficients_only']['max_abs_error'],
                clipping_increment_max=errors(vectors['clipped_true_tanh'],
                                              vectors['coefficients_only'])['max_abs_error'],
                rational_increment_max=errors(vectors['rational'],
                                               vectors['clipped_true_tanh'])['max_abs_error'],
                worst_absolute=dict(index=worst, x=x[worst], up=up[worst],
                                    reference=gold[worst],
                                    predicted_rational=vectors['rational'][worst]))


def check_observed(case, observation):
    """Cross-check attribution against already-revalidated RTL evidence."""
    predicted = case['metrics']['rational']
    if observation['strict_math_quality_mismatches'] != 4*predicted['failed_elements']:
        raise ValueError('Host attribution does not reproduce RTL quality failure count')
    delta = abs(observation['official_max_math_abs_error']-predicted['max_abs_error'])
    # Hardware arithmetic can differ from the independent FP64 formula mirror.
    # This compares maximum errors, NOT per-element execution correctness.
    # Per-element correctness is independently revalidated by collect_vm.
    allowance = observation['official_max_algorithm_abs_error'] + 2e-7
    if not math.isfinite(delta) or delta > allowance:
        raise ValueError('Attribution error exceeds revalidated RTL rounding allowance')
    case['rtl_math_max_abs_error'] = observation['official_max_math_abs_error']
    case['rtl_algorithm_max_abs_error'] = observation['official_max_algorithm_abs_error']
    case['rtl_failure_count_matches'] = True
    return case


def load_verified(job, repository=None):
    repository = repository or Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repository/'verification/google_official_rvv'))
    materialize = importlib.import_module('materialize')
    tools = materialize.verify(job/'tools')
    sys.path.insert(0, str(tools))
    summary = importlib.import_module('summarize')
    spec = importlib.import_module('lv_spec')
    # Reuses the SAME frozen probe, raw log/XML, exit status, SHA256,
    # packet, model, preparation and per-case proof checks. No new acceptance
    # bypass and no writes to the existing tools/packet/runs/summary.
    rows, _ = summary.collect_vm(job/'prepared', partial=False)
    return rows, spec


def build_report(job, repository=None):
    rows, spec = load_verified(job, repository)
    gelu = []
    for row in rows:
        index = row['case_id']
        if spec.CASES[index][1] != 'GEGLU':
            continue
        fixture = spec.fixture(index)
        detail = attribute_vectors(fixture['x'], fixture['w'], fixture['y'])
        detail.update(case=fixture['name'], vector_sha256=fixture['vector_sha256'])
        gelu.append(check_observed(detail, row['observation']))
    # Bounded host diagnostic only. This is NOT proof for arbitrary model
    # activations, all finite FP32 values, infinities, NaNs, or model accuracy.
    grid = [f32(i/512) for i in range(-4096, 4097)]
    dense = attribute_vectors(grid, [1.0]*len(grid))
    return dict(schema=1, scope=SCOPE, job=str(job), upstream=spec.UPSTREAM,
                elf_sha256=rows[0]['observation']['elf_sha256'], rtl_sha256=spec.RTL_SHA,
                atol=ATOL, rtol=RTOL, raw_evidence_revalidated=True,
                existing_RTL_runs=6, new_RTL_simulation='NOT_RUN', full_model='NOT_RUN',
                reference='existing_tanh_form_GELU_not_erf_GELU',
                formula_arithmetic='FP64_isolation_FP32_final_rounding_not_instruction_emulator',
                generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                source_evidence=[row['evidence'] for row in rows],
                observed_timings=[dict(case=r['observation']['case'],
                    execution_wall_seconds=r['observation']['execution_wall_seconds'],
                    command_wall_seconds=r['timing']['elapsed_seconds']) for r in rows],
                gelu_cases=gelu,
                bounded_host_grid=dict(x_range=[-8, 8], step=1/512, up=1,
                                       report=dense))


def markdown(report):
    lines = ['# Official RVV GELU error attribution', '',
             'Host numerical analysis of revalidated existing RTL evidence. No new RTL/model run.', '',
             '| Case | Failed elements / call | Max coefficient delta | Max clipping delta | Max rational delta | RTL max math error |',
             '|---|---:|---:|---:|---:|---:|']
    for row in report['gelu_cases']:
        lines.append(f"| {row['case']} | {row['metrics']['rational']['failed_elements']}/{row['elements']} | "
                     f"{row['coefficient_delta_max']:.9g} | {row['clipping_increment_max']:.9g} | "
                     f"{row['rational_increment_max']:.9g} | {row['rtl_math_max_abs_error']:.9g} |")
    lines += ['', 'Failure counts refer to synthetic tensor elements, NOT dataset classification accuracy.',
              'Reference is the existing tanh-form GELU, not exact erf-form GELU.',
              'Formula attribution is FP64 isolation with FP32 output rounding, not an RVV instruction emulator.',
              'The bounded host grid is not a new RTL result or proof for untested activations.', '',
              'Existing tools, packets, raw runs, summaries, source kernels and tolerances remain unchanged.']
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--repository', type=Path,
                        help='Repository providing the unchanged original verifier')
    parser.add_argument('--output', type=Path, required=True,
                        help='A NEW result directory outside the original job')
    args = parser.parse_args()
    job = args.job.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() or output == job or job in output.parents:
        raise ValueError('Output must be new and outside the accepted job')
    repository = args.repository.resolve(strict=True) if args.repository else None
    report = build_report(job, repository)
    output.mkdir()
    for name, content in (('attribution.json', json.dumps(report, indent=2, allow_nan=False)+'\n'),
                          ('attribution.md', markdown(report))):
        with (output/name).open('x', encoding='utf-8') as stream:
            stream.write(content)
    print(markdown(report))
    print('[OFFICIAL_RVV_HOST_ATTRIBUTION_PASS] new_RTL=NOT_RUN results='+str(output))


if __name__ == '__main__':
    main()
