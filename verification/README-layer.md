# Long-K and multi-output-tile diagnostics

This verification-only suite uses the **same signed-INT8 logical A/B/C** on
both hosts. It does not edit functional RTL or run a neural network. Both
shapes are plausible 1x1-convolution GEMMs under Yangg152's current dispatch
rule (`input_depth % 16 == 0`), but the suite drives arithmetic directly and
does **not** prove that the production TFLM path dispatched to MXU.

| Case | Logical MxNxK | Output tiles | K passes in Yangg152 |
| --- | --- | ---: | --- |
| multi-tile | 20x23x272 | 4 | 256 + 16 |
| three-pass thin output | 1x10x528 | 1 | 256 + 256 + 16 |

Each physical output tile is 16x16. Unused M/N rows/columns are zero, and
all 256 physical INT32 values are checked. The fork clears its accumulator
**once per output tile**, reconfigures and reloads between K passes, then
reads out only after all passes. This tests whether accumulated results survive
the later MCFG/load/MMA sequence. The official full-core program executes all
K steps in **one launch per output tile**, retaining its matrix accumulator;
different M/N tiles use separate launches. Both cases repeat three times.

The official `sum_tile_launch_wait_to_halt_cycles` is the sum of full-core
program launches, including each launch's startup, configuration, vector
loads, result readback, and halt. The fork
`sum_tile_input_to_output_cycles` is the sum of standalone-unit windows from
first weight-command handshake to final output handshake. Neither includes
model im2col, requantization, software loop dispatch, inter-tile memory
movement, or activation/weight cache behavior. **The numbers do not share a
timing boundary and must not be divided to rank final SoC performance.** They
diagnose functional feasibility, repeated-pass costs and scaling within each
engine. Nominal full-tile MAC counts are not power/activity measurements.

## Ubuntu VM: official full core

Keep the existing proxy available, and pull only with a clean worktree:

```bash
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
git rev-parse --short HEAD
conda run -n coral-matrix python verification/check_mxu_layer.py
cd coralnpu-google
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=all \
  //tests/cocotb/vme_test:vme_matrix_layer_vme_matrix_layer_test
```

Only if the Bazel target passes, summarize its 15 per-tile records and six
per-layer records:

```bash
conda run -n coral-matrix python ../verification/summarize_google_layer.py \
  bazel-testlogs/tests/cocotb/vme_test/vme_matrix_layer_vme_matrix_layer_test/test.log
```

The new long-K ELF is separate from the previous <=256 performance ELF, so
previous baselines are not silently changed. This probes signed B, Tk=1,
K=272/528, single accumulator per tile; it is not an optimized application
schedule. Preserve the complete test log if it fails.

## EDA152: Yangg152 standalone unit

Keep the Windows reverse-SSH Git proxy alive:

```bash
cd /home2/lqq/Desktop/Coral_matrix
git pull --ff-only origin main
git rev-parse --short HEAD
bash verification/run_yangg152_layer.sh \
  /home2/lqq/Desktop/Coral_matrix /home2/lqq/Desktop/mxu_runs
```

The script creates a fresh run directory, exports per-tile/per-pass HEX files,
compiles the original SRAM/PE/unit plus an independent testbench, then runs
five tiles x three fresh VCS processes. It requires 64/64 output beats,
exact expected MMA cycle sums and deterministic repeat counts before emitting
five `[YANGG_LAYER_TILE_SUMMARY]`, two `[YANGG_LAYER_SUMMARY]`, and
`[YANGG_LAYER_CHECK]`. Existing runs are preserved. A failing compile,
simulation, timeout, result, or missing record is **not** a partial pass.

Send both `[GOOGLE_LAYER_MANIFEST]` and `[MXU_LAYER_MANIFEST]`, both case
summaries, and final check lines. The expected shared logical-set digest is
`77d2281e35119c649f96f030303bf487411ac10dcfe2eb59970cb889af890376`
and must match on both hosts. If a run fails, send its first failing log path
and error; do not change RTL merely to make the benchmark pass.

Local tests validate scalar arithmetic, tiling, pass-split sum, HEX roundtrip,
no-overwrite export, fake official upload/check contract and strict summary
rejection. They **do not** compile the C++ program or VCS testbench, and do
not substitute for the above RTL simulations.
