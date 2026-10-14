#!/usr/bin/env bash
# Run ONE capacity at a time. Stage 1 is RAM qualification, not performance.
set -euo pipefail
tcm_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
tcm_kib=${1:-32}
tcm_study=${2:-"$HOME/coral_tcm_capacity_8e4_v1"}
case "$tcm_kib" in 32|128|512|1024|2048|4096) ;; *) echo 'DTCM KiB must be 32/128/512/1024/2048/4096' >&2; exit 2 ;; esac
[[ $(uname -s) == Linux ]] || { echo 'Run in native Linux, not Windows/Git Bash.' >&2; exit 2; }
for tcm_tool in git python3 curl sha256sum; do command -v "$tcm_tool" >/dev/null; done
mkdir -p -- "$tcm_study"
tcm_study=$(cd -- "$tcm_study" && pwd -P)
tcm_run=$(mktemp -d "$tcm_study/run_d${tcm_kib}.XXXXXX")
printf '[TCM_RUN_DIRECTORY] %s\n' "$tcm_run"
tcm_source="$tcm_study/source"
tcm_team="$tcm_study/team.git"
tcm_team_url=${TCM_TEAM_URL:-git@github.com:cheshire-coral-soc/cheshire-coral-soc.git}
tcm_upstream=8e4df09b4ea7e065e02d14ce3ae033d40dfd973a
tcm_team_commit=95e06e872bff13b3625721a837b4b739a93bed6f

if [[ ! -e "$tcm_source" ]]; then
    git clone --no-checkout --depth 1 https://github.com/google-coral/coralnpu.git "$tcm_source"
    git -C "$tcm_source" fetch --depth 1 origin "$tcm_upstream"
    git -C "$tcm_source" checkout --detach "$tcm_upstream"
fi
if [[ ! -f "$tcm_source/tcm_capacity_manifest.json" ]]; then
    command -v ssh >/dev/null
    if [[ ! -e "$tcm_team" ]]; then
        git clone --bare --depth 1 "$tcm_team_url" "$tcm_team"
    fi
    if [[ $(git -C "$tcm_team" rev-parse --is-bare-repository 2>/dev/null) != true ]]; then
        printf 'Existing team path is not a bare Git repository; preserved unchanged: %s\n' "$tcm_team" >&2
        exit 2
    fi
    # Explicit URL also handles existing clones whose origin still uses HTTPS.
    # Honor GIT_SSH_COMMAND/ssh-agent; never rewrite global Git or SSH settings.
    git -C "$tcm_team" fetch --depth 1 "$tcm_team_url" "$tcm_team_commit"
    python3 -B "$tcm_here/prepare.py" prepare --upstream "$tcm_source" --team-git "$tcm_team"
fi
python3 -B "$tcm_here/prepare.py" verify --upstream "$tcm_source"
cp "$tcm_source/tcm_capacity_manifest.json" "$tcm_run/manifest.json"
git -C "$tcm_source" diff --binary > "$tcm_run/experiment.patch"

tcm_bazel="$tcm_study/bazel-9.1.0"
tcm_bazel_sha=a667454f3f4f8878df8199136b82c199f6ada8477b337fae3b1ef854f01e4e2f
if [[ ! -e "$tcm_bazel" ]]; then
    curl -fL --retry 3 --connect-timeout 15 --max-time 300 \
        -o "$tcm_run/bazel.download" \
        https://releases.bazel.build/9.1.0/release/bazel-9.1.0-linux-x86_64
    printf '%s  %s\n' "$tcm_bazel_sha" "$tcm_run/bazel.download" | sha256sum -c -
    mv "$tcm_run/bazel.download" "$tcm_bazel"
    chmod u+x "$tcm_bazel"
fi
printf '%s  %s\n' "$tcm_bazel_sha" "$tcm_bazel" | sha256sum -c -
tcm_startup=(--output_user_root="$tcm_study/bazel-user" --host_jvm_args=-Xmx2g)
tcm_build_flags=(--jobs=2 --local_resources=memory=4096 --lockfile_mode=error
    --repo_env=CORALNPU_MAKE_JOBS=2 --action_env=LANG=C.UTF-8 --action_env=LC_ALL=C.UTF-8)
tcm_package="tests/cocotb/tcm_capacity/d$tcm_kib"
tcm_top=VmeCoreMiniAxi
if [[ "$tcm_kib" != 32 ]]; then tcm_top="VmeCoreMini_ITCM8KB_DTCM${tcm_kib}KBAxi"; fi
cd -- "$tcm_source"
"$tcm_bazel" "${tcm_startup[@]}" version > "$tcm_run/bazel-version.log" 2>&1
printf '%q ' "$tcm_bazel" "${tcm_startup[@]}" build "${tcm_build_flags[@]}" "//$tcm_package:rtl_emit_verilog" > "$tcm_run/build-command.txt"
printf '\n' >> "$tcm_run/build-command.txt"
"$tcm_bazel" "${tcm_startup[@]}" build "${tcm_build_flags[@]}" \
    "//$tcm_package:rtl_emit_verilog" 2>&1 | tee "$tcm_run/generate.log"
tcm_header="bazel-bin/$tcm_package/V${tcm_top}_parameters.h"
python3 -B "$tcm_here/prepare.py" header --file "$tcm_header" --kib "$tcm_kib" | tee "$tcm_run/parameters.log"
cp "$tcm_header" "$tcm_run/parameters.h"
sha256sum "bazel-bin/$tcm_package/$tcm_top.sv" \
    "bazel-bin/$tcm_package/$tcm_top.zip" "$tcm_header" > "$tcm_run/rtl.sha256"
"$tcm_bazel" "${tcm_startup[@]}" test "${tcm_build_flags[@]}" \
    --cache_test_results=no --test_output=errors \
    "//$tcm_package:capacity_tcm_capacity_test" 2>&1 | tee "$tcm_run/test-command.log"
cp -L "bazel-testlogs/$tcm_package/capacity_tcm_capacity_test/test.log" "$tcm_run/test.log"
python3 -B "$tcm_here/prepare.py" log --file "$tcm_run/test.log" --kib "$tcm_kib" | tee "$tcm_run/summary.log"
python3 -B "$tcm_here/prepare.py" verify --upstream "$tcm_source"
printf '[TCM_STAGE1_PASS] DTCM_KiB=%s results=%s\n' "$tcm_kib" "$tcm_run"
