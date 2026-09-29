#!/usr/bin/env bash
# Diagnostics, not expected-pass signoff. RTL and original TB stay untouched.
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then
    printf 'Usage: bash %s REPOSITORY_ROOT [RUN_PARENT]\n' "$0" >&2
    exit 2
fi
boundary_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
boundary_repo_root=$(cd -- "$1" && pwd -P)
boundary_run_parent=${2:-/home2/lqq/Desktop/mxu_runs}
boundary_src="$boundary_repo_root/coralnpu-Yangg152/hdl/mxu"
command -v vcs >/dev/null
command -v python3 >/dev/null
command -v timeout >/dev/null
mkdir -p -- "$boundary_run_parent"
boundary_run_parent=$(cd -- "$boundary_run_parent" && pwd -P)
boundary_run_dir=$(mktemp -d "$boundary_run_parent/Yangg152_boundary.XXXXXX")
printf '[MXU_BOUNDARY_RUN] directory=%s repo_revision=%s\n' "$boundary_run_dir" \
    "$(git -C "$boundary_repo_root" rev-parse HEAD)"
git -C "$boundary_repo_root" status --short
sha256sum "$boundary_src/Sram_256x128.v" "$boundary_src/rvv_backend_mxu_pe.sv" \
    "$boundary_src/rvv_backend_mxu_unit.sv" "$boundary_script_dir/mxu_boundary_tb.sv" \
    "$boundary_script_dir/generate_mxu_boundary.py" \
    "$boundary_repo_root/coralnpu-google/tests/cocotb/vme_test/vme_matrix_boundary_vectors.py"
python3 "$boundary_script_dir/generate_mxu_boundary.py" "$boundary_run_dir/vectors" \
    > "$boundary_run_dir/vectors.log"
grep '^\[MXU_BOUNDARY_MANIFEST\]' "$boundary_run_dir/vectors.log"
cd -- "$boundary_run_dir"
vcs -full64 -sverilog -timescale=1ns/1ps -top mxu_boundary_tb -o simv_boundary \
    -l compile.log "$boundary_src/Sram_256x128.v" "$boundary_src/rvv_backend_mxu_pe.sv" \
    "$boundary_src/rvv_backend_mxu_unit.sv" "$boundary_script_dir/mxu_boundary_tb.sv"
boundary_pass=0
boundary_fail=0

run_boundary_case() {
    local boundary_case=$1 boundary_k=$2 boundary_gaps=$3 boundary_stall=$4
    local boundary_tag="K${boundary_k}_gaps${boundary_gaps}_stall${boundary_stall}"
    local boundary_log="$boundary_run_dir/$boundary_tag.run.log"
    # Status is checked explicitly: diagnostic failures do not silently pass,
    # but remaining cases are collected after healthy controls pass.
    if (cd -- "$boundary_run_dir/vectors/$boundary_case" &&
        timeout --kill-after=10s 120s "$boundary_run_dir/simv_boundary" \
            "+K=$boundary_k" "+INPUT_GAPS=$boundary_gaps" "+OUTPUT_STALL=$boundary_stall" \
            -l "$boundary_log") > "$boundary_run_dir/$boundary_tag.stdout.log" 2>&1; then
        if grep -Fxq "[MXU_BOUNDARY_PASS] K=$boundary_k input_gaps=$boundary_gaps output_stall=$boundary_stall" "$boundary_log" &&
           grep -Fxq "[MXU_BOUNDARY_RESULT] K=$boundary_k input_gaps=$boundary_gaps output_stall=$boundary_stall beats=64 pass=64 fail=0" "$boundary_log" &&
           ! grep -Eiq 'Error[: -]|Fatal[: -]|Warning[: -]|MXU_BOUNDARY_MISMATCH|MXU_OUTPUT_STALL_FAIL|MXU_BOUNDARY_TIMEOUT' "$boundary_log"; then
            boundary_pass=$((boundary_pass + 1))
            printf '[MXU_K_RUN] K=%s input_gaps=%s output_stall=%s status=PASS\n' "$boundary_k" "$boundary_gaps" "$boundary_stall"
            return 0
        fi
    fi
    boundary_fail=$((boundary_fail + 1))
    printf '[MXU_K_RUN] K=%s input_gaps=%s output_stall=%s status=FAIL log=%s\n' \
        "$boundary_k" "$boundary_gaps" "$boundary_stall" "$boundary_log"
    grep -E 'MXU_BOUNDARY_MISMATCH|MXU_OUTPUT_STALL_FAIL|MXU_BOUNDARY_TIMEOUT|MXU_BOUNDARY_RESULT|Error[: -]|Fatal[: -]|Warning[: -]' \
        "$boundary_run_dir/$boundary_tag.stdout.log" || true
    return 1
}

# Reproduce known-good aligned K values, then check the new gap-driving mode.
# Stop if either control fails: inspect driver/source/stall behavior first.
for boundary_k in 16 64 256; do
    for boundary_gaps in 0 1; do
        if ! run_boundary_case "boundary_k$boundary_k" "$boundary_k" "$boundary_gaps" 0; then
            printf '[MXU_BOUNDARY_CONTROL_FAIL] Stop: validate the new TB/source before interpreting tail diagnoses.\n' >&2
            printf '[MXU_BOUNDARY_LOGS] directory=%s\n' "$boundary_run_dir"
            exit 1
        fi
    done
done
while read -r boundary_case boundary_k; do
    [[ "$boundary_case" == "boundary_k$boundary_k" && "$boundary_k" =~ ^[0-9]+$ ]] || exit 2
    if [[ "$boundary_k" == 16 || "$boundary_k" == 64 || "$boundary_k" == 256 ]]; then continue; fi
    for boundary_gaps in 0 1; do
        if run_boundary_case "$boundary_case" "$boundary_k" "$boundary_gaps" 0; then :; else :; fi
    done
done < "$boundary_run_dir/vectors/cases.txt"
# Separate strict ready/valid output-stall diagnostic on a known-good K=16.
if run_boundary_case boundary_k16 16 0 1; then :; else :; fi
printf '[MXU_BOUNDARY_SUMMARY] runs=%s pass=%s fail=%s directory=%s\n' \
    "$((boundary_pass + boundary_fail))" "$boundary_pass" "$boundary_fail" "$boundary_run_dir"
[[ "$((boundary_pass + boundary_fail))" == 43 && "$boundary_fail" == 0 ]]
