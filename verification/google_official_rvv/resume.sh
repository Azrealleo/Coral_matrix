#!/usr/bin/env bash
set -euo pipefail
[[ $# -ge 1 && $# -le 2 ]] || { echo 'Usage: resume.sh JOB [quick|probe|0..5|all]';exit 2; }
rvv_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
rvv_job=$(cd -- "$1" && pwd -P);rvv_plan=${2:-quick}
case "$rvv_plan" in quick|probe|0|1|2|3|4|5|all) ;; *) exit 2;; esac
export PYTHONDONTWRITEBYTECODE=1
python3 -B "$rvv_here/materialize.py" --output "$rvv_job/tools" --existing
rvv_tools="$rvv_job/tools/verification/google_official_rvv_v1"
printf '[OFFICIAL_RVV_ETA] probe 1-5min; each small case 2-15min; quick 3-13min; excludes build; rough uncalibrated\n'
bash "$rvv_tools/run_vm.sh" "$rvv_job/prepared" "$rvv_plan"
if [[ "$rvv_plan" != probe ]];then
    python3 -B "$rvv_tools/summarize.py" --vm-prepared "$rvv_job/prepared" --partial
fi
python3 -B "$rvv_here/materialize.py" --output "$rvv_job/tools" --existing
