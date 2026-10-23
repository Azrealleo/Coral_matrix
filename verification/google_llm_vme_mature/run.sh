#!/usr/bin/env bash
# Prepare only by default. quick explicitly requests probe + M8 RTL simulation.
set -euo pipefail
mature_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
mature_mode=${1:-prepare}
case "$mature_mode" in prepare|quick|all) ;; *) echo 'Usage: run.sh prepare|quick|all [STUDY]';exit 2;; esac
[[ $(uname -s) == Linux ]] || { echo 'Use Ubuntu VM coral-matrix.' >&2;exit 2; }
mature_study=${2:-"$HOME/coral_tcm_capacity_8e4_v1"}
mature_study=$(cd -- "$mature_study" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
mature_job=$(mktemp -d "$mature_study/llm_vme_mature.XXXXXX")
printf '[LLM_VME_MATURE_JOB_DIRECTORY] %s\n' "$mature_job"
python3 -B "$mature_here/materialize.py" --output "$mature_job/tools"
mature_tools="$mature_job/tools/verification/google_llm_vme_mature_v1"
bash "$mature_tools/prepare_tomorrow.sh" "$mature_study" "$mature_job/prepared"
[[ "$mature_mode" != prepare ]] || exit 0
printf '[LLM_VME_MATURE_PLAN_ETA] quick 20-45min; all 80-180min; first preparation/model build excluded; estimates need this candidate calibration\n'
bash "$mature_tools/run_vm.sh" "$mature_job/prepared" "$mature_mode"
if [[ "$mature_mode" == quick ]];then
    python3 -u -B "$mature_tools/summarize.py" --vm-prepared "$mature_job/prepared" --partial
else
    python3 -u -B "$mature_tools/summarize.py" --vm-prepared "$mature_job/prepared"
fi
python3 -B "$mature_here/materialize.py" --output "$mature_job/tools" --existing
