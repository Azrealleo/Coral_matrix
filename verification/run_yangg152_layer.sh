#!/usr/bin/env bash
# Signed-INT8 multi-tile / multi-pass diagnostics, no functional RTL changes.
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then
    printf 'Usage: bash %s REPOSITORY_ROOT [RUN_PARENT]\n' "$0" >&2
    exit 2
fi
layer_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
layer_repo_root=$(cd -- "$1" && pwd -P)
layer_parent=${2:-/home2/lqq/Desktop/mxu_runs}
layer_src="$layer_repo_root/coralnpu-Yangg152/hdl/mxu"
command -v vcs >/dev/null
command -v python3 >/dev/null
command -v timeout >/dev/null
mkdir -p -- "$layer_parent"
layer_parent=$(cd -- "$layer_parent" && pwd -P)
layer_run_dir=$(mktemp -d "$layer_parent/Yangg152_layer.XXXXXX")
printf '[YANGG_LAYER_RUN] directory=%s repo_revision=%s\n' "$layer_run_dir" \
    "$(git -C "$layer_repo_root" rev-parse HEAD)"
git -C "$layer_repo_root" status --short
sha256sum "$layer_src/Sram_256x128.v" "$layer_src/rvv_backend_mxu_pe.sv" \
    "$layer_src/rvv_backend_mxu_unit.sv" "$layer_script_dir/mxu_layer_tb.sv" \
    "$layer_script_dir/generate_mxu_layer.py" \
    "$layer_repo_root/coralnpu-google/tests/cocotb/vme_test/vme_matrix_layer_vectors.py"
python3 "$layer_script_dir/generate_mxu_layer.py" "$layer_run_dir/vectors" \
    > "$layer_run_dir/vectors.log"
grep '^\[MXU_LAYER_MANIFEST\]' "$layer_run_dir/vectors.log"
cd -- "$layer_run_dir"
vcs -full64 -sverilog -timescale=1ns/1ps -top mxu_layer_tb -o simv_layer \
    -l compile.log "$layer_src/Sram_256x128.v" "$layer_src/rvv_backend_mxu_pe.sv" \
    "$layer_src/rvv_backend_mxu_unit.sv" "$layer_script_dir/mxu_layer_tb.sv"

