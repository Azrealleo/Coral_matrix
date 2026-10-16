#!/usr/bin/env bash
# One capacity / weight working set / external read-delay assumption at a time.
set -euo pipefail
tcm_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
tcm_kib=${1:-32}
tcm_tiles=${2:-12}
tcm_delay=${3:-0}
tcm_study=${4:-"$HOME/coral_tcm_capacity_8e4_v1"}
case "$tcm_kib" in 32|128|512|1024|2048|4096) ;; *) echo 'Invalid DTCM KiB' >&2; exit 2 ;; esac
case "$tcm_tiles" in 2|12|120|192|384|768) ;; *) echo 'Invalid weight tile count' >&2; exit 2 ;; esac
case "$tcm_delay" in 0|8) ;; *) echo 'Read delay must be 0 or 8 cycles' >&2; exit 2 ;; esac
[[ $(uname -s) == Linux ]] || { echo 'Run in native Linux.' >&2; exit 2; }
tcm_study=$(cd -- "$tcm_study" && pwd -P)
tcm_source="$tcm_study/source"
tcm_bazel="$tcm_study/bazel-9.1.0"
python3 -B "$tcm_here/prepare_workset.py" prepare --upstream "$tcm_source"
tcm_run=$(mktemp -d "$tcm_study/workset_d${tcm_kib}_t${tcm_tiles}_r${tcm_delay}.XXXXXX")
printf '[TCM_WORKSET_RUN_DIRECTORY] %s\n' "$tcm_run"
cp "$tcm_source/tcm_workset_manifest.json" "$tcm_run/manifest.json"
cp -- "$tcm_here/run_workset.sh" "$tcm_here/resolve_bazel_elf.py" "$tcm_run/"
printf '%s  %s\n' a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f "$tcm_bazel" | sha256sum -c -
tcm_startup=(--output_user_root="$tcm_study/bazel-user" --host_jvm_args=-Xmx2g)
tcm_flags=(--noshow_progress --jobs=2 --local_resources=memory=4096 --lockfile_mode=error
    --repo_env=CORALNPU_MAKE_JOBS=2 --action_env=LANG=C.UTF-8 --action_env=LC_ALL=C.UTF-8)
tcm_package="tests/cocotb/tcm_workset/d$tcm_kib"
tcm_top=VmeCoreMiniAxi
if [[ "$tcm_kib" != 32 ]]; then tcm_top="VmeCoreMini_ITCM8KB_DTCM${tcm_kib}KBAxi"; fi
cd -- "$tcm_source"
"$tcm_bazel" "${tcm_startup[@]}" version > "$tcm_run/bazel-version.log" 2>&1
printf '[TCM_STAGE] Building workset RTL/program, DTCM_KiB=%s weight_tiles=%s read_delay=%s\n' "$tcm_kib" "$tcm_tiles" "$tcm_delay"
printf '%q ' "$tcm_bazel" "${tcm_startup[@]}" build "${tcm_flags[@]}" \
    "//$tcm_package:rtl_emit_verilog" //tests/cocotb/tcm_workset:workset_program.elf > "$tcm_run/build-command.txt"
printf '\n' >> "$tcm_run/build-command.txt"
"$tcm_bazel" "${tcm_startup[@]}" build "${tcm_flags[@]}" \
    "//$tcm_package:rtl_emit_verilog" //tests/cocotb/tcm_workset:workset_program.elf 2>&1 | tee "$tcm_run/build.log"
tcm_header="bazel-bin/$tcm_package/V${tcm_top}_parameters.h"
python3 -B "$tcm_here/prepare.py" header --file "$tcm_header" --kib "$tcm_kib" | tee "$tcm_run/parameters.log"
cp "$tcm_header" "$tcm_run/parameters.h"
printf '[TCM_STAGE] Resolving configured workset ELF\n'
"$tcm_bazel" "${tcm_startup[@]}" cquery "${tcm_flags[@]}" \
    --universe_scope=//tests/cocotb/tcm_workset:workset_program.elf \
    --output=files 'config(//tests/cocotb/tcm_workset:workset_program.elf, target)' \
    > "$tcm_run/elf-outputs.txt" 2> "$tcm_run/elf-query.log" || { cat "$tcm_run/elf-query.log" >&2; exit 1; }
"$tcm_bazel" "${tcm_startup[@]}" info execution_root \
    > "$tcm_run/execution-root.txt" 2> "$tcm_run/execution-root-query.log" || { cat "$tcm_run/execution-root-query.log" >&2; exit 1; }
tcm_elf=$(python3 -B "$tcm_here/resolve_bazel_elf.py" --basename workset_program.elf \
    --execution-root-file "$tcm_run/execution-root.txt" --outputs-file "$tcm_run/elf-outputs.txt")
printf '[TCM_WORKSET_ELF] %s\n' "$tcm_elf"
cp -L -- "$tcm_elf" "$tcm_run/workset_program.elf"
sha256sum "bazel-bin/$tcm_package/$tcm_top.sv" "$tcm_header" "$tcm_run/workset_program.elf" \
    "$tcm_run/run_workset.sh" "$tcm_run/resolve_bazel_elf.py" > "$tcm_run/artifacts.sha256"
printf '[TCM_STAGE] Building/running stream vs prefix-cache, three repeats each\n'
printf '%q ' "$tcm_bazel" "${tcm_startup[@]}" test "${tcm_flags[@]}" \
    --cache_test_results=no --test_output=errors "--test_env=TCM_WS_TILES=$tcm_tiles" \
    "--test_env=TCM_WS_READ_DELAY=$tcm_delay" "//$tcm_package:workset_tcm_workset_test" > "$tcm_run/test-command.txt"
printf '\n' >> "$tcm_run/test-command.txt"
"$tcm_bazel" "${tcm_startup[@]}" test "${tcm_flags[@]}" --cache_test_results=no --test_output=errors \
    "--test_env=TCM_WS_TILES=$tcm_tiles" "--test_env=TCM_WS_READ_DELAY=$tcm_delay" \
    "//$tcm_package:workset_tcm_workset_test" 2>&1 | tee "$tcm_run/test-command.log"
cp -L "bazel-testlogs/$tcm_package/workset_tcm_workset_test/test.log" "$tcm_run/test.log"
python3 -B "$tcm_here/prepare_workset.py" log --file "$tcm_run/test.log" \
    --kib "$tcm_kib" --tiles "$tcm_tiles" --delay "$tcm_delay" | tee "$tcm_run/summary.log"
python3 -B "$tcm_here/prepare_workset.py" verify --upstream "$tcm_source"
printf '[TCM_WORKSET_PASS] DTCM_KiB=%s tiles=%s read_delay=%s results=%s\n' "$tcm_kib" "$tcm_tiles" "$tcm_delay" "$tcm_run"
