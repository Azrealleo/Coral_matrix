#!/usr/bin/env bash
# VM build/export only. No RTL simulation and no model compilation.
set -euo pipefail
lv_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
lv_study=${1:-"$HOME/coral_tcm_capacity_8e4_v1"}
[[ $(uname -s) == Linux ]] || { echo 'Run on Ubuntu VM with coral-matrix.' >&2;exit 2; }
lv_study=$(cd -- "$lv_study" && pwd -P)
lv_source="$lv_study/source";lv_bazel="$lv_study/bazel-9.1.0"
printf '%s  %s\n' a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f "$lv_bazel" | sha256sum -c -
export PYTHONDONTWRITEBYTECODE=1
unset WAVES GUI COCOTB_ENABLE_PROFILING COCOTB_TESTCASE COCOTB_TEST_FILTER
python3 -B "$lv_here/prepare.py" --upstream "$lv_source"
lv_job=$(mktemp -d "$lv_study/llm_vme_export.XXXXXX")
printf '[LLM_VME_EXPORT_DIRECTORY] %s\n' "$lv_job"
cp -- "$lv_source/llm_vme_linear_v2_manifest.json" "$lv_job/source-manifest.json"
lv_startup=(--output_user_root="$lv_study/bazel-user" --host_jvm_args=-Xmx2g --noblock_for_lock)
lv_flags=(--noshow_progress --color=no --curses=no --jobs=2 --local_resources=memory=4096
    --lockfile_mode=error --repo_env=CORALNPU_MAKE_JOBS=2 --action_env=LANG=C.UTF-8 --action_env=LC_ALL=C.UTF-8)
lv_pkg=//tests/cocotb/llm_vme_linear_v2;lv_rtl=//tests/cocotb/llm_linear_v1:rtl_emit_verilog
cd -- "$lv_source"
printf '[LLM_VME_STAGE] Native packing/arithmetic reference only; hardware=NOT_RUN\n'
"$lv_bazel" "${lv_startup[@]}" test "${lv_flags[@]}" --cache_test_results=no --test_output=all \
    "$lv_pkg:host_reference_test" "$lv_pkg:host_packing_test" 2>&1 | tee "$lv_job/host.log"
printf '[LLM_VME_STAGE] Link one ELF and check existing RTL identity; NO RTL simulation/model build\n'
"$lv_bazel" "${lv_startup[@]}" build "${lv_flags[@]}" "$lv_pkg:probe_program.elf" "$lv_rtl" \
    2>&1 | tee "$lv_job/build.log"
"$lv_bazel" "${lv_startup[@]}" cquery "${lv_flags[@]}" --universe_scope="$lv_pkg:probe_program.elf" \
    --output=files "config($lv_pkg:probe_program.elf, target)" > "$lv_job/elf-outputs.txt" 2> "$lv_job/elf-query.log"
"$lv_bazel" "${lv_startup[@]}" cquery "${lv_flags[@]}" --output=files "$lv_rtl" \
    > "$lv_job/rtl-outputs.txt" 2> "$lv_job/rtl-query.log"
"$lv_bazel" "${lv_startup[@]}" info execution_root > "$lv_job/execution-root.txt" 2> "$lv_job/info.log"
python3 -B "$lv_here/lv_audit.py" --run "$lv_job"
python3 -B "$lv_here/export.py" --upstream "$lv_source" --job "$lv_job"
