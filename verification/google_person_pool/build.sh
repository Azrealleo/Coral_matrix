#!/usr/bin/env bash
# New candidate only: leave Depthwise, VME v1 and existing server jobs untouched.
set -euo pipefail
pd_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
pd_study=${1:-"$HOME/coral_tcm_capacity_8e4_v1"}
[[ $(uname -s) == Linux ]] || { echo 'Run on the Ubuntu VM.' >&2; exit 2; }
pd_study=$(cd -- "$pd_study" && pwd -P)
pd_source="$pd_study/source";pd_bazel="$pd_study/bazel-9.1.0"
pd_assets="$pd_study/person_detect_b75c6ff4_assets"
printf '%s  %s\n' a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f "$pd_bazel" | sha256sum -c -
python3 -c 'import elftools'
python3 -B "$pd_here/prepare_pool.py" --upstream "$pd_source" --assets "$pd_assets"
pd_run=$(mktemp -d "$pd_study/person_pool_v1.XXXXXX")
printf '[PERSON_POOL_BUILD_DIRECTORY] %s\n' "$pd_run"
cp -- "$pd_source/person_detect_vme_pool_v1_manifest.json" "$pd_run/manifest.json"
pd_startup=(--output_user_root="$pd_study/bazel-user" --host_jvm_args=-Xmx2g --noblock_for_lock)
pd_flags=(--noshow_progress --color=no --curses=no --jobs=2 --local_resources=memory=4096 --lockfile_mode=error
    --repo_env=CORALNPU_MAKE_JOBS=2 --action_env=LANG=C.UTF-8 --action_env=LC_ALL=C.UTF-8)
cd -- "$pd_source"
printf '[PERSON_POOL_STAGE] Native pinned-TFLM pooling reference + original model two images; NOT RTL\n'
"$pd_bazel" "${pd_startup[@]}" test "${pd_flags[@]}" --cache_test_results=no --test_output=all --test_timeout=1800 \
    //tests/cocotb/person_detect_vme_pool_v1:host_pool_core_test \
    //tests/cocotb/person_detect_vme_pool_v1:host_model_test 2>&1 | tee "$pd_run/host-test.log"
grep -Fq '[PERSON_POOL_HOST_MODEL_PASS] cases=2 compared_layers=30' "$pd_run/host-test.log"
for pd_mode in validate fast;do
    pd_target="//tests/cocotb/person_detect_vme_pool_v1:person_vme_pool_${pd_mode}.elf"
    "$pd_bazel" "${pd_startup[@]}" build "${pd_flags[@]}" "$pd_target" 2>&1 | tee "$pd_run/$pd_mode-build.log"
    "$pd_bazel" "${pd_startup[@]}" cquery "${pd_flags[@]}" --universe_scope="$pd_target" \
        --output=files "config($pd_target, target)" > "$pd_run/$pd_mode-outputs.txt" 2> "$pd_run/$pd_mode-query.log" \
        || { cat "$pd_run/$pd_mode-query.log" >&2;exit 1; }
    "$pd_bazel" "${pd_startup[@]}" info execution_root > "$pd_run/execution-root.txt" 2> "$pd_run/info.log"
    python3 -B "$pd_here/audit_pool.py" --mode "$pd_mode" --execution-root-file "$pd_run/execution-root.txt" \
        --outputs-file "$pd_run/$pd_mode-outputs.txt" --output "$pd_run/$pd_mode" | tee "$pd_run/$pd_mode-resources.log"
done
python3 -B "$pd_here/prepare_pool.py" --upstream "$pd_source" --assets "$pd_assets"
printf '[PERSON_POOL_HOST_AND_LINK_PASS] depthwise_unchanged=true NPU_RTL=NOT_RUN results=%s\n' "$pd_run"
