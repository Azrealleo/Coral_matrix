#!/usr/bin/env bash
# Preparation only; no RTL test is started here.
set -euo pipefail
chain_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
chain_study=${1:-"$HOME/coral_tcm_capacity_8e4_v1"}
chain_study=$(cd -- "$chain_study" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
chain_job=$(mktemp -d "$chain_study/transformer_chain.XXXXXX")
printf '[TRANSFORMER_CHAIN_JOB_DIRECTORY] %s\n' "$chain_job"
python3 -B "$chain_here/materialize.py" --output "$chain_job/tools"
bash "$chain_job/tools/verification/google_transformer_chain_v2/prepare_tomorrow.sh" "$chain_study" "$chain_job/prepared"
python3 -B "$chain_here/materialize.py" --output "$chain_job/tools" --existing
