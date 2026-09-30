#!/usr/bin/env bash
# Common logical-tile VCS diagnostics; standalone unit timing only.
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then
    printf 'Usage: bash %s REPOSITORY_ROOT [RUN_PARENT]\n' "$0" >&2
    exit 2
fi
model_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
model_repo_root=$(cd -- "$1" && pwd -P)
model_parent=${2:-/home2/lqq/Desktop/mxu_runs}
model_src="$model_repo_root/coralnpu-Yangg152/hdl/mxu"
command -v vcs >/dev/null
command -v python3 >/dev/null
command -v timeout >/dev/null
mkdir -p -- "$model_parent"
model_parent=$(cd -- "$model_parent" && pwd -P)
model_run_dir=$(mktemp -d "$model_parent/Yangg152_model_tile.XXXXXX")
printf '[YANGG_MODEL_TILE_RUN] directory=%s repo_revision=%s\n' "$model_run_dir" \
    "$(git -C "$model_repo_root" rev-parse HEAD)"
git -C "$model_repo_root" status --short
sha256sum "$model_src/Sram_256x128.v" "$model_src/rvv_backend_mxu_pe.sv" \
    "$model_src/rvv_backend_mxu_unit.sv" "$model_script_dir/mxu_boundary_tb.sv" \
    "$model_script_dir/mxu_model_perf_monitor.sv" \
    "$model_script_dir/generate_mxu_model_tile.py" \
    "$model_repo_root/coralnpu-google/tests/cocotb/vme_test/vme_matrix_model_tile_vectors.py"
python3 "$model_script_dir/generate_mxu_model_tile.py" "$model_run_dir/vectors" \
    > "$model_run_dir/vectors.log"
grep '^\[MODEL_TILE_MANIFEST\]' "$model_run_dir/vectors.log"
cd -- "$model_run_dir"
vcs -full64 -sverilog -timescale=1ns/1ps -top mxu_boundary_tb -o simv_model \
    -l compile.log "$model_src/Sram_256x128.v" "$model_src/rvv_backend_mxu_pe.sv" \
    "$model_src/rvv_backend_mxu_unit.sv" "$model_script_dir/mxu_boundary_tb.sv" \
    "$model_script_dir/mxu_model_perf_monitor.sv"

run_model_case() {
    local model_case=$1 model_m=$2 model_n=$3 model_k=$4 model_khw=$5 model_sha=$6
    local model_prev_perf= model_perf= model_field= model_repeat= model_tag= model_log= model_stdout=
    for model_repeat in 0 1 2; do
        model_tag="${model_case}_repeat${model_repeat}"
        model_log="$model_run_dir/$model_tag.run.log"
        model_stdout="$model_run_dir/$model_tag.stdout.log"
        printf '[YANGG_MODEL_TILE_CASE] case=%s repeat=%s K=%s K_hw=%s\n' \
            "$model_case" "$model_repeat" "$model_k" "$model_khw"
        if ! (cd -- "$model_run_dir/vectors/$model_case" &&
            timeout --kill-after=10s 120s "$model_run_dir/simv_model" \
                "+K=$model_khw" "+INPUT_GAPS=0" "+OUTPUT_STALL=0" \
                "+MODEL_M=$model_m" "+MODEL_N=$model_n" "+MODEL_K=$model_k" \
                -l "$model_log") > "$model_stdout" 2>&1; then
            printf '[YANGG_MODEL_TILE_FAIL] case=%s repeat=%s log=%s\n' \
                "$model_case" "$model_repeat" "$model_log" >&2
            return 1
        fi
        if ! grep -Fxq "[MXU_BOUNDARY_PASS] K=$model_khw input_gaps=0 output_stall=0" "$model_log" ||
           ! grep -Fxq "[MXU_BOUNDARY_RESULT] K=$model_khw input_gaps=0 output_stall=0 beats=64 pass=64 fail=0" "$model_log" ||
           grep -Eiq 'Error[: -]|Fatal[: -]|Warning[: -]|MXU_BOUNDARY_MISMATCH|MXU_BOUNDARY_TIMEOUT' "$model_log"; then
            printf '[YANGG_MODEL_TILE_FAIL] case=%s repeat=%s log=%s\n' \
                "$model_case" "$model_repeat" "$model_log" >&2
            return 1
        fi
        model_perf=$(grep '^\[MXU_MODEL_PERF\]' "$model_log" || true)
        if [[ -z "$model_perf" || "$model_perf" == *$'\n'* ]]; then
            printf '[YANGG_MODEL_TILE_FAIL] missing/duplicate perf row: %s\n' "$model_log" >&2
            return 1
        fi
        declare -A model_fields=()
        for model_field in $model_perf; do
            if [[ "$model_field" == *=* ]]; then
                model_fields["${model_field%%=*}"]="${model_field#*=}"
            fi
        done
        if [[ "${model_fields[M]:-}" != "$model_m" ||
              "${model_fields[N]:-}" != "$model_n" ||
              "${model_fields[K]:-}" != "$model_k" ||
              "${model_fields[K_hw]:-}" != "$model_khw" ||
              "${model_fields[output_beats]:-}" != 64 ||
              "${model_fields[mma_latency_cycles]:-}" != "$((model_khw + 3))" ||
              "${model_fields[useful_macs]:-}" != "$((model_m * model_n * model_k))" ||
              "${model_fields[physical_macs]:-}" != "$((256 * model_khw))" ||
              ! "${model_fields[input_to_output_span_cycles]:-}" =~ ^[0-9]+$ ||
              ! "${model_fields[readback_span_cycles]:-}" =~ ^[0-9]+$ ]]; then
            printf '[YANGG_MODEL_TILE_FAIL] malformed perf row: %s\n' "$model_log" >&2
            return 1
        fi
        if [[ -n "$model_prev_perf" && "$model_prev_perf" != "$model_perf" ]]; then
            printf '[YANGG_MODEL_TILE_FAIL] nondeterministic repeats: %s\n' "$model_case" >&2
            return 1
        fi
        model_prev_perf=$model_perf
        unset model_fields
    done
    printf '[YANGG_MODEL_TILE_SUMMARY] case=%s logical_sha256=%s repeats=3 %s\n' \
        "$model_case" "$model_sha" "${model_prev_perf#\[MXU_MODEL_PERF\] }"
}

model_cases_run=0
while read -r model_case model_m model_n model_k model_khw model_sha; do
    [[ "$model_case" =~ ^[a-z0-9_]+$ && "$model_m" =~ ^[0-9]+$ &&
       "$model_n" =~ ^[0-9]+$ && "$model_k" =~ ^[0-9]+$ &&
       "$model_khw" =~ ^[0-9]+$ && "$model_sha" =~ ^[0-9a-f]{64}$ ]] || exit 2
    run_model_case "$model_case" "$model_m" "$model_n" "$model_k" "$model_khw" "$model_sha"
    model_cases_run=$((model_cases_run + 1))
done < "$model_run_dir/vectors/cases.txt"
[[ "$model_cases_run" == 7 ]]
printf '[YANGG_MODEL_TILE_CHECK] cases=7 repeats=3 all_passed directory=%s\n' "$model_run_dir"
