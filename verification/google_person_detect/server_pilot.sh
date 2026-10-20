#!/usr/bin/env bash
# Foreground server pilot for the exact VM export reported on 2026-10-20.
set -eo pipefail
pd_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
pd_archive=${1:-"$HOME/Desktop/coral_person_packages/coral_person_i256_d512.tar.gz"}
[[ $(uname -s) == Linux ]] || { echo 'Run on the laboratory Linux server.' >&2; exit 2; }
[[ -f "$pd_archive" ]] || { echo "Package not found: $pd_archive" >&2; exit 2; }
pd_archive=$(readlink -f -- "$pd_archive")
printf '%s  %s\n' a83bd98bd92157163223b75d74a25e5f426a59937354fb3784d830be4f130726 "$pd_archive" | sha256sum -c -
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-verilator
unset WAVES GUI COCOTB_ENABLE_PROFILING
export CC="$CONDA_PREFIX/bin/gcc"
export CXX="$CONDA_PREFIX/bin/g++"
pd_python="$CONDA_PREFIX/bin/python"
set -u
pd_unpack=$(mktemp -d "$(dirname -- "$pd_archive")/person_pilot.XXXXXX")
tar -xzf "$pd_archive" -C "$pd_unpack"
pd_package="$pd_unpack/coral_person_i256_d512"
pd_log="$pd_unpack/pilot-console.log"
printf '[PERSON_SERVER_PILOT_DIRECTORY] %s\n' "$pd_unpack"
printf '[PERSON_SERVER_CONSOLE_LOG] %s\n' "$pd_log"
(
    for pd_phase in verify check build; do
        printf '[PERSON_SERVER_STAGE] %s\n' "$pd_phase"
        "$pd_python" -B "$pd_here/person_runner.py" --package "$pd_package" "$pd_phase" --jobs 2 --timeout 1800
    done
    printf '[PERSON_SERVER_STAGE] bounded person-image observation; NOT a full-inference PASS claim\n'
    "$pd_python" -B "$pd_here/person_runner.py" --package "$pd_package" smoke \
        --case person --cycles 200000 --timeout 1800
    printf '[PERSON_SERVER_PILOT_FINISHED] package=%s\n' "$pd_package"
) 2>&1 | tee "$pd_log"
