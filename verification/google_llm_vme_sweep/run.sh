#!/usr/bin/env bash
# Independent sweep. Explicit quick/all are simulation requests; default prepare.
set -euo pipefail
sweep_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
sweep_mode=${1:-prepare}
case "$sweep_mode" in
  prepare|quick|all) ;;
  *) echo 'Usage: run.sh prepare|quick|all [STUDY]';exit 2;;
esac
[[ $(uname -s) == Linux ]] || { echo 'Use Ubuntu VM coral-matrix.' >&2;exit 2; }
sweep_study=${2:-"$HOME/coral_tcm_capacity_8e4_v1"}
sweep_study=$(cd -- "$sweep_study" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
sweep_job=$(mktemp -d "$sweep_study/llm_vme_m_sweep.XXXXXX")
printf '[LLM_VME_SWEEP_JOB_DIRECTORY] %s\n' "$sweep_job"
python3 -B "$sweep_here/materialize.py" --output "$sweep_job/tools"
sweep_tools="$sweep_job/tools/verification/google_llm_vme_sweep_v1"
bash "$sweep_tools/prepare_tomorrow.sh" "$sweep_study" "$sweep_job/prepared"
[[ "$sweep_mode" != prepare ]] || exit 0
printf '[LLM_VME_SWEEP_PLAN_ETA] quick: 20-45min; all: 80-180min, preparation excluded; each case roughly 5-45min\n'
bash "$sweep_tools/run_vm.sh" "$sweep_job/prepared" "$sweep_mode"
if [[ "$sweep_mode" == quick ]];then
    python3 -u -B "$sweep_tools/summarize.py" --vm-prepared "$sweep_job/prepared" --partial
else
    python3 -u -B "$sweep_tools/summarize.py" --vm-prepared "$sweep_job/prepared"
fi
python3 -B "$sweep_here/materialize.py" --output "$sweep_job/tools" --existing
