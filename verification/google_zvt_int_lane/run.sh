#!/usr/bin/env bash
set -euo pipefail

# Run the unmodified Google Zvt INT8 PE lane outside the Git worktree.
# This smoke test does not verify the matrix array or complete NPU core.
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
run_dir="${1:?usage: bash run.sh /absolute/output-directory}"
rev=bb65bdedd07711dfd41c621382f940a5cbb93046
archive=cvfpu-$rev.zip
sha=0723e6a6feb8e033679d2f9145f99ee4fb26c80e67b3662a8eec9b61bd30f6cc

mkdir -p "$run_dir"
cd "$run_dir"
if [[ ! -f "$archive" ]]; then
  curl_args=(-fL)
  if [[ -n "${CORAL_PROXY:-}" ]]; then
    curl_args+=(-x "$CORAL_PROXY")
  fi
  curl "${curl_args[@]}" -o "$archive" \
    "https://github.com/openhwgroup/cvfpu/archive/$rev.zip"
fi
printf '%s  %s\n' "$sha" "$archive" | sha256sum -c -
if [[ ! -f "cvfpu-$rev/src/fpnew_pkg.sv" ]]; then
  python3 -m zipfile -e "$archive" .
fi

google="$repo_root/coralnpu-google/hdl/verilog/rvv"
vcs -full64 -sverilog -top zvt_int_lane_tb -o simv \
  "cvfpu-$rev/src/fpnew_pkg.sv" \
  "$google/common/edff.sv" \
  "$google/design/Zvt/zvt_pe_mulbulk_int_lane.sv" \
  "$repo_root/verification/google_zvt_int_lane/tb.sv" \
  +incdir+"$google/inc"
./simv
