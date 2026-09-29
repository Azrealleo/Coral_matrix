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

## Official core baseline reported after commit 2113cf3

The signed diagnostic target passed, followed by all four common cases x three
repeats. The user supplied the 12 `[GOOGLE_MATRIX_PERF]` records: all repeats
were identical and all four vector fingerprints matched the local static check.
This is a user-reported RTL result, not a Windows simulation run.

| K | Official launch-wait-to-halt cycles | MAC / that cycle window |
| --- | --- | --- |
| 16 | 432 | 9.481481 |
| 64 | 722 | 22.692521 |
| 256 | 1876 | 34.933902 |

The nonnegative K=16 case repeats the first row. Negative-B and Tk=4 arithmetic
are now confirmed **for the executed cases/configuration**, not all ISA modes.

## Official array observer (Ubuntu VM, new model)

The ordinary compiled model exposes top-level ports, not the array's internal
signals. The new `vme_matrix_engine_model` uses the same generated SV and compile
defines, plus a **selective visibility-only** `zvt_perf.vlt.tpl`. The original
model and its cache are untouched; the new model requires one initial compile.
No function RTL or RISC-V program is changed. Do not run `bazel clean`.

```bash
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
python verification/check_google_array_counter.py
cd coralnpu-google
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=all \
  //tests/cocotb/vme_test:vme_matrix_engine_vme_matrix_engine_profile_test
```

Stop on any error. After the target passes, extract four compact summaries:

```bash
python ../verification/summarize_google_array.py \
  bazel-testlogs/tests/cocotb/vme_test/vme_matrix_engine_vme_matrix_engine_profile_test/test.log
```

Preserve the full test log. The summarizer requires all 12 array records, matched
fingerprints and identical repeats before printing any summaries. Missing VPI
signals, unsupported geometry, protocol inconsistencies or missing writes fail
the test; no fallback estimate is emitted.

### Observer boundaries and guards

Scope is limited to the tested VLEN128, tile 0, M=N=16, signed-A INT8, Tk=4
workload. One matrix instruction performs 1024 MACs and writes 1024 bytes of
INT32 tile results. It issues four M strips to block 0 and propagates through
four quadrant blocks. `peCmdRdy` consumes the queued command on the **last**
strip, so that handshake alone is not its execution-start boundary.

The observer captures settled signals at the array's falling clock edge and
accounts for them at the following rising edge. This avoids Verilator's
post-evaluation RisingEdge sampling counting the next edge's work. The observed
array has only rising-edge sequential logic; this method is not a generic
asynchronous-interface monitor.

Start = first `blkCmdVld[0] && blkCmdRdy[0]` issue with `cnt=0`.
End = rising edge committing the last of 1024 **unique** enabled tile bytes for
that instruction, after all four blocks complete. The monitor checks each
block's 256-byte coverage, full INT32 word masks, consistent instruction PC,
final-strip retire, and equality of the PE write enables and the `zvt_ctrl`
write enables actually sent to MT. It rejects reset after work starts and
flush while a measured matrix command is in flight; idle flush is ignored.
All cycles are elapsed clock **intervals** (end-start), not inclusive spans.

| Field | Meaning |
| --- | --- |
| `command_latency_cycles` | First strip to that instruction's last committed Tile write |
| `command_start_intervals` | Difference between successive instruction start edges under the existing program |
| `array_schedule_elapsed_cycles` | First instruction start to the workload's final Tile write; includes gaps between supplied commands |
| `command_active_union_elapsed_cycles` | Union of command-in-flight intervals, avoiding double counting overlapped pipelines |
| `no_command_inflight_elapsed_cycles` | Array window minus that union; scheduling gaps with no measured command in flight |
| `no_full_command_offered_cycles` | Cycles without all four PE-command lanes offered; includes final pipeline drain and controller/upstream effects |
| `raw_wait_cycles` | A full offer is blocked by the array's `hitRaw` condition |
| `full_offer_no_strip_no_raw_cycles` | Full offer, no RAW condition, no block-0 issue |
| `array_busy_cycles_in_window` | Observed array `busy` cycles inside the elapsed window |

