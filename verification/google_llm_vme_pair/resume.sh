#!/usr/bin/env bash
set -euo pipefail
pair_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ $# -ge 1 && $# -le 2 ]] || { echo 'Usage: resume.sh JOB [probe|0..5|quick|all]';exit 2; }
pair_job=$(cd -- "$1" && pwd -P)
pair_mode=${2:-quick}
case "$pair_mode" in probe|0|1|2|3|4|5|quick|all) ;; *) echo 'Invalid plan';exit 2;; esac
export PYTHONDONTWRITEBYTECODE=1
python3 -B "$pair_here/materialize.py" --output "$pair_job/tools" --existing
pair_tools="$pair_job/tools/verification/google_llm_vme_pair_v2"
bash "$pair_tools/run_vm.sh" "$pair_job/prepared" "$pair_mode"
if [[ "$pair_mode" != probe ]];then
    python3 -u -B "$pair_tools/summarize.py" --vm-prepared "$pair_job/prepared" --partial
fi
python3 -B "$pair_here/materialize.py" --output "$pair_job/tools" --existing
