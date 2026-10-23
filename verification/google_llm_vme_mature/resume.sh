#!/usr/bin/env bash
# No rebuilding/replacing the tool preparation when resuming an existing job.
set -euo pipefail
mature_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ $# -ge 1 && $# -le 2 ]] || { echo 'Usage: resume.sh JOB [probe|0..5|quick|all]';exit 2; }
mature_job=$(cd -- "$1" && pwd -P)
mature_mode=${2:-quick}
case "$mature_mode" in probe|0|1|2|3|4|5|quick|all) ;; *) echo 'Invalid plan';exit 2;; esac
export PYTHONDONTWRITEBYTECODE=1
python3 -B "$mature_here/materialize.py" --output "$mature_job/tools" --existing
mature_tools="$mature_job/tools/verification/google_llm_vme_mature_v1"
bash "$mature_tools/run_vm.sh" "$mature_job/prepared" "$mature_mode"
if [[ "$mature_mode" != probe ]];then
    python3 -u -B "$mature_tools/summarize.py" --vm-prepared "$mature_job/prepared" --partial
fi
python3 -B "$mature_here/materialize.py" --output "$mature_job/tools" --existing
