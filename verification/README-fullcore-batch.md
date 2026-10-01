# One-launch shared-weight full-core batch

This follows the 22-case single-tile sweep. Each run starts one core, computes
1, 4, or 16 **different** 16x16 signed-INT8 output tiles, stores all results,
then halts. K is 16, 64, or 256, so both implementations use the same exact
K without padding. The same B matrix is shared across all tiles in a run.
All `tiles * 256` INT32 results are checked against a software reference.
Each of the nine workload shapes is repeated three times.
The large input/output buffers are placed in each checkout's `.extbss`
external-memory section (0x20000000); small control words remain in DTCM.
The fixture overwrites every byte of these buffers for each repeat, so no
ELF initialization is needed; `.extbss` also keeps them out of the raw BIN.
Consequently, do not compare the absolute one-tile cycles here with the
earlier DTCM-backed single-tile sweep as if only batch length had changed.

The programs follow legal but distinct schedules. Official Tk=4 reloads A
and B from memory for each tile; the fork loads B into MXU weight SRAM once,
then clears the accumulator, reloads A and computes each subsequent tile.
Thus this is a **specific legal-schedule workload comparison**, not a pure
array comparison or proof of silicon speed at a target clock. In particular,
the fork's reuse advantage and the official core's other overheads cannot be
separated from the overall cycle ratio. The official schedule has not been
proven optimal; an alternative loop order or register use may improve it.
It also does not model memory
contention, complete AI inference, or frequency/area/power.

On the Ubuntu VM, with the proxy available, run in order and stop on the
first error:

```bash
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
conda run -n coral-matrix python verification/check_fullcore_batch.py
cd coralnpu-google
bazel build --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  //tests/cocotb/vme_test:vme_matrix_shared_weight_batch_program
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=errors \
  //tests/cocotb/vme_test:vme_matrix_shared_weight_batch_vme_matrix_shared_weight_batch_test
cd ../coralnpu-Yangg152
bazel build --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  //tests/mxu:mxu_fullcore_shared_weight_batch_program
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=errors \
  //tests/mxu:mxu_fullcore_shared_weight_batch_mxu_fullcore_shared_weight_batch_test
cd ..
conda run -n coral-matrix python verification/compare_fullcore_batch.py \
  coralnpu-google/bazel-testlogs/tests/cocotb/vme_test/vme_matrix_shared_weight_batch_vme_matrix_shared_weight_batch_test/test.log \
  coralnpu-Yangg152/bazel-testlogs/tests/mxu/mxu_fullcore_shared_weight_batch_mxu_fullcore_shared_weight_batch_test/test.log
```

Return the manifest and nine `[FULLCORE_BATCH_PAIR]` rows, or the first
build/test error and its log path. The parser rejects incomplete repeats,
wrong vector hashes, wrong output counts and unstable per-case cycles. Compare
cycles per tile as batch length grows, not only the total batch cycles.
