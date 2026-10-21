#!/usr/bin/env bash
# Foreground Ubuntu pilot. No downloads of models, no background long queue.
set -euo pipefail
llm_case=${1:-0}
case "$llm_case" in
    0) llm_name=decode_tiny;; 1) llm_name=prefill_tiny;;
    2) llm_name=decode_small;; 3) llm_name=prefill_small;;
    *) echo 'case must be 0,1,2,3' >&2; exit 2;;
esac
llm_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
llm_study=${2:-"$HOME/coral_tcm_capacity_8e4_v1"}
[[ $(uname -s) == Linux ]] || { echo 'Run on Ubuntu VM with coral-matrix.' >&2; exit 2; }
llm_study=$(cd -- "$llm_study" && pwd -P)
llm_source="$llm_study/source";llm_bazel="$llm_study/bazel-9.1.0"
printf '%s  %s\n' a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f "$llm_bazel" | sha256sum -c -
unset WAVES GUI COCOTB_ENABLE_PROFILING COCOTB_TESTCASE COCOTB_TEST_FILTER
python3 -B "$llm_here/prepare.py" --upstream "$llm_source"
llm_run=$(mktemp -d "$llm_study/llm_linear_c${llm_case}.XXXXXX")
printf '[LLM_LINEAR_RUN_DIRECTORY] %s\n' "$llm_run"
cp -- "$llm_source/llm_linear_v1_manifest.json" "$llm_run/manifest.json"
llm_startup=(--output_user_root="$llm_study/bazel-user" --host_jvm_args=-Xmx2g --noblock_for_lock)
llm_flags=(--noshow_progress --color=no --curses=no --jobs=2 --local_resources=memory=4096
    --lockfile_mode=error --repo_env=CORALNPU_MAKE_JOBS=2 --action_env=LANG=C.UTF-8 --action_env=LC_ALL=C.UTF-8)
llm_pkg=//tests/cocotb/llm_linear_v1
cd -- "$llm_source"
printf '[LLM_LINEAR_STAGE] Native scalar vectors/reference ONLY, no RVV execution\n'
"$llm_bazel" "${llm_startup[@]}" test "${llm_flags[@]}" --cache_test_results=no --test_output=all \
    "$llm_pkg:host_reference_test" 2>&1 | tee "$llm_run/host.log"
printf '[LLM_LINEAR_STAGE] Build firmware and 256/512KiB RTL; first model compilation may take minutes\n'
"$llm_bazel" "${llm_startup[@]}" build "${llm_flags[@]}" \
    "$llm_pkg:probe_program.elf" "$llm_pkg:rtl_emit_verilog" 2>&1 | tee "$llm_run/build.log"
"$llm_bazel" "${llm_startup[@]}" cquery "${llm_flags[@]}" --universe_scope="$llm_pkg:probe_program.elf" \
    --output=files "config($llm_pkg:probe_program.elf, target)" > "$llm_run/elf-outputs.txt" 2> "$llm_run/elf-query.log"
"$llm_bazel" "${llm_startup[@]}" cquery "${llm_flags[@]}" --output=files "$llm_pkg:rtl_emit_verilog" \
    > "$llm_run/rtl-outputs.txt" 2> "$llm_run/rtl-query.log"
"$llm_bazel" "${llm_startup[@]}" info execution_root > "$llm_run/execution-root.txt" 2> "$llm_run/info.log"
python3 -B "$llm_here/audit.py" --run "$llm_run"
llm_test="$llm_pkg:linear_llm_${llm_name}_test"
printf '[LLM_LINEAR_STAGE] Foreground RTL case=%s only; wall test timeout 5400s is a limit, NOT an ETA\n' "$llm_name"
"$llm_bazel" "${llm_startup[@]}" test "${llm_flags[@]}" --cache_test_results=no --test_output=all \
    --test_timeout=5400 "$llm_test" 2>&1 | tee "$llm_run/test.log"
python3 -B "$llm_here/summarize.py" --run "$llm_run" --case "$llm_case"
python3 -B "$llm_here/prepare.py" --upstream "$llm_source"
printf '[LLM_LINEAR_PASS] case=%s full_model=NOT_RUN VME=NOT_RUN results=%s\n' "$llm_name" "$llm_run"
