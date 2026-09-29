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
K=16/64/256. This is a **static prediction**, not a measured result; the probe
warns if the observed value differs so its boundaries/source can be checked.

Input/output spans include testbench-inserted bubbles. In particular the
existing testbench issues a fresh MSTORE command for each 128-bit result beat.
These spans characterize that schedule, not an optimized host driver or an
ideal one-beat-per-cycle design. `CLK_PERIOD=10` is just a testbench setting;
it does not demonstrate that synthesized hardware reaches 100 MHz.

## Next comparison stage

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
A compatible simulator was not available on the Windows host, so
VCS compilation and observed counts still need the EDA152 run above.
