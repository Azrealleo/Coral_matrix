#!/usr/bin/env bash
# Default is PREPARE ONLY. quick/all are explicit user-requested RTL plans.
set -euo pipefail
opt_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
opt_mode=${1:-prepare}
case "$opt_mode" in
  -h|--help) echo 'Usage: tomorrow.sh prepare|quick|all [STUDY_DIRECTORY]';exit 0;;
  prepare|quick|all) ;;
  *) echo 'Unknown mode; nothing built or simulated.' >&2;exit 2;;
esac
opt_study=${2:-"$HOME/coral_tcm_capacity_8e4_v1"}
if [[ "$opt_mode" == prepare ]]; then
    bash "$opt_here/prepare_tomorrow.sh" "$opt_study"
    exit 0
fi
[[ $(uname -s) == Linux ]] || { echo 'Use Ubuntu VM coral-matrix.' >&2;exit 2; }
opt_study=$(cd -- "$opt_study" && pwd -P)
opt_session=$(mktemp -d "$opt_study/llm_vme_opt_session.XXXXXX")
printf '[LLM_VME_OPT_SESSION_DIRECTORY] %s\n' "$opt_session"
printf '[LLM_VME_OPT_PLAN_ETA] quick roughly 15-35min; all roughly 45-100min, plus preparation; VM calibration pending\n'
bash "$opt_here/prepare_tomorrow.sh" "$opt_study" "$opt_session/prepared"
bash "$opt_here/run_vm.sh" "$opt_session/prepared" "$opt_mode"
if [[ "$opt_mode" == quick ]]; then
    python3 -u -B "$opt_here/summarize.py" --vm-prepared "$opt_session/prepared" --partial
else
    python3 -u -B "$opt_here/summarize.py" --vm-prepared "$opt_session/prepared"
fi