declare -A layer_total_cycles=() layer_total_mma=() layer_tiles=() layer_hash=()
layer_tile_count=0
while read -r layer_case layer_tile layer_k layer_passes layer_k0 layer_k1 layer_k2 layer_sha layer_useful; do
    [[ "$layer_case" =~ ^[a-z0-9_]+$ && "$layer_tile" =~ ^r[0-9]+_c[0-9]+$ &&
       "$layer_k" =~ ^[0-9]+$ && "$layer_passes" =~ ^[23]$ &&
       "$layer_k0" =~ ^[0-9]+$ && "$layer_k1" =~ ^[0-9]+$ &&
       "$layer_k2" =~ ^[0-9]+$ && "$layer_sha" =~ ^[0-9a-f]{64}$ &&
       "$layer_useful" =~ ^[0-9]+$ ]] || exit 2
    layer_tag="${layer_case}_${layer_tile}"
    layer_prev_row=
    for layer_repeat in 0 1 2; do
        layer_log="$layer_run_dir/${layer_tag}_repeat${layer_repeat}.run.log"
        layer_stdout="$layer_run_dir/${layer_tag}_repeat${layer_repeat}.stdout.log"
        printf '[YANGG_LAYER_TILE_RUN] case=%s tile=%s repeat=%s K=%s passes=%s\n' \
            "$layer_case" "$layer_tile" "$layer_repeat" "$layer_k" "$layer_passes"
        if ! (cd -- "$layer_run_dir/vectors/$layer_case/$layer_tile" &&
            timeout --kill-after=10s 120s "$layer_run_dir/simv_layer" \
                "+TILE=$layer_tile" "+PASSES=$layer_passes" \
                "+K0=$layer_k0" "+K1=$layer_k1" "+K2=$layer_k2" \
                -l "$layer_log") > "$layer_stdout" 2>&1; then
            printf '[YANGG_LAYER_FAIL] log=%s stdout=%s\n' "$layer_log" "$layer_stdout" >&2
            exit 1
        fi
        if ! grep -Fxq "[MXU_LAYER_PASS] tile=$layer_tile" "$layer_log" ||
           grep -Eiq 'Error[: -]|Fatal[: -]|Warning[: -]|MXU_LAYER_MISMATCH|MXU_LAYER_TIMEOUT' "$layer_log"; then
            printf '[YANGG_LAYER_FAIL] log=%s\n' "$layer_log" >&2
            exit 1
        fi
        layer_row=$(grep '^\[MXU_LAYER_RESULT\]' "$layer_log" || true)
        if [[ -z "$layer_row" || "$layer_row" == *$'\n'* ]]; then
            printf '[YANGG_LAYER_FAIL] missing/duplicate result: %s\n' "$layer_log" >&2
            exit 1
        fi
        declare -A layer_fields=()
        for layer_field in $layer_row; do
            if [[ "$layer_field" == *=* ]]; then
                layer_fields["${layer_field%%=*}"]="${layer_field#*=}"
            fi
        done
        layer_expected_mma=$((layer_k0 + layer_k1 + layer_k2 + 3 * layer_passes))
        if [[ "${layer_fields[tile]:-}" != "$layer_tile" ||
              "${layer_fields[passes]:-}" != "$layer_passes" ||
              "${layer_fields[beats]:-}" != 64 ||
              "${layer_fields[pass]:-}" != 64 ||
              "${layer_fields[fail]:-}" != 0 ||
              "${layer_fields[mma_sum_cycles]:-}" != "$layer_expected_mma" ||
              ! "${layer_fields[input_to_output_cycles]:-}" =~ ^[1-9][0-9]*$ ]]; then
            printf '[YANGG_LAYER_FAIL] malformed result: %s\n' "$layer_log" >&2
            exit 1
        fi
        unset layer_fields
        if [[ -n "$layer_prev_row" && "$layer_row" != "$layer_prev_row" ]]; then
            printf '[YANGG_LAYER_FAIL] nondeterministic tile: %s\n' "$layer_tag" >&2
            exit 1
        fi
        layer_prev_row=$layer_row
    done
    layer_tile_cycles=${layer_prev_row##*input_to_output_cycles=}
    printf '[YANGG_LAYER_TILE_SUMMARY] case=%s tile=%s K=%s passes=%s useful_macs=%s physical_macs=%s mma_sum_cycles=%s input_to_output_cycles=%s logical_sha256=%s\n' \
        "$layer_case" "$layer_tile" "$layer_k" "$layer_passes" "$layer_useful" \
        "$((256 * (layer_k0 + layer_k1 + layer_k2)))" "$layer_expected_mma" \
        "$layer_tile_cycles" "$layer_sha"
    layer_total_cycles[$layer_case]=$((${layer_total_cycles[$layer_case]:-0} + layer_tile_cycles))
    layer_total_mma[$layer_case]=$((${layer_total_mma[$layer_case]:-0} + layer_expected_mma))
    layer_tiles[$layer_case]=$((${layer_tiles[$layer_case]:-0} + 1))
    layer_hash[$layer_case]=$layer_sha
    layer_tile_count=$((layer_tile_count + 1))
done < "$layer_run_dir/vectors/tiles.txt"

[[ "$layer_tile_count" == 5 && "${layer_tiles[multi_tile_m20_n23_k272]:-}" == 4 &&
   "${layer_tiles[three_pass_m1_n10_k528]:-}" == 1 ]]
for layer_case in multi_tile_m20_n23_k272 three_pass_m1_n10_k528; do
    printf '[YANGG_LAYER_SUMMARY] case=%s tiles=%s repeats=3 sum_tile_input_to_output_cycles=%s sum_tile_mma_cycles=%s logical_sha256=%s scope=sequential_standalone_tile_runs_not_model_runtime\n' \
        "$layer_case" "${layer_tiles[$layer_case]}" "${layer_total_cycles[$layer_case]}" \
        "${layer_total_mma[$layer_case]}" "${layer_hash[$layer_case]}"
done
printf '[YANGG_LAYER_CHECK] cases=2 tiles=5 repeats=3 all_passed directory=%s\n' "$layer_run_dir"
