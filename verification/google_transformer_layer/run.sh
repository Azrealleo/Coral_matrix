#!/usr/bin/env bash
set -euo pipefail
attn_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
attn_study=${1:-"$HOME/coral_tcm_capacity_8e4_v1"}
attn_study=$(cd -- "$attn_study" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
attn_job=$(mktemp -d "$attn_study/transformer_layer.XXXXXX")
printf '[LAYER_JOB_DIRECTORY] %s\n' "$attn_job"
python3 -B "$attn_here/materialize.py" --output "$attn_job/tools"
bash "$attn_job/tools/verification/google_transformer_layer_v2/prepare_tomorrow.sh" "$attn_study" "$attn_job/prepared"
python3 -B "$attn_here/materialize.py" --output "$attn_job/tools" --existing