In-flight/busy cycles are **not** PE utilization, energy efficiency or ideal
compute-only throughput. No-offer cycles do not by themselves prove the CPU is
the cause. Start intervals are the delivered intervals of this program, not
the array's minimum sustainable initiation interval. The preloaded/reused-
operand command-stream test below measures a denser same-Tile schedule.

The target also verifies all original golden results, requires the original
432/722/1876/432 core cycles, and compares internal traces across three resets.
If visibility changes core cycles, investigate rather than silently rebasing.
The official per-instruction Tk=4 latency cannot be substituted for the whole
K=16/64/256 workload or directly ranked against the fork's single MMA command.

### Local observer checks

`check_google_array_counter.py` runs 11 **synthetic** unit tests, including
overlapping commands, input gaps, all three K values, offset invariance, and
rejection of lost/duplicate/suppressed writes, incorrect PC, partial INT32
writes, early consume/retire, reset/flush and incorrect command count.
These checks validate accounting, **not** VPI discovery or RTL behavior.
The observer/model has not been compiled or simulated on Windows; the Ubuntu
VM result supplied by the user is recorded below.

### Official array baseline reported on 2026-09-29

The user supplied four summaries from the `vme_matrix_engine_profile_test`
log after the target passed. The summarizer validated all 12 records, vector
fingerprints and identical repeats. The original core-cycle baseline was
preserved. Full simulation logs have not been independently reviewed here.

| K | Matrix commands | Per-command latency | Delivered start interval | Array schedule window | MAC / window cycle | No-command-in-flight intervals |
| --- | --- | --- | --- | --- | --- | --- |
| 16 | 4 | 12 | 24 | 84 | 48.761905 | 36 |
| 64 | 16 | 12 | 24 | 372 | 44.043011 | 180 |
| 256 | 64 | 12 | 24 | 1524 | 43.002625 | 756 |

The nonnegative K=16 case is identical. RAW-wait and full-offer/no-strip/no-RAW
counts are zero in all cases. Active-command unions are 48/192/768 intervals;
busy counts are 47/191/767 because the first issue edge is initially idle and
the observer uses a half-open elapsed window. These are not inconsistent.

The measured starts/ends give `window = 24 * (K/4 - 1) + 12 = 6*K - 12`.
For K=256, 756/1524 (49.61%) of the array window has no matrix command in flight.
This shows a sparse delivered schedule, not the minimum sustainable array
initiation interval. The no-offer count includes controller/upstream behavior
and final drain: it does not isolate a CPU bottleneck. In particular, a
12-cycle command latency does **not** imply one command can start only every
12 cycles, and `1024/12` is not a demonstrated peak MAC rate.

## Official preloaded instruction-stream test

This is a **separate synthetic workload**, not the earlier random common GEMM.
The new `vme_matrix_burst_program.cc` loads one 16x4 A and one 4x16 B chunk
only once. Assembly `.rept` emits 4/16/64 consecutive matrix instructions,
all accumulating Tile 0. No loads or loop branches occur between them.
The harness also checks the observed instruction PCs advance by four bytes.
Logical A/B repeat that same chunk along K; full golden results are the
chunk product multiplied by the command count. The operand fingerprints are
different from the common benchmark and must not be mixed with it.

Signed cases cover K=16/64/256 with both negative and positive operands,
including -128/127. A nonnegative K=16 case checks the altfmt=0 setting.
All 256 output elements must match a widened reference; each case runs three
times from reset. The existing observer checks complete unique MT writes and
command protocol even when commands overlap. A mismatch/protocol failure is
not a usable performance result. This tests same-Tile accumulation dependencies
under dense input, not arbitrary tiles, general GEMM data movement or signoff.

