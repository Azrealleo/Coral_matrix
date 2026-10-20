#!/usr/bin/env bash
# Ubuntu generator only. Same measured ELF; no host test or RTL simulation rerun.
set -euo pipefail
pd_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
pd_firmware=${1:?Supply the completed person_firmware run directory}
pd_study=${2:-"$HOME/coral_tcm_capacity_8e4_v1"}
[[ $(uname -s) == Linux ]] || { echo 'Run on the Ubuntu builder.' >&2; exit 2; }
pd_study=$(cd -- "$pd_study" && pwd -P)
pd_firmware=$(cd -- "$pd_firmware" && pwd -P)
pd_source="$pd_study/source"
pd_bazel="$pd_study/bazel-9.1.0"
pd_assets="$pd_study/person_detect_b75c6ff4_assets"
printf '%s  %s\n' a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f "$pd_bazel" | sha256sum -c -
python3 -B "$pd_here/export_person.py" prepare --upstream "$pd_source" \
    --assets "$pd_assets" --firmware-run "$pd_firmware"
pd_job=$(mktemp -d "$pd_study/person_rtl_export.XXXXXX")
printf '[PERSON_RTL_EXPORT_DIRECTORY] %s\n' "$pd_job"
cp -- "$pd_here/export_rtl.sh" "$pd_job/"
pd_startup=(--output_user_root="$pd_study/bazel-user" --host_jvm_args=-Xmx2g --noblock_for_lock)
pd_flags=(--noshow_progress --color=no --curses=no --jobs=2 --local_resources=memory=4096
    --lockfile_mode=error --repo_env=CORALNPU_MAKE_JOBS=2
    --action_env=LANG=C.UTF-8 --action_env=LC_ALL=C.UTF-8)
pd_target=//tests/cocotb/person_detect_rtl_i256_d512:rtl_emit_verilog
cd -- "$pd_source"
printf '[PERSON_STAGE] Generate RTL only, ITCM256KiB / DTCM512KiB; simulation NOT_RUN\n'
printf '%q ' "$pd_bazel" "${pd_startup[@]}" build "${pd_flags[@]}" "$pd_target" > "$pd_job/build-command.txt"
printf '\n' >> "$pd_job/build-command.txt"
"$pd_bazel" "${pd_startup[@]}" build "${pd_flags[@]}" "$pd_target" 2>&1 | tee "$pd_job/build.log"
"$pd_bazel" "${pd_startup[@]}" cquery "${pd_flags[@]}" --output=files "$pd_target" \
    > "$pd_job/rtl-outputs.txt" 2> "$pd_job/rtl-query.log" \
    || { cat "$pd_job/rtl-query.log" >&2; exit 1; }
"$pd_bazel" "${pd_startup[@]}" info execution_root > "$pd_job/execution-root.txt" 2> "$pd_job/info.log" \
    || { cat "$pd_job/info.log" >&2; exit 1; }
python3 -B "$pd_here/export_person.py" export --upstream "$pd_source" \
    --assets "$pd_assets" --firmware-run "$pd_firmware" --job "$pd_job"
