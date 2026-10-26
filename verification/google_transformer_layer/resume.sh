#!/usr/bin/env bash
set -euo pipefail
[[ $# -ge 1 && $# -le 2 ]] || { echo 'Usage: resume.sh JOB [quick|probe|0|1|2|all]';exit 2; }
attn_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
attn_job=$(cd -- "$1" && pwd -P);attn_plan=${2:-quick}
case "$attn_plan" in quick|probe|0|1|2|all) ;; *) exit 2;; esac
export PYTHONDONTWRITEBYTECODE=1
python3 -B "$attn_here/materialize.py" --output "$attn_job/tools" --existing
attn_tools="$attn_job/tools/verification/google_transformer_layer_v2"
printf '[LAYER_ETA] quick 3-9min; all 14-40min; excludes first build; rough uncalibrated\n'
bash "$attn_tools/run_vm.sh" "$attn_job/prepared" "$attn_plan"
if [[ "$attn_plan" != probe ]];then python3 -B "$attn_tools/summarize.py" --vm-prepared "$attn_job/prepared" --partial;fi
python3 -B "$attn_here/materialize.py" --output "$attn_job/tools" --existing
