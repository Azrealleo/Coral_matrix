#!/usr/bin/env bash
set -euo pipefail
sweep_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if [[ $# != 2 ]];then echo 'Usage: resume.sh JOB_DIRECTORY quick|all|probe|0|1|2|3|4|5';exit 2;fi
sweep_job=$(cd -- "$1" && pwd -P)
sweep_mode=$2
case "$sweep_mode" in quick|all|probe|0|1|2|3|4|5) ;; *) exit 2;; esac
export PYTHONDONTWRITEBYTECODE=1
python3 -B "$sweep_here/materialize.py" --output "$sweep_job/tools" --existing
sweep_tools="$sweep_job/tools/verification/google_llm_vme_sweep_v1"
bash "$sweep_tools/run_vm.sh" "$sweep_job/prepared" "$sweep_mode"
if [[ "$sweep_mode" != probe ]];then
    python3 -u -B "$sweep_tools/summarize.py" --vm-prepared "$sweep_job/prepared" --partial
fi
python3 -B "$sweep_here/materialize.py" --output "$sweep_job/tools" --existing