In the Ubuntu VM (keep the existing proxy environment active):

```bash
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
git rev-parse --short HEAD
python verification/check_google_burst.py
python verification/check_google_array_counter.py
cd coralnpu-google
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=all \
  //tests/cocotb/vme_test:vme_matrix_engine_vme_matrix_engine_burst_test
```

Stop if any step fails. This reuses the already compiled selective-visibility
Verilator model; only the new program/test needs building. Do not clean Bazel.
After the target passes:

```bash
python ../verification/summarize_google_array.py --burst \
  bazel-testlogs/tests/cocotb/vme_test/vme_matrix_engine_vme_matrix_engine_burst_test/test.log
```

Keep the full log and repository revision. The summarizer requires the burst
completion marker, all 12 records, correct hashes/schedule/command count/write
coverage/consecutive PCs, and identical repeats. It prints four compact rows.
No fixed throughput is required: measured RAW waits and command intervals are
part of the result, rather than assumed to be zero/four cycles.

`check_google_burst.py` has six local-only tests: reused-chunk guards, independent
scalar references, mocked upload/golden/observer handling, rejection of a wrong
result before logging performance, unchanged common-vector hashes, and strict
summary parsing/rejection. These checks do **not** compile the RISC-V program
or simulate RTL. The Ubuntu VM result supplied by the user is recorded below.

The result will characterize this reused-operand command stream through the
existing core/dispatch path. It is not automatically the array's intrinsic
peak, a general-GEMM end-to-end rate, or a same-interface comparison against
Yangg152. Fmax, area and power comparisons still require matched synthesis.

### Preloaded stream result reported on 2026-09-29

The user supplied four summaries from the burst log. The current summarizer
requires its completion marker, all 12 records, matched hashes, consecutive
instruction PCs and identical repeats before emitting any rows. The test
checks all output elements and complete per-command write coverage before
logging array performance. This is a user-reported RTL result; the complete
log and actual VM revision have not been independently reviewed on Windows.
The supplied test was introduced at commit `ffb6b35`.

| K | Matrix commands | Command latency | Start interval | Array window | MAC / window cycle | Full-core fixture cycles |
| --- | --- | --- | --- | --- | --- | --- |
| 16 | 4 | 12 | 4 | 24 | 170.666667 | 371 |
| 64 | 16 | 12 | 4 | 72 | 227.555556 | 419 |
| 256 | 64 | 12 | 4 | 264 | 248.242424 | 611 |

The nonnegative K=16 case repeats the first row. No-command-in-flight, RAW-wait
and full-offer/no-strip/no-RAW counts are zero. The 8 no-offer intervals in
each window are the final pipeline tail after the last command's four strips,
not gaps between successive starts. Busy is window minus one, using the same
edge/half-open-window convention as the original observer.

`window = 4 * (K/4 - 1) + 12 = K + 8`. Consecutive same-Tile accumulation
overlaps correctly for these inputs, with a demonstrated 4-cycle start
interval. Each Tk=4 instruction performs 1024 MACs, so this cadence corresponds
to 256 useful MAC/cycle in steady state; the measured finite-window averages
remain those in the table and include fill/drain. The four M strips per
instruction issue without bubbles in this tested configuration.

The earlier 24-cycle delivered interval was not an intrinsic 24-cycle array
restriction. This experiment changed the input schedule **and** the vectors
to repeated chunks, so it is not a measured optimization of arbitrary random
GEMM. The reported fork MMA rates (215.579/244.537/253.035) and this stream's
array rates are in the same throughput class, approaching 256 MAC/cycle.
Their different boundaries, interfaces and input patterns prevent using the
small finite-window difference as a definitive winner. Nor may 611 full-core
fixture cycles be compared with 906 fork input/output-span cycles as a fair
system speedup: operand reuse and counted transfers are different.

