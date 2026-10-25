#!/usr/bin/env bash
set -euo pipefail
[[ $# -ge 1 && $# -le 2 ]] || { echo 'Usage: resume.sh JOB [quick|probe|0|1|2|all]';exit 2; }
gelu_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
gelu_job=$(cd -- "$1" && pwd -P);gelu_plan=${2:-quick}
case "$gelu_plan" in quick|probe|0|1|2|all) ;; *) exit 2;; esac
export PYTHONDONTWRITEBYTECODE=1
python3 -B "$gelu_here/materialize.py" --output "$gelu_job/tools" --existing
gelu_tools="$gelu_job/tools/verification/google_gelu_rvv_mlas_v2"
printf '[GELU_RVV_MLAS_ETA] probe 0.5-2min; case0/1 1-4min; case2 2-5min; excludes build; estimate not timeout\n'
bash "$gelu_tools/run_vm.sh" "$gelu_job/prepared" "$gelu_plan"
if [[ "$gelu_plan" != probe ]];then python3 -B "$gelu_tools/summarize.py" --vm-prepared "$gelu_job/prepared" --partial;fi
python3 -B "$gelu_here/materialize.py" --output "$gelu_job/tools" --existing
