#!/usr/bin/env bash
set -euo pipefail
[[ $# -ge 1 && $# -le 2 ]] || { echo 'Usage: resume.sh JOB [quick|probe|0|1|2|all]';exit 2; }
chain_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
chain_job=$(cd -- "$1" && pwd -P);chain_plan=${2:-quick}
case "$chain_plan" in quick|probe|0|1|2|all) ;; *) exit 2;; esac
export PYTHONDONTWRITEBYTECODE=1
python3 -B "$chain_here/materialize.py" --output "$chain_job/tools" --existing
chain_tools="$chain_job/tools/verification/google_transformer_chain_v2"
printf '[TRANSFORMER_CHAIN_ETA] quick 1-5min; all 4-12min; excludes first build; rough uncalibrated\n'
bash "$chain_tools/run_vm.sh" "$chain_job/prepared" "$chain_plan"
if [[ "$chain_plan" != probe ]];then python3 -B "$chain_tools/summarize.py" --vm-prepared "$chain_job/prepared" --partial;fi
python3 -B "$chain_here/materialize.py" --output "$chain_job/tools" --existing
