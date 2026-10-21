#!/usr/bin/env bash
# VM only: reuse byte-identical existing RTL; link a short hardware probe.
set -euo pipefail
pd_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
pd_run=${1:?Supply the completed person_vme_v1 run directory}
pd_baseline=${2:?Supply the original exported coral_person_i256_d512 directory}
pd_study=${3:-"$HOME/coral_tcm_capacity_8e4_v1"}
[[ $(uname -s) == Linux ]] || { echo 'Run on the Ubuntu VM.' >&2; exit 2; }
pd_run=$(cd -- "$pd_run" && pwd -P)
pd_baseline=$(cd -- "$pd_baseline" && pwd -P)
pd_study=$(cd -- "$pd_study" && pwd -P)
pd_source="$pd_study/source"
pd_bazel="$pd_study/bazel-9.1.0"
pd_args=(--upstream "$pd_source" --assets "$pd_study/person_detect_b75c6ff4_assets"
    --firmware-run "$pd_run" --baseline-package "$pd_baseline")
printf '%s  %s\n' a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f "$pd_bazel" | sha256sum -c -
python3 -B "$pd_here/export_bundle.py" prepare "${pd_args[@]}"
pd_job=$(mktemp -d "$pd_study/person_vme_export.XXXXXX")
printf '[PERSON_VME_EXPORT_DIRECTORY] %s\n' "$pd_job"
pd_startup=(--output_user_root="$pd_study/bazel-user" --host_jvm_args=-Xmx2g --noblock_for_lock)
pd_flags=(--noshow_progress --color=no --curses=no --jobs=2 --local_resources=memory=4096 --lockfile_mode=error
    --repo_env=CORALNPU_MAKE_JOBS=2 --action_env=LANG=C.UTF-8 --action_env=LC_ALL=C.UTF-8)
cd -- "$pd_source"
pd_target=//tests/cocotb/person_vme_probe_v1:probe_program.elf
printf '[PERSON_VME_EXPORT_STAGE] Link short VME probe; existing RTL/ELFs are only copied, NOT simulated\n'
"$pd_bazel" "${pd_startup[@]}" build "${pd_flags[@]}" "$pd_target" 2>&1 | tee "$pd_job/probe-build.log"
"$pd_bazel" "${pd_startup[@]}" cquery "${pd_flags[@]}" --universe_scope="$pd_target" \
    --output=files "config($pd_target, target)" > "$pd_job/probe-outputs.txt" 2> "$pd_job/query.log" \
    || { cat "$pd_job/query.log" >&2; exit 1; }
"$pd_bazel" "${pd_startup[@]}" info execution_root > "$pd_job/execution-root.txt" 2> "$pd_job/info.log"
python3 -B "$pd_here/export_bundle.py" export "${pd_args[@]}" --job "$pd_job"
