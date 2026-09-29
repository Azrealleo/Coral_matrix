#!/usr/bin/env bash
# Profile the existing four passing cases without changing the RTL or mxu_tb.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    printf 'Usage: bash %s REPOSITORY_ROOT [RUN_PARENT]\n' "$0" >&2
    exit 2
fi

perf_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
perf_repo_root=$(cd -- "$1" && pwd -P)
perf_run_parent=${2:-/home2/lqq/Desktop/mxu_runs}
perf_src="$perf_repo_root/coralnpu-Yangg152/hdl/mxu"
perf_monitor="$perf_script_dir/mxu_perf_monitor.sv"

command -v vcs >/dev/null
command -v python3 >/dev/null
for perf_input in Sram_256x128.v rvv_backend_mxu_pe.sv rvv_backend_mxu_unit.sv mxu_tb.v golden.py; do
    if [[ ! -r "$perf_src/$perf_input" ]]; then
        printf 'Missing input: %s\n' "$perf_src/$perf_input" >&2
        exit 2
    fi
done
if [[ ! -r "$perf_monitor" ]]; then
    printf 'Keep mxu_perf_monitor.sv beside this script: %s\n' "$perf_monitor" >&2
    exit 2
fi

mkdir -p -- "$perf_run_parent"
perf_run_parent=$(cd -- "$perf_run_parent" && pwd -P)
# A fresh directory prevents stale simulation executables or data from passing.
perf_run_dir=$(mktemp -d "$perf_run_parent/Yangg152_perf.XXXXXX")
perf_repo_revision=$(git -C "$perf_repo_root" rev-parse HEAD)
printf '[MXU_PERF_RUN] directory=%s repo_revision=%s\n' "$perf_run_dir" "$perf_repo_revision"
git -C "$perf_repo_root" status --short
sha256sum "$perf_src/Sram_256x128.v" "$perf_src/rvv_backend_mxu_pe.sv" \
    "$perf_src/rvv_backend_mxu_unit.sv" "$perf_src/mxu_tb.v" \
    "$perf_src/golden.py" "$perf_monitor"

cd -- "$perf_run_dir"
python3 "$perf_src/golden.py"

# Intentionally do NOT define MXU_ENABLE_FSDB or MXU_TEST_TRUE_UNSIGNED.
# The former needs a Verdi PLI; the latter is a known failing diagnostic,
# excluded from this baseline while unsigned support is out of scope.
vcs -full64 -sverilog -timescale=1ns/1ps -top mxu_tb \
    -o simv_perf -l compile.log \
    "$perf_src/Sram_256x128.v" \
    "$perf_src/rvv_backend_mxu_pe.sv" \
    "$perf_src/rvv_backend_mxu_unit.sv" \
    "$perf_src/mxu_tb.v" \
    "$perf_monitor"

./simv_perf "+MXU_REPO_REV=$perf_repo_revision" -l run.log
printf '[MXU_PERF_RUN] logs=%s/{compile.log,run.log}\n' "$perf_run_dir"
grep -E 'MXU_PERF|\[TEST[1-4]\]|PASS:|FAIL:|ALL TESTS PASSED' run.log

# A successful simulator exit is not enough: require golden success and
# four complete measurements, with no probe warnings or incomplete frame.
grep -q '\*\*\* ALL TESTS PASSED \*\*\*' run.log
perf_rows=$(grep -c '^\[MXU_PERF\] ' run.log || true)
if [[ "$perf_rows" != 4 ]]; then
    printf 'Expected four complete performance rows; found %s. Do not rank this run.\n' "$perf_rows" >&2
    exit 1
fi
if grep -Eq 'MXU_PERF_INCOMPLETE|MXU_PERF: expected K\+3' run.log; then
    printf 'Probe completion/boundary check failed. Do not rank this run.\n' >&2
    exit 1
fi
