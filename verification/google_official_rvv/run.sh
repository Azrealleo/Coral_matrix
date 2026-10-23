#!/usr/bin/env bash
# Preparation only: no new RTL simulation, no background queue.
set -euo pipefail
rvv_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ $(uname -s) == Linux ]] || { echo 'Use Ubuntu coral-matrix.' >&2;exit 2; }
rvv_study=${1:-"$HOME/coral_tcm_capacity_8e4_v1"}
rvv_study=$(cd -- "$rvv_study" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
rvv_job=$(mktemp -d "$rvv_study/official_rvv.XXXXXX")
printf '[OFFICIAL_RVV_JOB_DIRECTORY] %s\n' "$rvv_job"
python3 -B "$rvv_here/materialize.py" --output "$rvv_job/tools"
bash "$rvv_job/tools/verification/google_official_rvv_v1/prepare_tomorrow.sh" "$rvv_study" "$rvv_job/prepared"
python3 -B "$rvv_here/materialize.py" --output "$rvv_job/tools" --existing
printf '[OFFICIAL_RVV_PREPARATION_FINISHED] simulation=NOT_RUN\n'
