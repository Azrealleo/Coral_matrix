#!/usr/bin/env bash
# Server: check the existing Pool model, then launch ONE validation image.
set -eo pipefail
pd_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
pd_package=${1:-"$HOME/Desktop/coral_person_packages/pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1"}
pd_probe=${2:-"${pd_package}_verilator_runtime/runs/probe.46bl5uqr"}
[[ $(uname -s) == Linux ]] || { echo 'Run on the laboratory server.' >&2;exit 2; }
pd_package=$(cd -- "$pd_package" && pwd -P)
pd_probe=$(cd -- "$pd_probe" && pwd -P)
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-verilator
unset WAVES GUI COCOTB_ENABLE_PROFILING
export CC="$CONDA_PREFIX/bin/gcc"
export CXX="$CONDA_PREFIX/bin/g++"
pd_python="$CONDA_PREFIX/bin/python"
pd_args=(--package "$pd_package" --probe-run "$pd_probe" --variant validate --case person
    --cycles 400000000 --timeout 172800)
"$pd_python" -B "$pd_here/model_runner.py" "${pd_args[@]}" check
pd_job=$(mktemp -d "$HOME/coral_vcs_tools/person_pool_full.XXXXXX")
nohup "$pd_python" -u -B "$pd_here/model_runner.py" "${pd_args[@]}" infer \
    > "$pd_job/console.log" 2>&1 < /dev/null &
pd_pid=$!
printf '%s\n' "$pd_pid" > "$pd_job/launcher.pid"
printf '[PERSON_POOL_FULL_JOB_DIRECTORY] %s\n' "$pd_job"
printf '[PERSON_POOL_FULL_PID] %s\n' "$pd_pid"
printf '[PERSON_POOL_FULL_CONSOLE_LOG] %s/console.log\n' "$pd_job"
printf 'Started background validation for ONE person image; not a speed benchmark.\n'
