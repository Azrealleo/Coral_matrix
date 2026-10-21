#!/usr/bin/env bash
# Build/qualify only. NO RTL simulation and no background jobs.
set -euo pipefail
tx_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
tx_study=${1:-"$HOME/coral_tcm_capacity_8e4_v1"}
[[ $(uname -s) == Linux ]] || { echo 'Run on Ubuntu VM.' >&2;exit 2; }
tx_study=$(cd -- "$tx_study" && pwd -P)
tx_source="$tx_study/source";tx_bazel="$tx_study/bazel-9.1.0"
printf '%s  %s\n' a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f "$tx_bazel" | sha256sum -c -
unset WAVES GUI COCOTB_ENABLE_PROFILING COCOTB_TESTCASE COCOTB_TEST_FILTER
python3 -B "$tx_here/tx_prepare.py" --upstream "$tx_source"
tx_run=$(mktemp -d "$tx_study/llm_tx_prepare.XXXXXX")
printf '[LLM_TX_PREPARE_DIRECTORY] %s\n' "$tx_run"
cp -- "$tx_source/llm_transformer_v1_manifest.json" "$tx_run/manifest.json"
tx_startup=(--output_user_root="$tx_study/bazel-user" --host_jvm_args=-Xmx2g --noblock_for_lock)
tx_flags=(--noshow_progress --color=no --curses=no --jobs=2 --local_resources=memory=4096
    --lockfile_mode=error --repo_env=CORALNPU_MAKE_JOBS=2 --action_env=LANG=C.UTF-8 --action_env=LC_ALL=C.UTF-8)
tx_pkg=//tests/cocotb/llm_transformer_v1;tx_linear=//tests/cocotb/llm_linear_v1
cd -- "$tx_source"
printf '[LLM_TX_STAGE] Native scalar reference versus independent FP64 gold; RVV=NOT_RUN\n'
"$tx_bazel" "${tx_startup[@]}" test "${tx_flags[@]}" --cache_test_results=no --test_output=all \
    "$tx_pkg:host_reference_test" 2>&1 | tee "$tx_run/host.log"
printf '[LLM_TX_STAGE] Link FP32 firmware; reuse unchanged 256/512KiB linear model\n'
"$tx_bazel" "${tx_startup[@]}" build "${tx_flags[@]}" "$tx_pkg:probe_program.elf" \
    "$tx_linear:rtl_emit_verilog" "$tx_linear:model" 2>&1 | tee "$tx_run/build.log"
"$tx_bazel" "${tx_startup[@]}" cquery "${tx_flags[@]}" --universe_scope="$tx_pkg:probe_program.elf" \
    --output=files "config($tx_pkg:probe_program.elf, target)" > "$tx_run/elf-outputs.txt" 2> "$tx_run/elf-query.log"
"$tx_bazel" "${tx_startup[@]}" cquery "${tx_flags[@]}" --output=files "$tx_linear:rtl_emit_verilog" \
    > "$tx_run/rtl-outputs.txt" 2> "$tx_run/rtl-query.log"
"$tx_bazel" "${tx_startup[@]}" info execution_root > "$tx_run/execution-root.txt" 2> "$tx_run/info.log"
python3 -B "$tx_here/tx_audit.py" --run "$tx_run"
python3 -B "$tx_here/tx_prepare.py" --upstream "$tx_source"
printf '[LLM_TX_BUILD_READY] RTL=NOT_RUN results=%s\n' "$tx_run"
