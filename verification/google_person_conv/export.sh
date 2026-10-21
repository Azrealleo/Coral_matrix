#!/usr/bin/env bash
# Copy the measured small ELF and tools only; no Bazel or RTL compilation/run.
set -euo pipefail
pd_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
pd_run=${1:?Supply completed person_conv_v1 run}
pd_study=${2:-"$HOME/coral_tcm_capacity_8e4_v1"}
pd_run=$(cd -- "$pd_run" && pwd -P);pd_study=$(cd -- "$pd_study" && pwd -P)
pd_deps="$pd_study/person_conv_generator_deps_v1"
test -d "$pd_deps"
export PYTHONPATH="$pd_deps${PYTHONPATH:+:$PYTHONPATH}"
pd_job=$(mktemp -d "$pd_study/person_conv_export.XXXXXX")
printf '[PERSON_CONV_EXPORT_DIRECTORY] %s\n' "$pd_job"
python3 -B "$pd_here/export_conv.py" --upstream "$pd_study/source" \
    --assets "$pd_study/person_detect_b75c6ff4_assets" --run "$pd_run" --job "$pd_job"
