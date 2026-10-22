#!/usr/bin/env bash
# VM build/export ONLY: no RTL simulator invocation or Verilator model build.
set -euo pipefail
llm_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
llm_study=${1:-"$HOME/coral_tcm_capacity_8e4_v1"}
[[ $(uname -s) == Linux ]] || { echo 'Run on Ubuntu VM with coral-matrix.' >&2; exit 2; }
llm_study=$(cd -- "$llm_study" && pwd -P)
llm_source="$llm_study/source";llm_bazel="$llm_study/bazel-9.1.0"
printf '%s  %s\n' a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f "$llm_bazel" | sha256sum -c -
unset WAVES GUI COCOTB_ENABLE_PROFILING COCOTB_TESTCASE COCOTB_TEST_FILTER
export PYTHONDONTWRITEBYTECODE=1
python3 -B "$llm_here/transformer/tx_prepare.py" --upstream "$llm_source"
llm_job=$(mktemp -d "$llm_study/llm_server_export.XXXXXX")
mkdir -- "$llm_job/int8" "$llm_job/fp32"
printf '[LLM_SERVER_EXPORT_DIRECTORY] %s\n' "$llm_job"
cp -- "$llm_source/llm_linear_v1_manifest.json" "$llm_job/int8/manifest.json"
cp -- "$llm_source/llm_transformer_v1_manifest.json" "$llm_job/fp32/manifest.json"
llm_startup=(--output_user_root="$llm_study/bazel-user" --host_jvm_args=-Xmx2g --noblock_for_lock)
llm_flags=(--noshow_progress --color=no --curses=no --jobs=2 --local_resources=memory=4096
    --lockfile_mode=error --repo_env=CORALNPU_MAKE_JOBS=2 --action_env=LANG=C.UTF-8 --action_env=LC_ALL=C.UTF-8)
llm_linear=//tests/cocotb/llm_linear_v1;llm_tx=//tests/cocotb/llm_transformer_v1
cd -- "$llm_source"
printf '[LLM_SERVER_EXPORT_STAGE] Native references only; NOT NPU/RVV simulation\n'
"$llm_bazel" "${llm_startup[@]}" test "${llm_flags[@]}" --cache_test_results=no --test_output=all \
    "$llm_linear:host_reference_test" 2>&1 | tee "$llm_job/int8/host.log"
"$llm_bazel" "${llm_startup[@]}" test "${llm_flags[@]}" --cache_test_results=no --test_output=all \
    "$llm_tx:host_reference_test" 2>&1 | tee "$llm_job/fp32/host.log"
printf '[LLM_SERVER_EXPORT_STAGE] Link two ELFs and emit/check RTL identity; NO model build or RTL simulation\n'
"$llm_bazel" "${llm_startup[@]}" build "${llm_flags[@]}" \
    "$llm_linear:probe_program.elf" "$llm_tx:probe_program.elf" "$llm_linear:rtl_emit_verilog" \
    2>&1 | tee "$llm_job/build.log"
"$llm_bazel" "${llm_startup[@]}" cquery "${llm_flags[@]}" --output=files "$llm_linear:rtl_emit_verilog" \
    > "$llm_job/rtl-outputs.txt" 2> "$llm_job/rtl-query.log"
"$llm_bazel" "${llm_startup[@]}" info execution_root > "$llm_job/execution-root.txt" 2> "$llm_job/info.log"
for llm_family in int8 fp32; do
    if [[ $llm_family == int8 ]]; then llm_pkg=$llm_linear; else llm_pkg=$llm_tx; fi
    cp -- "$llm_job/build.log" "$llm_job/rtl-outputs.txt" "$llm_job/execution-root.txt" "$llm_job/$llm_family/"
    "$llm_bazel" "${llm_startup[@]}" cquery "${llm_flags[@]}" --universe_scope="$llm_pkg:probe_program.elf" \
        --output=files "config($llm_pkg:probe_program.elf, target)" \
        > "$llm_job/$llm_family/elf-outputs.txt" 2> "$llm_job/$llm_family/elf-query.log"
done
python3 -B "$llm_here/audit.py" --run "$llm_job/int8"
python3 -B "$llm_here/transformer/tx_audit.py" --run "$llm_job/fp32"
python3 -B "$llm_here/server/export_packet.py" --upstream "$llm_source" --job "$llm_job"
