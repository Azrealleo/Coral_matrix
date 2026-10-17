#!/usr/bin/env bash
# Build portable source/firmware ONLY on the modern Ubuntu builder. No simulation.
set -euo pipefail
tcm_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
tcm_tools="$tcm_here/../google_tcm_capacity"
tcm_kib=${1:-1024}
tcm_study=${2:-"$HOME/coral_tcm_capacity_8e4_v1"}
case "$tcm_kib" in 1024|2048|4096) ;; *) echo 'Choose DTCM KiB 1024, 2048 or 4096' >&2; exit 2 ;; esac
[[ $(uname -s) == Linux ]] || { echo 'Run the export in native Linux.' >&2; exit 2; }
tcm_study=$(cd -- "$tcm_study" && pwd -P)
tcm_source="$tcm_study/source"
tcm_bazel="$tcm_study/bazel-9.1.0"
python3 -B "$tcm_tools/upgrade_workset_timeout.py" --upstream "$tcm_source"
python3 -B "$tcm_tools/prepare_workset.py" verify --upstream "$tcm_source"
printf '%s  %s\n' a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f "$tcm_bazel" | sha256sum -c -
tcm_job=$(mktemp -d "$tcm_study/vcs_export_d${tcm_kib}.XXXXXX")
printf '[TCM_VCS_EXPORT_JOB] %s\n' "$tcm_job"
cp -- "$tcm_here/export.sh" "$tcm_job/"
tcm_startup=(--output_user_root="$tcm_study/bazel-user" --host_jvm_args=-Xmx2g --noblock_for_lock)
tcm_flags=(--noshow_progress --jobs=2 --local_resources=memory=4096 --lockfile_mode=error
    --repo_env=CORALNPU_MAKE_JOBS=2 --action_env=LANG=C.UTF-8 --action_env=LC_ALL=C.UTF-8)
tcm_package="tests/cocotb/tcm_workset/d$tcm_kib"
cd -- "$tcm_source"
printf '%q ' "$tcm_bazel" "${tcm_startup[@]}" build "${tcm_flags[@]}" \
    "//$tcm_package:rtl_emit_verilog" //tests/cocotb/tcm_workset:workset_program.elf > "$tcm_job/build-command.txt"
printf '\n' >> "$tcm_job/build-command.txt"
printf '[TCM_VCS_STAGE] Building RTL/ZIP/parameters and firmware only, DTCM_KiB=%s\n' "$tcm_kib"
"$tcm_bazel" "${tcm_startup[@]}" build "${tcm_flags[@]}" \
    "//$tcm_package:rtl_emit_verilog" //tests/cocotb/tcm_workset:workset_program.elf 2>&1 | tee "$tcm_job/build.log"
"$tcm_bazel" "${tcm_startup[@]}" cquery "${tcm_flags[@]}" \
    --universe_scope=//tests/cocotb/tcm_workset:workset_program.elf \
    --output=files 'config(//tests/cocotb/tcm_workset:workset_program.elf, target)' \
    > "$tcm_job/elf-outputs.txt" 2> "$tcm_job/elf-query.log" || { cat "$tcm_job/elf-query.log" >&2; exit 1; }
"$tcm_bazel" "${tcm_startup[@]}" info execution_root \
    > "$tcm_job/execution-root.txt" 2> "$tcm_job/execution-root-query.log" || { cat "$tcm_job/execution-root-query.log" >&2; exit 1; }
tcm_elf=$(python3 -B "$tcm_tools/resolve_bazel_elf.py" --basename workset_program.elf \
    --execution-root-file "$tcm_job/execution-root.txt" --outputs-file "$tcm_job/elf-outputs.txt")
python3 -B "$tcm_here/export.py" --upstream "$tcm_source" --kib "$tcm_kib" --elf "$tcm_elf" \
    --job "$tcm_job" --output "$tcm_job/coral_tcm_vcs_d$tcm_kib"
