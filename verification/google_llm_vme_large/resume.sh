#!/usr/bin/env bash
set -euo pipefail
large_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if [[ $# != 2 ]];then echo 'Usage: resume.sh JOB_DIRECTORY quick|all|probe|0|1|2|3|4|5|6|7';exit 2;fi
large_job=$(cd -- "$1" && pwd -P)
large_mode=$2
case "$large_mode" in quick|all|probe|0|1|2|3|4|5|6|7) ;; *) exit 2;; esac
export PYTHONDONTWRITEBYTECODE=1
python3 -B "$large_here/materialize.py" --output "$large_job/tools" --existing
large_tools="$large_job/tools/verification/google_llm_vme_large_v1"
bash "$large_tools/run_vm.sh" "$large_job/prepared" "$large_mode"
if [[ "$large_mode" != probe ]];then
    python3 -u -B "$large_tools/summarize.py" --vm-prepared "$large_job/prepared" --partial
fi
python3 -B "$large_here/materialize.py" --output "$large_job/tools" --existing
