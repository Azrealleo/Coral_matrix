#!/usr/bin/env bash
# Run common signed arithmetic vectors using the unchanged mxu_tb/RTL.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    printf 'Usage: bash %s REPOSITORY_ROOT [RUN_PARENT]\n' "$0" >&2
    exit 2
fi
stress_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
stress_repo_root=$(cd -- "$1" && pwd -P)
stress_run_parent=${2:-/home2/lqq/Desktop/mxu_runs}
stress_src="$stress_repo_root/coralnpu-Yangg152/hdl/mxu"
command -v vcs >/dev/null
command -v python3 >/dev/null
command -v timeout >/dev/null
for stress_input in Sram_256x128.v rvv_backend_mxu_pe.sv rvv_backend_mxu_unit.sv mxu_tb.v; do
    test -r "$stress_src/$stress_input"
done
test -r "$stress_script_dir/generate_signed_stress.py"
mkdir -p -- "$stress_run_parent"
stress_run_parent=$(cd -- "$stress_run_parent" && pwd -P)
stress_run_dir=$(mktemp -d "$stress_run_parent/Yangg152_signed_stress.XXXXXX")
stress_revision=$(git -C "$stress_repo_root" rev-parse HEAD)
printf '[SIGNED_STRESS_RUN] directory=%s repo_revision=%s\n' "$stress_run_dir" "$stress_revision"
git -C "$stress_repo_root" status --short
sha256sum "$stress_src/Sram_256x128.v" "$stress_src/rvv_backend_mxu_pe.sv" \
    "$stress_src/rvv_backend_mxu_unit.sv" "$stress_src/mxu_tb.v" \
    "$stress_script_dir/generate_signed_stress.py" \
    "$stress_repo_root/coralnpu-google/tests/cocotb/vme_test/vme_matrix_stress_vectors.py"
python3 "$stress_script_dir/generate_signed_stress.py" "$stress_run_dir/vectors" \
    > "$stress_run_dir/vectors.log"
grep '^\[SIGNED_STRESS_MANIFEST\]' "$stress_run_dir/vectors.log"
cd -- "$stress_run_dir"
# No true-uint8 diagnostic or FSDB dependency. Reuse the original four cases.
vcs -full64 -sverilog -timescale=1ns/1ps -top mxu_tb -o simv_stress \
    -l compile.log "$stress_src/Sram_256x128.v" "$stress_src/rvv_backend_mxu_pe.sv" \
    "$stress_src/rvv_backend_mxu_unit.sv" "$stress_src/mxu_tb.v"
stress_batches_passed=0
while IFS= read -r stress_batch; do
    [[ "$stress_batch" =~ ^[a-z0-9_]+$ ]] || exit 2
    cd -- "$stress_run_dir/vectors/$stress_batch"
    timeout --kill-after=10s 120s "$stress_run_dir/simv_stress" -l "$stress_run_dir/$stress_batch.run.log" \
        > "$stress_run_dir/$stress_batch.stdout.log" 2>&1 || {
        printf 'Simulation failed: %s\n' "$stress_run_dir/$stress_batch.run.log" >&2
        tail -n 40 "$stress_run_dir/$stress_batch.stdout.log" >&2
        exit 1
    }
    grep -q '\*\*\* ALL TESTS PASSED \*\*\*' "$stress_run_dir/$stress_batch.run.log"
    grep -Eq '^[[:space:]]*PASS: 256[[:space:]]*$' "$stress_run_dir/$stress_batch.run.log"
    grep -Eq '^[[:space:]]*FAIL: 0[[:space:]]*$' "$stress_run_dir/$stress_batch.run.log"
    stress_rows=$(grep -Ec '^\[TEST[1-4]\] 64/64 passed, 0 failed$' \
        "$stress_run_dir/$stress_batch.run.log" || true)
    if [[ "$stress_rows" != 4 ]] || grep -Eiq '\[FAIL\]|SOME TESTS FAILED|Error[: -]|Fatal[: -]|Warning[: -]' \
        "$stress_run_dir/$stress_batch.run.log"; then
        printf 'Incomplete/failed/warning run: %s\n' "$stress_run_dir/$stress_batch.run.log" >&2
        exit 1
    fi
    stress_batches_passed=$((stress_batches_passed + 1))
    printf '[YANGG_SIGNED_STRESS] batch=%s cases=4 output_beats=256 checked_elements=1024 PASS\n' "$stress_batch"
done < "$stress_run_dir/vectors/batches.txt"
[[ "$stress_batches_passed" == 8 ]] || exit 1
printf '[YANGG_SIGNED_STRESS_CHECK] batches=8 cases=32 checked_elements=8192 passed\n'
printf '[SIGNED_STRESS_RUN] logs=%s manifest=%s/vectors/manifest.json\n' "$stress_run_dir" "$stress_run_dir"
