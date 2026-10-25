#!/usr/bin/env bash
# Build/export only. No RTL tests.
set -euo pipefail
ffn_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
ffn_study=${1:-"$HOME/coral_tcm_capacity_8e4_v1"}
ffn_study=$(cd -- "$ffn_study" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
ffn_job=$(mktemp -d "$ffn_study/ffn.XXXXXX")
printf '[FFN_JOB_DIRECTORY] %s\n' "$ffn_job"
python3 -B "$ffn_here/materialize.py" --output "$ffn_job/tools"
bash "$ffn_job/tools/verification/google_ffn_v1/prepare_tomorrow.sh" "$ffn_study" "$ffn_job/prepared"
python3 -B "$ffn_here/materialize.py" --output "$ffn_job/tools" --existing
