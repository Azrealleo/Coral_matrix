#!/usr/bin/env bash
# VM only: official native TFLM test + firmware link/resource audit. NO RTL run.
set -euo pipefail
pd_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
pd_study=${1:-"$HOME/coral_tcm_capacity_8e4_v1"}
[[ $(uname -s) == Linux ]] || { echo 'Run on the Ubuntu VM, not CentOS or Windows.' >&2; exit 2; }
pd_study=$(cd -- "$pd_study" && pwd -P)
pd_source="$pd_study/source"
pd_bazel="$pd_study/bazel-9.1.0"
python3 -c 'import elftools' || { echo 'In coral-matrix install: python -m pip install pyelftools==0.32' >&2; exit 2; }
printf '%s  %s\n' a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f "$pd_bazel" | sha256sum -c -
pd_assets="$pd_study/person_detect_b75c6ff4_assets"
python3 -B "$pd_here/fetch.py" "$pd_assets"
python3 -B "$pd_here/prepare_person.py" --upstream "$pd_source" --assets "$pd_assets"
pd_run=$(mktemp -d "$pd_study/person_firmware.XXXXXX")
printf '[PERSON_FIRMWARE_RUN_DIRECTORY] %s\n' "$pd_run"
cp -- "$pd_source/person_detect_firmware_manifest.json" "$pd_run/manifest.json"
cp -- "$pd_here/build_firmware.sh" "$pd_here/firmware_report.py" "$pd_here/spec.py" "$pd_run/"
pd_startup=(--output_user_root="$pd_study/bazel-user" --host_jvm_args=-Xmx2g --noblock_for_lock)
pd_flags=(--noshow_progress --color=no --curses=no --jobs=2 --local_resources=memory=4096 --lockfile_mode=error
    --repo_env=CORALNPU_MAKE_JOBS=2 --action_env=LANG=C.UTF-8 --action_env=LC_ALL=C.UTF-8)
cd -- "$pd_source"
printf '[PERSON_STAGE] Native pinned-TFLM person/no-person host test, not NPU RTL\n'
"$pd_bazel" "${pd_startup[@]}" test "${pd_flags[@]}" --cache_test_results=no \
    --test_output=all --test_timeout=1800 \
    @tflite_micro//tensorflow/lite/micro/examples/person_detection:person_detection_test \
    2>&1 | tee "$pd_run/host-test-command.log"
python3 -B "$pd_here/check_host.py" "$pd_run/host-test-command.log" | tee "$pd_run/host-reference.json.log"
printf '[PERSON_TFLM_NATIVE_HOST_TEST_PASS] NPU_RTL=NOT_RUN\n' | tee "$pd_run/host-pass.log"
printf '[PERSON_STAGE] Cross-compile only; ITCM link ceiling512KiB / DTCM512KiB\n'
pd_target=//tests/cocotb/person_detect_baseline:person_program.elf
"$pd_bazel" "${pd_startup[@]}" build "${pd_flags[@]}" "$pd_target" 2>&1 | tee "$pd_run/build.log"
"$pd_bazel" "${pd_startup[@]}" cquery "${pd_flags[@]}" --universe_scope="$pd_target" \
    --output=files "config($pd_target, target)" > "$pd_run/elf-outputs.txt" 2> "$pd_run/elf-query.log" \
    || { cat "$pd_run/elf-query.log" >&2; exit 1; }
"$pd_bazel" "${pd_startup[@]}" info execution_root > "$pd_run/execution-root.txt" 2> "$pd_run/info.log"
python3 -B "$pd_here/firmware_report.py" --execution-root-file "$pd_run/execution-root.txt" \
    --outputs-file "$pd_run/elf-outputs.txt" --copy-to "$pd_run/person_program.elf" \
    --report "$pd_run/resources.json" | tee "$pd_run/resources.log"
python3 -B "$pd_here/prepare_person.py" --upstream "$pd_source" --assets "$pd_assets"
printf '[PERSON_FIRMWARE_MEASURED] NPU_RTL=NOT_RUN results=%s\n' "$pd_run"
