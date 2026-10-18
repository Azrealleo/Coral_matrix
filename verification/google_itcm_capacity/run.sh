#!/usr/bin/env bash
# ONE ITCM geometry test. Reuse the fixed source/cache without altering old files.
set -euo pipefail
itcm_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
itcm_kib=${1:-8}
itcm_study=${2:-"$HOME/coral_tcm_capacity_8e4_v1"}
case "$itcm_kib" in 8|16|32|64|128) ;; *) echo 'ITCM KiB must be 8/16/32/64/128' >&2; exit 2 ;; esac
[[ $(uname -s) == Linux ]] || { echo 'Run in the Ubuntu VM.' >&2; exit 2; }
command -v flock >/dev/null
itcm_study=$(cd -- "$itcm_study" && pwd -P)
itcm_source="$itcm_study/source"
itcm_bazel="$itcm_study/bazel-9.1.0"
[[ -f "$itcm_source/tcm_capacity_manifest.json" ]] || { echo 'Existing DTCM study required.' >&2; exit 2; }
exec 9>"$itcm_study/itcm_geometry.lock"
flock -n 9 || { echo 'Another ITCM task is running; nothing changed.' >&2; exit 2; }
itcm_run=$(mktemp -d "$itcm_study/itcm_geometry_i${itcm_kib}.XXXXXX")
printf '[ITCM_RUN_DIRECTORY] %s\n' "$itcm_run"
python3 -B "$itcm_here/prepare_itcm.py" prepare --upstream "$itcm_source"
cp "$itcm_source/itcm_geometry_manifest.json" "$itcm_run/manifest.json"
cp -- "$itcm_here/run.sh" "$itcm_run/"
printf '%s  %s\n' a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f "$itcm_bazel" | sha256sum -c -
itcm_startup=(--output_user_root="$itcm_study/bazel-user" --host_jvm_args=-Xmx2g --noblock_for_lock)
itcm_flags=(--noshow_progress --jobs=2 --local_resources=memory=4096 --lockfile_mode=error
    --repo_env=CORALNPU_MAKE_JOBS=2 --action_env=LANG=C.UTF-8 --action_env=LC_ALL=C.UTF-8)
itcm_package="tests/cocotb/itcm_capacity/i$itcm_kib"
itcm_top="VmeCoreMini_ITCM${itcm_kib}KB_DTCM2048KBAxi"
cd -- "$itcm_source"
printf '[ITCM_STAGE] Generating RTL, ITCM_KiB=%s DTCM_KiB=2048\n' "$itcm_kib"
"$itcm_bazel" "${itcm_startup[@]}" build "${itcm_flags[@]}" \
    "//$itcm_package:rtl_emit_verilog" 2>&1 | tee "$itcm_run/build.log"
itcm_header="bazel-bin/$itcm_package/V${itcm_top}_parameters.h"
python3 -B "$itcm_here/prepare_itcm.py" header --file "$itcm_header" --kib "$itcm_kib" | tee "$itcm_run/parameters.log"
cp "$itcm_header" "$itcm_run/parameters.h"
sha256sum "bazel-bin/$itcm_package/$itcm_top.sv" \
    "bazel-bin/$itcm_package/$itcm_top.zip" "$itcm_header" > "$itcm_run/artifacts.sha256"
itcm_target="//$itcm_package:geometry_itcm_geometry_test"
printf '%q ' "$itcm_bazel" "${itcm_startup[@]}" test "${itcm_flags[@]}" \
    --test_timeout=21600 --cache_test_results=no --test_output=errors "$itcm_target" > "$itcm_run/test-command.txt"
printf '\n' >> "$itcm_run/test-command.txt"
printf '[ITCM_STAGE] Frontdoor RAM geometry only; not performance\n'
date -u '+%Y-%m-%dT%H:%M:%SZ' > "$itcm_run/test-started-utc.txt"
itcm_started=$SECONDS
set +e
"$itcm_bazel" "${itcm_startup[@]}" test "${itcm_flags[@]}" \
    --test_timeout=21600 --cache_test_results=no --test_output=errors \
    "$itcm_target" 2>&1 | tee "$itcm_run/test-command.log"
itcm_status=("${PIPESTATUS[@]}")
set -e
date -u '+%Y-%m-%dT%H:%M:%SZ' > "$itcm_run/test-finished-utc.txt"
printf 'elapsed_seconds=%s\nbazel_exit=%s\ntee_exit=%s\n' \
    "$((SECONDS - itcm_started))" "${itcm_status[0]}" "${itcm_status[1]}" > "$itcm_run/test-exit-status.txt"
itcm_log="bazel-testlogs/$itcm_package/geometry_itcm_geometry_test/test.log"
[[ ! -f "$itcm_log" ]] || cp -L "$itcm_log" "$itcm_run/test.log"
if (( itcm_status[0] != 0 || itcm_status[1] != 0 )); then
    printf '[ITCM_INCOMPLETE] results=%s\n' "$itcm_run" >&2
    exit 1
fi
python3 -B "$itcm_here/prepare_itcm.py" log --file "$itcm_run/test.log" --kib "$itcm_kib" | tee "$itcm_run/summary.log"
python3 -B "$itcm_here/prepare_itcm.py" verify --upstream "$itcm_source"
printf '[ITCM_GEOMETRY_PASS] ITCM_KiB=%s DTCM_KiB=2048 results=%s\n' "$itcm_kib" "$itcm_run"
