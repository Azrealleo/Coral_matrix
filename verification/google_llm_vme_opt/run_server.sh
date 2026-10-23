#!/usr/bin/env bash
# Run from an exported immutable packet. Default checks only; NO build step.
set -euo pipefail
opt_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
opt_mode=${1:-check}
case "$opt_mode" in
  -h|--help) echo 'Usage: run_server.sh check|probe|quick|all|0|1|2|3 [CANDIDATE_PROBE_RUN]';exit 0;;
  check|probe|quick|all|0|1|2|3) ;;
  *) echo 'Unknown mode; nothing started.' >&2;exit 2;;
esac
unset WAVES GUI COCOTB_ENABLE_PROFILING COCOTB_TESTCASE COCOTB_TEST_FILTER
export PYTHONDONTWRITEBYTECODE=1
opt_rtl=${LLM_RTL_PACKAGE:-/data/home2/lqq/Desktop/coral_person_packages/pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1}
opt_original_probe=${LLM_ORIGINAL_PROBE:-"${opt_rtl}_verilator_runtime/runs/probe.46bl5uqr"}
opt_python=${LLM_PYTHON:-python}
opt_common=(--packet "$opt_here" --rtl-package "$opt_rtl")
"$opt_python" -u -B "$opt_here/server.py" "${opt_common[@]}" check --probe-run "$opt_original_probe"
[[ "$opt_mode" != check ]] || exit 0
if [[ "$opt_mode" =~ ^[0-3]$ && $# -ne 2 ]]; then echo 'Need the NEW candidate probe run as second argument.' >&2;exit 2;fi
mkdir -p -- "${opt_here}_runtime/console"
opt_console=$(mktemp -d "${opt_here}_runtime/console/plan.XXXXXX")
printf '[LLM_VME_OPT_CONSOLE_DIRECTORY] %s\n' "$opt_console"
if [[ "$opt_mode" == probe || "$opt_mode" == quick || "$opt_mode" == all ]]; then
    "$opt_python" -u -B "$opt_here/server.py" "${opt_common[@]}" run --probe-run "$opt_original_probe" --case 4 \
        2>&1 | tee "$opt_console/probe.log"
    [[ "$opt_mode" != probe ]] || exit 0
    opt_candidate_probe=$("$opt_python" -B -c 'import pathlib,re,sys; rows=re.findall(r"^\[LLM_VME_OPT_RUN_DIRECTORY\] (.+)$",pathlib.Path(sys.argv[1]).read_text(),re.M); assert len(rows)==1,"Ambiguous new probe"; print(rows[0])' "$opt_console/probe.log")
    if [[ "$opt_mode" == quick ]]; then opt_cases=(1);else opt_cases=(0 1 2 3);fi
else
    opt_candidate_probe=$2
    opt_cases=("$opt_mode")
fi
for opt_case in "${opt_cases[@]}"; do
    "$opt_python" -u -B "$opt_here/server.py" "${opt_common[@]}" run --probe-run "$opt_original_probe" \
        --opt-probe-run "$opt_candidate_probe" --case "$opt_case" 2>&1 | tee "$opt_console/case${opt_case}.log"
done
printf '[LLM_VME_OPT_SERVER_PLAN_PASS] plan=%s full_model=NOT_RUN\n' "$opt_mode"
