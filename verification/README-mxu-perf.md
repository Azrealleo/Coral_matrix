# MXU baseline profiling

This is a simulation-only, read-only observer for the **existing Yangg152
`mxu_tb` schedule**. It is not yet the common benchmark used to rank the two
projects. No RTL or original testbench is changed. It profiles the existing
K=16, 64, 256 signed tests and the K=16 nonnegative test.

## Run on EDA152

The files live together in `verification/`. Commit and push the Windows
changes to the user's `Coral_matrix` repository, then update the Linux
checkout using Git. In the **EDA152 server terminal**, not the Ubuntu VMware VM:

```bash
cd /home2/lqq/Desktop/Coral_matrix
git pull --ff-only origin main
bash verification/run_yangg152_perf.sh \
  /home2/lqq/Desktop/Coral_matrix \
  /home2/lqq/Desktop/mxu_runs
```

Run these steps sequentially. If the pull fails, stop and inspect the local
commits and worktree before running the benchmark; do not force-reset or
discard server changes. `--ff-only` deliberately refuses a divergent merge.
The monitor and script must remain in the same directory.

The script creates a fresh `Yangg152_perf.XXXXXX` directory for every run,
generates golden vectors there, compiles using VCS, and stops on a compile or
simulation error. Previous runs are preserved. The unsigned diagnostic and
FSDB dumping are intentionally not enabled. Preserve the displayed commit,
source hashes, `compile.log`, and `run.log` with the result.

Only use measurements if all 256 golden beats pass, four `[MXU_PERF]` rows
appear, and no incomplete-frame, probe, or simulation warnings/errors occur.
Review compilation warnings as well.

## Counter definitions

Transfers/command accepts are sampled on rising edges before NBA updates.
The first weight/activation beat is accepted with MLOAD_W/MLOAD_A, before
their stream-ready signal goes high; the probe counts that special beat.
`op_done` is observed 1 ps after the edge so the counter does not include the
extra wait edge in the testbench's `do_mma` task.

| Field | Boundary |
| --- | --- |
| `mma_latency_cycles` | Clock intervals from accepted MMA to registered `op_done` becoming asserted |
| `load_span_cycles` | First accepted weight beat to last accepted input beat, inclusive |
| `readback_span_cycles` | First accepted MSTORE command to the 64th result handshake, inclusive |
| `input_to_output_span_cycles` | First accepted weight beat to 64th result handshake, inclusive |
| `config_to_output_span_cycles` | Accepted MCFG to 64th result handshake, inclusive |
| `useful_macs` | 16 * 16 * K (one multiply-accumulate is one MAC, not two) |
| `mma_mac_per_cycle` | Useful MACs / MMA latency; not sustained multi-tile throughput |

The inspected FSM predicts MMA latency K+3, i.e. 19/67/259 cycles for
K=16/64/256. The EDA152 run reported below matches this prediction; the probe
warns if a future observed value differs so its boundaries/source can be checked.

Input/output spans include testbench-inserted bubbles. In particular the
existing testbench issues a fresh MSTORE command for each 128-bit result beat.
These spans characterize that schedule, not an optimized host driver or an
ideal one-beat-per-cycle design. `CLK_PERIOD=10` is just a testbench setting;
it does not demonstrate that synthesized hardware reaches 100 MHz.

## EDA152 baseline reported on 2026-09-29

User-provided log excerpt, source commit
`519ac9b25e8d0c5e3eff44103fc32fcb1095a21c`, monitor version 1.
Run directory: `/data/home2/lqq/Desktop/mxu_runs/Yangg152_perf.7x8re7`.
All four cases passed (256/256 output beats). Full compile/run logs have not
been independently reviewed on Windows.

| K | Load span | MMA latency | Readback span | First input to last output | Config to last output | MMA MAC/cycle |
| --- | --- | --- | --- | --- | --- | --- |
| 16 | 34 | 19 | 128 | 186 | 192 | 215.579 |
| 64 | 130 | 67 | 128 | 330 | 336 | 244.537 |
| 256 | 514 | 259 | 128 | 906 | 912 | 253.035 |

All spans/latencies above are hardware clock counts with the counter definitions
above, not simulator seconds. The nonnegative K=16 case repeats the first row.
The mean MAC rate over the input-to-output span is 22.022, 49.648, 72.336,
respectively. MMA latency approaches 256 MAC/cycle as K grows; this is neither
an area-normalized efficiency result nor a sustained multi-tile throughput result.

## Official same-vector workload (Ubuntu VM)

New verification-only files in `coralnpu-google/tests/cocotb/vme_test/`:
`vme_matrix_perf_program.cc` and `vme_matrix_perf_bench.py`. No RTL is modified.
They reuse the cached `VmeCoreMiniAxi` Verilator model. First check negative-B
arithmetic and Tk=1/2/3/4, int8 extrema and all four sign quadrants (9 cases).
Then execute the four existing fork vector sets, each three times from reset.
The Python RNG, draw order and int8 dtype exactly match `golden.py`.

In the Ubuntu VM, keep the working proxy environment active:

```bash
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
python verification/check_google_matrix_vectors.py
cd coralnpu-google
```

Stop if any of those steps fails. Then run the diagnostic first:

```bash
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=all \
  //tests/cocotb/vme_test:vme_matrix_perf_vme_matrix_signed_diagnostic_test
```

Only after it passes, run the baseline:

```bash
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=all \
  //tests/cocotb/vme_test:vme_matrix_perf_vme_matrix_common_perf_test
```

Preserve the Git revision and Bazel test logs. Expect 9 diagnostic or 12 common
`[GOOGLE_MATRIX_PERF]` JSON records plus the corresponding `[GOOGLE_MATRIX_CHECK]`
success line. Every record is printed only after all 256 elements match NumPy.
Failures are not performance results. An altfmt/Tk CSR readback is checked too,
but arithmetic matching, not CSR readback, is the correctness gate.

Timing field `launch_wait_to_halt_cycles` uses the existing fixture: count
`io_aclk` cycles from return of `execute_from()` until `io_halted` is observed.
It includes remaining program startup, tile zero/configuration, eight vector
loads per matrix instruction, loop/control/dispatch, matrix execution,
16 tile-row moves/stores and shutdown. AXI upload of inputs, Python transpose
and host result download are **outside** this timing. It is not an optimized
software kernel. Tk<4 diagnostics deliberately load all four slots to check
masking; do not use them to rank optimized Tk modes.

This is a same-workload functional/core-schedule baseline, **not** a matched
standalone-engine performance comparison. Do not divide its cycles by the
fork's MMA-only cycles and declare a winner. Engine counters and a comparable
system interface/driver benchmark are still required.

## Remaining comparison work

Use common vectors and complete 16x16xK workloads on both designs, count
compute and transfer phases with clearly matched endpoints, include negative
B operands, and then synthesize the relevant blocks using the same process
library and constraints. Keep hardware cycle counts separate from simulator
wall-clock runtime. The old official test-program comments about `altfmt`
being unwritable and Tk being only two bits contradict the current RTL:
negative-B arithmetic and Tk=4 require explicit tests before support is
reported. Neither test comments nor configuration readback alone establish
arithmetic correctness.

## Local validation status

The observer was checked against the current source and the special first-beat
protocol. The shell script passed `bash -n` using the existing Git Bash.
A compatible simulator was not available on the Windows host. EDA152 has now
run the fork observer successfully according to the user-provided excerpt.
The new official workload still needs RISC-V compilation and RTL simulation
in the Ubuntu VM. `check_google_matrix_vectors.py` checks vector equality and
scalar references only; it is not hardware validation.
