# Model-like tile arithmetic and cycle diagnostics

This verification-only suite does **not** run a complete neural network. It
tests seven deterministic GEMM-shaped tasks with logical M/N/K, full signed
INT8 range, and an INT32 reference. Both hosts use the same logical A/B/C
fingerprint set; the expected digest of seven logical hashes is
`87085fb87e02f0b4d28c7de2aa256e55df836807842fe899538367211c72fbda`.
No functional RTL, original TB, original RISC-V ELF or existing model is edited.

| Case | Logical M | Logical N | Logical K | Fork physical K |
| --- | ---: | ---: | ---: | ---: |
| aligned control | 16 | 16 | 64 | 64 |
| 3x3, 3-channel-like | 16 | 16 | 27 | 32 |
| 3x3, 8-channel-like | 7 | 13 | 72 | 80 |
| 1x1, 17-channel-like | 15 | 11 | 17 | 32 |
| 1x1, 65-channel-like | 16 | 16 | 65 | 80 |
| FC batch-1-like | 1 | 10 | 127 | 128 |
| high-K tail | 16 | 9 | 241 | 256 |

Names indicate *shapes*, not a claim that a current TFLM convolution kernel
dispatches those layers to the matrix hardware. This is one 16x16 output tile
per case; it does not test multiple tiles, a complete convolution or K>256.

For official CoralNPU, unused M rows/N columns are zero; K is logical K, and
the existing program uses Tk=1. The full-core fixture reports cycles from
launch-wait to halt, including instruction dispatch, input vector loads,
configuration, result readback and shutdown. This is a **functional path and
full-core schedule diagnostic**, not an optimized application kernel.

For Yangg152, both operands are padded with zeros to
`K_hw=16*ceil(K/16)`, and unused M/N lanes are zero. The original fork unit
is configured for a 16x16xK_hw arithmetic tile. The separate bound monitor records MMA latency,
first weight command to 64th result handshake, and 64-beat readback span.
Unlike prior poisoned-padding tests, zero padding here is deliberate and
part of the driver workaround. The unmodified independent boundary TB checks
all 256 physical INT32 results, including zeroed lanes. Every case is run in
three fresh VCS processes. Both tests reject changed cycle counts across
repeats; this is repeatability, not a clock-frequency or power measurement.

`useful_macs=M*N*K`; the `physical_macs` fields count nominal full-tile
arithmetic slots: `256*K_hw` for the fork and `256*K` for the official
Tk=1 program. These are not measured switching activity or power. Their
ratio quantifies *arithmetic padding*, not achieved performance. The
official full-core and fork unit spans have different endpoints and software;
**do not divide their cycle counts to declare a hardware speed winner**. A
matched full-system workload/driver and same-library synthesis remain needed.

## Ubuntu VM (official full-core Verilator)

Keep the proxy active. Pull with a clean worktree and stop on any failure:

```bash
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
git rev-parse --short HEAD
conda run -n coral-matrix python verification/check_model_tile.py
cd coralnpu-google
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=all \
  //tests/cocotb/vme_test:vme_matrix_model_tile_vme_matrix_model_tile_test
```

Only after the target passes, validate all 21 records and print seven rows:

```bash
conda run -n coral-matrix python ../verification/summarize_google_model_tile.py \
  bazel-testlogs/tests/cocotb/vme_test/vme_matrix_model_tile_vme_matrix_model_tile_test/test.log
```

Preserve the full test log. The summary requires three deterministic complete
runs, matching logical and physical fingerprints, correct checked-element and
MAC counts, and the completion marker. This reuses the ordinary Verilator
model and original workload ELF; do not run `bazel clean`.

## EDA152 (fork standalone VCS)

Keep the Windows SSH proxy tunnel active for Git. Stop if Git fails:

```bash
cd /home2/lqq/Desktop/Coral_matrix
git pull --ff-only origin main
git rev-parse --short HEAD
bash verification/run_yangg152_model_tile.sh \
  /home2/lqq/Desktop/Coral_matrix /home2/lqq/Desktop/mxu_runs
```

The script creates a fresh `Yangg152_model_tile.XXXXXX` directory, exports
vectors plus a manifest, compiles the original SRAM/PE/unit with the already
validated boundary TB and a new **read-only** bind monitor, then runs 7x3
fresh VCS processes. It validates each 64/64 passing result, the exact shape,
MMA K_hw+3 latency and deterministic repeated cycle record before printing a
summary. A compile error, timeout, runtime simulator warning, mismatch or missing record
is a failure. Existing run directories are preserved. Review compile warnings
and keep all per-case stdout/run logs; this target has not been simulated on
Windows.

Return the `[GOOGLE_MODEL_TILE_MANIFEST]` and seven
`[GOOGLE_MODEL_TILE_SUMMARY]` rows, plus the server's `[MODEL_TILE_MANIFEST]`,
seven `[YANGG_MODEL_TILE_SUMMARY]` rows and final
`[YANGG_MODEL_TILE_CHECK]`. If either host fails, return the first failing
case/compile error and its log path instead; do not count partial results as
a completed comparison or change RTL just to make a benchmark pass.

## Model-software route audit still required

The repositories' MobileNet examples register ordinary `Register_CONV_2D`,
whereas the Yangg152 PoseNet example explicitly registers
`Register_MXU_CONV_2D`. Thus passing a model inference test does **not** prove
that the matrix path ran; selected model layers need dispatch tracing.
Yangg152's specialized software routes some 1x1 shapes to MXU and others to
RVV, and pads selected other convolutions to 16. Its non-1x1 MXU path has a
source-level output-channel bound concern: 16-channel fixed buffers are indexed
up to `output_depth`, without an `output_depth<=16` dispatch guard. This is
not an RTL result. Before real-model benchmarking, test or correct the route,
then record per-layer MXU/RVV/fallback usage and accuracy against a reference.

Local `check_model_tile.py` verifies scalar math, zero-padding/HEX roundtrip,
no-overwrite export, existing official harness upload/checks with a **fake**
fixture, and summary rejection. Bash and Python/BUILD syntax checks are also
local only. None compiles the new VCS monitor or runs actual RTL.
