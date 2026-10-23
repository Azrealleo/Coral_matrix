#!/usr/bin/env bash
# Default prepare: no new RTL simulation while another experiment is running.
set -euo pipefail
pair_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
pair_mode=${1:-prepare}
case "$pair_mode" in prepare|quick|all) ;; *) echo 'Usage: run.sh prepare|quick|all [STUDY]';exit 2;; esac
[[ $(uname -s) == Linux ]] || { echo 'Use Ubuntu VM coral-matrix.' >&2;exit 2; }
pair_study=${2:-"$HOME/coral_tcm_capacity_8e4_v1"}
pair_study=$(cd -- "$pair_study" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
pair_job=$(mktemp -d "$pair_study/llm_vme_pair.XXXXXX")
printf '[LLM_VME_PAIR_JOB_DIRECTORY] %s\n' "$pair_job"
python3 -B "$pair_here/materialize.py" --output "$pair_job/tools"
pair_tools="$pair_job/tools/verification/google_llm_vme_pair_v1"
bash "$pair_tools/prepare_tomorrow.sh" "$pair_study" "$pair_job/prepared"
[[ "$pair_mode" != prepare ]] || exit 0
printf '[LLM_VME_PAIR_PLAN_ETA] quick 25-65min; all 80-180min; excludes preparation/first compilation; needs pair candidate calibration\n'
bash "$pair_tools/run_vm.sh" "$pair_job/prepared" "$pair_mode"
if [[ "$pair_mode" == quick ]];then
    python3 -u -B "$pair_tools/summarize.py" --vm-prepared "$pair_job/prepared" --partial
else
    python3 -u -B "$pair_tools/summarize.py" --vm-prepared "$pair_job/prepared"
fi
python3 -B "$pair_here/materialize.py" --output "$pair_job/tools" --existing
