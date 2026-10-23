#!/usr/bin/env bash
# Default builds only; quick/all explicitly request simulation.
set -euo pipefail
large_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
large_mode=${1:-prepare}
case "$large_mode" in prepare|quick|all) ;; *) echo 'Usage: run.sh prepare|quick|all [STUDY]';exit 2;; esac
[[ $(uname -s) == Linux ]] || { echo 'Use Ubuntu VM coral-matrix.' >&2;exit 2; }
large_study=${2:-"$HOME/coral_tcm_capacity_8e4_v1"}
large_study=$(cd -- "$large_study" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
large_job=$(mktemp -d "$large_study/llm_vme_large.XXXXXX")
printf '[LLM_VME_LARGE_JOB_DIRECTORY] %s\n' "$large_job"
python3 -B "$large_here/materialize.py" --output "$large_job/tools"
large_tools="$large_job/tools/verification/google_llm_vme_large_v1"
bash "$large_tools/prepare_tomorrow.sh" "$large_study" "$large_job/prepared"
[[ "$large_mode" != prepare ]] || exit 0
printf '[LLM_VME_LARGE_PLAN_ETA] quick roughly 20-60min; preparation excluded; larger cases need calibration before choosing VM/server\n'
bash "$large_tools/run_vm.sh" "$large_job/prepared" "$large_mode"
if [[ "$large_mode" == quick ]];then
    python3 -u -B "$large_tools/summarize.py" --vm-prepared "$large_job/prepared" --partial
else
    python3 -u -B "$large_tools/summarize.py" --vm-prepared "$large_job/prepared"
fi
python3 -B "$large_here/materialize.py" --output "$large_job/tools" --existing
