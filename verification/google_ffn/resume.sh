#!/usr/bin/env bash
set -euo pipefail
[[ $# -ge 1 && $# -le 2 ]] || { echo 'Usage: resume.sh JOB [quick|probe|0|1|2|all]';exit 2; }
ffn_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
ffn_job=$(cd -- "$1" && pwd -P);ffn_plan=${2:-quick}
case "$ffn_plan" in quick|probe|0|1|2|all) ;; *) exit 2;; esac
export PYTHONDONTWRITEBYTECODE=1
python3 -B "$ffn_here/materialize.py" --output "$ffn_job/tools" --existing
ffn_tools="$ffn_job/tools/verification/google_ffn_v1"
printf '[FFN_ETA] quick 1-5min; all 6-20min; excludes first build; rough uncalibrated\n'
bash "$ffn_tools/run_vm.sh" "$ffn_job/prepared" "$ffn_plan"
if [[ "$ffn_plan" != probe ]];then python3 -B "$ffn_tools/summarize.py" --vm-prepared "$ffn_job/prepared" --partial;fi
python3 -B "$ffn_here/materialize.py" --output "$ffn_job/tools" --existing
