# Expanded paired full-core speed sweep

This extends `README-fullcore-fair.md` without replacing its seven-case
baseline. Both checkouts run the same 22 signed-INT8 logical matrix tasks:
17 full 16x16 tiles with K = 1, 4, 8, 15, 16, 17, 31, 32, 33, 63, 64, 65,
127, 128, 129, 255, 256; and five K=64 occupancy cases with M/N = 1x1,
1x16, 16x1, 8x8, 15x15. Each is repeated three times. The fixture checks
all 256 physical INT32 outputs against a signed software reference, including
the zero-filled portion outside the logical MxN tile.

The official driver uses Tk=4 and zero-pads K to a multiple of 4. The fork
driver zero-pads K to a multiple of 16. Reported cycles use the same
launch-to-halt endpoint but include *different* whole cores and legal
instruction streams. The ratio is therefore a workload/driver comparison,
not a clock-frequency, area, power, or silicon-speed claim. These isolated
tiles do not measure complete-model inference or reuse across tiles.

On the Ubuntu VM (with the Git/Bazel network proxy available), run one
command at a time. Stop and share the first error if a command fails:

```bash
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
conda run -n coral-matrix python verification/check_fullcore_sweep.py
cd coralnpu-google
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=errors \
  //tests/cocotb/vme_test:vme_matrix_speed_sweep_vme_matrix_speed_sweep_test
cd ../coralnpu-Yangg152
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=errors \
  //tests/mxu:mxu_fullcore_speed_sweep_mxu_fullcore_speed_sweep_test
cd ..
conda run -n coral-matrix python verification/compare_fullcore_sweep.py \
  coralnpu-google/bazel-testlogs/tests/cocotb/vme_test/vme_matrix_speed_sweep_vme_matrix_speed_sweep_test/test.log \
  coralnpu-Yangg152/bazel-testlogs/tests/mxu/mxu_fullcore_speed_sweep_mxu_fullcore_speed_sweep_test/test.log
```

The final command refuses missing/duplicate runs, mismatched logical or
physical vector hashes, wrong K padding, incorrect output counts, and
non-deterministic per-case cycle counts. Send the manifest and all
`[FULLCORE_SWEEP_PAIR]` lines. A Bazel build success alone is not a test pass.
