# Common K-boundary and MXU stall diagnostics

Verification additions only: no functional RTL, original `mxu_tb`, existing
RISC-V program or existing simulator model is changed. These new RTL tests
have **not yet been run** on the VM/server. Local checks are described below.
The paired 32-case signed pressure pass is recorded in `README-mxu-perf.md`.

## Scope and assumptions

Both designs receive the same deterministic signed INT8 A/B and widened
16x16 INT32 golden matrix for each K:

```text
1 2 3 4 7 15 16 17 31 32 33 63 64 65 127 128 129 240 241 255 256
```

These 21 cases check complete tiles, not partial M/N tiles or every K value.
There are 5376 checked output elements per input schedule. The logical
vector-set SHA256 (concatenated per-case A/B/C hashes in the order above) is:

```text
b71ab7aecb33652c0d7fcda2887e10db948e35fc482b03ef8d28bb374afd888a
```

The official runner reuses the original workload ELF with **Tk=1 for every
instruction**, allowing arbitrary K without changing that program. Each case
checks all 256 outputs, configuration readback and completion. This is a
functional check, not optimized Tk=4 plus mixed-tail performance. It does
not inject official array/interface backpressure. Existing full-core cycle
logs must not be ranked against the fork's standalone schedule.

The independent fork TB configures total K directly (`cfg_Tk=0` means 256),
loads K weight beats and `16*ceil(K/16)` activation beats, then issues one MMA
and 64 MSTORE commands. Activations are padded **after each row** with 37;
unused weight bytes are 53. Nonzero padding makes unintended contributions
visible. Every case starts in a fresh simulator process. Drives use falling
edges; output handshakes are scored on rising edges before NBA.

Two input schedules are checked for all K: continuous continuation beats,
and two valid-low bubbles before every third continuation beat. The first
load beat is accepted with the command even though stream-ready is initially
low, matching the existing unit/testbench protocol. The output consumer is
always ready for these arithmetic checks.

A separate K=16 test holds `result_ready=0` across the first output. It
requires the ordinary ready/valid contract: once valid is offered, valid and
payload stay unchanged until acceptance. It checks actual handshakes, not
`op_done` alone. If the intended interface requires always-ready consumers,
failure means that feature is unsupported; whether it violates the design
contract must be settled before calling it an integration bug. This is a
unit-level check, not an integrated wrapper/ROB stall test.

## Source concerns to reproduce, not confirmed RTL results

In `coralnpu-Yangg152/hdl/mxu/rvv_backend_mxu_unit.sv`:

- MCFG uses `cfg_Tk[7:4]` for activation chunks when K>=16, rather than
  `ceil(K/16)`. For example K=17 selects one chunk per row, while the
  exporter sends two. Row mapping and unwritten activation columns need
  testing. K=256 has its own special 16-chunk encoding.
- `result_ready` is declared but unused. MSTORE pulses valid, advances the
  output index and reports done regardless of consumer readiness. Under
  the ready/valid assumption above this predicts an output-stall failure.

The inspected integrated unit copy in `hdl/verilog/rvv/design` is identical;
the wrapper passes a downstream readiness signal to the unit. The actual
integrated ROB contract and legal-K restrictions still need confirmation.
If legal K is restricted to multiples of 16, or output readiness is guaranteed,
record those restrictions explicitly rather than silently broadening the
design's advertised contract. Do not patch RTL merely to make diagnostics pass.

## Run on the Ubuntu VM

Keep the existing working proxy environment. Stop if Git or a local check fails.
Use the same Conda environment in which the signed summary now succeeds:

```bash
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
git rev-parse --short HEAD
conda run -n coral-matrix python verification/check_mxu_boundary.py
cd coralnpu-google
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=all \
  //tests/cocotb/vme_test:vme_matrix_boundary_vme_matrix_k_boundary_test
```

Only after the target passes:

```bash
conda run -n coral-matrix python ../verification/summarize_google_boundary.py \
  bazel-testlogs/tests/cocotb/vme_test/vme_matrix_boundary_vme_matrix_k_boundary_test/test.log
```

Expect one `[GOOGLE_K_BOUNDARY_SUMMARY]` row after all 21 records, the
completion marker and logical fingerprints validate. Preserve the full
test log and revision. This uses the ordinary cached Verilator model;
do not run `bazel clean`.

## Run on EDA152

Keep the Windows SSH proxy tunnel active for Git. Stop if the pull fails:

```bash
cd /home2/lqq/Desktop/Coral_matrix
git pull --ff-only origin main
git rev-parse --short HEAD
bash verification/run_yangg152_boundary.sh \
  /home2/lqq/Desktop/Coral_matrix /home2/lqq/Desktop/mxu_runs
```

The script creates a fresh `Yangg152_boundary.XXXXXX` directory, records
revision/source hashes and writes vectors plus a manifest, then compiles
the new TB once using VCS. No FSDB or true-uint8 mode is enabled. Old results
are preserved. Compilation failure stops immediately; review warnings too.

K=16/64/256 with both input schedules are six controls. If any control fails,
the script stops: inspect the new driver, source and stall behavior before
interpreting unaligned-K results. Once controls pass, remaining K/schedule
runs are collected even if a diagnostic fails; the final output-stall test
is independent. There are 43 runs in total: 21 K values x two schedules,
plus one output-stall run. Every process has a 120-second wall-clock timeout
and a 40000-clock TB watchdog.

A PASS requires 64 actual output handshakes, 64 matching golden beats, a
completion marker, zero exit status and no detected runtime warnings/errors.
The final script status is **nonzero if any run failed**. That is not a pass
or permission to change the implementation. Keep the failing log for diagnosis;
the script prints its path. If interrupted or stopped at a control, do not
infer the remaining cases ran.

Send back the `[MXU_BOUNDARY_MANIFEST]`, `[MXU_K_RUN]` and
`[MXU_BOUNDARY_SUMMARY]` lines, plus any displayed mismatch/stall/timeout/error
messages. Preserve `compile.log`, per-run `.run.log`/`.stdout.log`, revision
and `vectors/manifest.json`. Compare the manifest digest with the VM summary.

## Local validation, not hardware validation

`check_mxu_boundary.py` has four synthetic checks: all 21 independent scalar
references; per-row padded HEX roundtrip and no-overwrite behavior; the real
host harness's upload/reference checks using a fake fixture, including wrong
output rejection; and strict summary parsing/rejection. Git Bash checked
shell syntax. New Python files and BUILD syntax were parsed locally.

These checks do not compile the new SV TB, run RTL, verify VCS scheduling,
or prove the new Bazel target works. The six controls and actual VM test are
the next gates. Mid-operation reset, mixed-Tk tails, partial M/N, continuous
multi-tile workloads, long accumulation/overflow, four-state/X checks of the
official RTL, integrated protocol verification and matched PPA/signoff remain.
