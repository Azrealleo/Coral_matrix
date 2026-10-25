#!/usr/bin/env bash
# Preparation only; never starts RTL tests.
set -euo pipefail
gelu_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
gelu_study=${1:-"$HOME/coral_tcm_capacity_8e4_v1"}
gelu_study=$(cd -- "$gelu_study" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
gelu_job=$(mktemp -d "$gelu_study/gelu_rvv_mlas.XXXXXX")
printf '[GELU_RVV_MLAS_JOB_DIRECTORY] %s\n' "$gelu_job"
python3 -B "$gelu_here/materialize.py" --output "$gelu_job/tools"
bash "$gelu_job/tools/verification/google_gelu_rvv_mlas_v2/prepare_tomorrow.sh" "$gelu_study" "$gelu_job/prepared"
python3 -B "$gelu_here/materialize.py" --output "$gelu_job/tools" --existing