## Shared signed arithmetic pressure tests

`vme_matrix_stress_vectors.py` defines eight batches: positive/positive,
positive/negative, negative/positive, negative/negative, signed boundary
patterns, a fixed full-range random seed, all -128, and alternating -128/127.
Each batch contains K=16/64/256 signed cases and one nonnegative K=16 case:
32 full 16x16 matrices, 8192 checked INT32 elements per design. The nonnegative
case remains within 0..127; it is **not** proof of full uint8 support.

Both runners use the identical logical A/B and widened golden C. The fork
exporter maps them onto the unchanged `mxu_tb`'s existing four filenames,
stream order and K=256 configuration encoding. Batch SHA256 is computed from
the four logical A/B/C fingerprints in testcase order; compare the server's
eight `[SIGNED_STRESS_MANIFEST]` rows with the VM's eight summary hashes.
The fourth nonnegative matrix is repeated in each batch as a baseline.

First, in the Ubuntu VM:

The standalone check/summarizer uses the terminal's Conda Python, not Bazel's
managed Python/wheel dependencies. The user encountered `ModuleNotFoundError:
No module named 'numpy'` before summary parsing. Install NumPy into the named
environment if needed (2.3.4 matches this checkout's Bazel wheel), then verify:

```bash
conda install -n coral-matrix -c conda-forge "numpy=2.3.4"
conda run -n coral-matrix python -c 'import numpy; print(numpy.__version__)'
```

If the RTL test already passed, do not rerun it just to repair the summarizer.
Use `conda run -n coral-matrix python` for standalone scripts if the activated
shell's `python` does not resolve to the intended environment.

```bash
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
python verification/check_signed_stress.py
cd coralnpu-google
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=all \
  //tests/cocotb/vme_test:vme_matrix_signed_stress_vme_matrix_signed_stress_test
```

Only after it passes, summarize:

```bash
python ../verification/summarize_signed_stress.py \
  bazel-testlogs/tests/cocotb/vme_test/vme_matrix_signed_stress_vme_matrix_signed_stress_test/test.log
```

This reuses the ordinary cached Verilator model and original full-workload
ELF. No new RTL or RISC-V program is needed. It checks arithmetic/configuration
and resets between cases, not the burst schedule or matched system performance.

Then, in EDA152 (keep the SSH proxy tunnel active for Git):

```bash
cd /home2/lqq/Desktop/Coral_matrix
git pull --ff-only origin main
bash verification/run_yangg152_signed_stress.sh \
  /home2/lqq/Desktop/Coral_matrix /home2/lqq/Desktop/mxu_runs
```

Stop on any step's failure. The server script creates a fresh run directory,
generates HEX plus `manifest.json`, compiles the unchanged fork RTL/testbench
once, then executes eight fresh processes. Each run has a 120-second timeout,
requires four 64/64 passing output-beat rows and PASS=256/FAIL=0, and rejects
runtime warnings/errors. Review compile warnings separately. It does not enable
the known failing true-uint8 diagnostic or FSDB. Existing results are preserved.
The final marker is `[YANGG_SIGNED_STRESS_CHECK] ... checked_elements=8192 passed`.

Keep revision, source hashes, manifest, compile log and all run logs. Five
local synthetic checks cover scalar references, signs/shapes, exact HEX
roundtrip/config encoding, no-overwrite behavior, official-reference hash
agreement, deterministic batch hashes and strict summary parsing. Shell syntax
was checked with Git Bash. These are **not** RTL pressure tests themselves.
They still do not cover partial K/tiles, ready/valid backpressure, mid-operation
reset, continuous accumulation across different loaded matrices, overflow
semantics, all opcodes or synthesis/signoff.

### EDA152 signed pressure result reported on 2026-09-30

The user supplied all eight `[YANGG_SIGNED_STRESS]` PASS rows and the final
`batches=8 cases=32 checked_elements=8192 passed` marker. Reported directory:
`/data/home2/lqq/Desktop/mxu_runs/Yangg152_signed_stress.f9j80n`.
All four sign combinations, signed edges, random seed 137, all -128 and
alternating extrema passed under the existing fork schedule. The script
and suite were introduced at `4f03352`; the actual server revision and full
compile/run logs have not been independently reviewed here.

### Paired signed pressure result reported on 2026-09-30

After fixing the terminal NumPy dependency, the user supplied all eight
`[GOOGLE_SIGNED_STRESS_SUMMARY]` rows and the eight server manifest rows.
The current official summarizer requires the completion marker, all 32
unique testcase records, correct element counts and logical vector hashes
before emitting any rows. Each batch hash matched its server counterpart:

| Batch | Identical SHA256 on both hosts |
| --- | --- |
| positive_positive | `58d8d2697423a1782f17fae699f02a344abf777625ebc9d9bbbd75f6a4136245` |
| positive_negative | `291a0f7171d4057f1bfb43065cafd6b334ce28ebfcad4dbca77890c55e068f09` |
| negative_positive | `ab36dfccc926b0c3ee5b6fd8b24b932c8d3e62e98fca054a1dfd0735ad8cbbfb` |
| negative_negative | `db9d79e4c5d16503d739c40a58395455b7cc224ad3c19f93f5d0a9880853d824` |
| signed_edges | `8260cbea8dd6576c2eab67143e4bcb28af513506bb8f6cdb281fccce142bde41` |
| random_seed137 | `ec4d6d1feceb63a1b616065d63150cb8d2c579ca399179a94028914e16c3772b` |
| all_minus128 | `fc271b0bfeaeaee5789e6b3f562e79c8685ab6439577531dda41fdc432a83ec9` |
| alternating_extremes | `c06a5c82b88e62355df290f74248e22b67494d5f4fa98af4177487b3f57f0d15` |

This closes the paired functional check for the 32 shared testcase instances:
8192 INT32 elements passed **per design** (16384 across the two runs), with
identical logical operands/goldens. The repeated fourth baseline is not eight
different matrices. This is a user-reported RTL result, not a Windows RTL run;
the full host logs and actual revisions have not been independently reviewed.
It does not validate all signed workloads or remove the coverage gaps above.

The next independent diagnostic covers arbitrary K and input/output stalls;
see `README-mxu-boundary.md`. Its local exporter/harness checks are complete,
but neither new RTL target has been compiled/simulated on Windows or reported
by the user yet. Do not count those diagnostics as passed.

## Remaining comparison work

Use common vectors and complete 16x16xK workloads on both designs, count
compute and transfer phases with clearly matched endpoints, include negative
B operands, and then synthesize the relevant blocks using the same process
library and constraints. Keep hardware cycle counts separate from simulator
wall-clock runtime. The old official test-program comments about `altfmt`
being unwritable and Tk being only two bits contradict the current RTL:
the executed diagnostics and burst cases confirm negative-B arithmetic and
Tk=4 for their tested configurations. Broader modes still require explicit
coverage. Neither test comments nor configuration readback alone establish
arithmetic correctness.

## Local validation status

The observer was checked against the current source and the special first-beat
protocol. The shell script passed `bash -n` using the existing Git Bash.
A compatible simulator was not available on the Windows host. EDA152 has now
run the fork observer successfully according to the user-provided excerpt.
The official common workload and signed diagnostics have passed on the VM
according to the supplied results. The selective-visibility observer has
passed according to the supplied summaries. The reused-operand burst test
has also passed according
to the user's four validated summaries. The shared signed pressure suite has
passed on both hosts according to the supplied 32-case results and eight
identical cross-host batch fingerprints. Its standalone summarizer's initial
missing NumPy dependency is documented above and is now resolved.
`check_google_matrix_vectors.py` checks vector equality and scalar references
only; it is not hardware validation.
