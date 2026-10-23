#!/usr/bin/env bash
# ONLY native tests, firmware/resource export and BUILD of test executables.
# NO RTL test/run here. Safe to execute as preparation, not a simulation plan.
set -euo pipefail
opt_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
opt_study=${1:-"$HOME/coral_tcm_capacity_8e4_v1"}
[[ $(uname -s) == Linux ]] || { echo 'Use Ubuntu VM coral-matrix.' >&2;exit 2; }
opt_study=$(cd -- "$opt_study" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
unset WAVES GUI COCOTB_ENABLE_PROFILING COCOTB_TESTCASE COCOTB_TEST_FILTER
if [[ $# -ge 2 ]]; then
    opt_prepared=$2
    mkdir -- "$opt_prepared"
    opt_prepared=$(cd -- "$opt_prepared" && pwd -P)
else
    opt_prepared=$(mktemp -d "$opt_study/llm_vme_opt_tomorrow.XXXXXX")
fi
printf '[LLM_VME_OPT_TOMORROW_DIRECTORY] %s\n' "$opt_prepared"
bash "$opt_here/build_export.sh" "$opt_study" "$opt_prepared/firmware"
python3 -u -B "$opt_here/vm.py" prepare --prepared "$opt_prepared" --study "$opt_study" --source "$opt_study/source"
printf '[LLM_VME_OPT_READY_FOR_TOMORROW] simulation=NOT_RUN directory=%s\n' "$opt_prepared"
