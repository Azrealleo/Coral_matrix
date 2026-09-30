# Paired signed-INT8 full-core tile benchmark

This is the first **same-endpoint** cycle comparison between these checkouts.
It is still not a complete AI model, physical timing result or perfectly
identical SoC: official uses `VmeCoreMiniAxi`/ZVT, the fork uses
`RvvCoreMiniAxi`/MXU, and their legal instruction streams differ. It answers:
*how many simulated full-core launch-to-halt cycles does each implementation's
driver require for the same seven signed-INT8 logical tile tasks?*

Both sides run the seven cases from `README-model-tile.md`, repeat each case
three times, check **all 256 physical INT32 outputs**, and measure
`run_to_halt` after loading the ELF and inputs. The official side runs both
its older diagnostic Tk=1 schedule and a new Tk=4 schedule with K zero-padded
to 4; **Tk=4 is the primary official cycle baseline**. The fork's new C++ program
uses the repository's existing MXU instruction encodings and its real wrapper;
non-aligned K is explicitly zero-padded to 16. Official Tk=4 reuses the
existing parameterized ELF, with no official RTL change. The fork's pinned, patched TFLite
Micro archive now replaces the author's hard-coded `/home/yang` local checkout
in WORKSPACE. The fork's `rules_java` is pinned to the 9.6.1 archive already
used by the successfully built official checkout because the older fork pin
lacks `java:rules_java_deps.bzl`; functional RTL and production software are
untouched.

The same logical A/B/C fingerprint set must equal
`87085fb87e02f0b4d28c7de2aa256e55df836807842fe899538367211c72fbda`.
Local `check_fullcore_fair.py` verifies byte-for-byte shared vectors, fork
padding/packing and strict paired-log validation. **It does not run RTL or
cross-compile the new fork ELF.**

## Ubuntu VM

Use the VM that already builds the official repository. Keep its proxy
available; stop if Git or any command fails. The official Tk=1 log is the
previous successful model-tile run. Verify it, then run official Tk=4 before
starting the fork:

```bash
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
git rev-parse --short HEAD
conda run -n coral-matrix python verification/check_fullcore_fair.py
test -f coralnpu-google/bazel-testlogs/tests/cocotb/vme_test/vme_matrix_model_tile_vme_matrix_model_tile_test/test.log
cd coralnpu-google
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=all \
  //tests/cocotb/vme_test:vme_matrix_tk4_tile_vme_matrix_tk4_tile_test
cd ../coralnpu-Yangg152
bazel build --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  //tests/mxu:mxu_fullcore_tile_program
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=all \
  //tests/mxu:mxu_fullcore_tile_mxu_fullcore_tile_test
```

The first fork build may download a separate toolchain and cached
dependencies; do **not** run `bazel clean`. The `bazel build` checkpoint makes
compilation failures easier to diagnose before the Verilator core simulation.
If the target naming differs, run `bazel query '//tests/mxu:*fullcore*'` and
share its output; do not guess at an unrelated test.

Only after the fork test passes, pair both complete logs:

```bash
cd "$HOME/桌面/Coral_matrix"
conda run -n coral-matrix python verification/compare_fullcore_tiles.py \
  coralnpu-google/bazel-testlogs/tests/cocotb/vme_test/vme_matrix_model_tile_vme_matrix_model_tile_test/test.log \
  coralnpu-google/bazel-testlogs/tests/cocotb/vme_test/vme_matrix_tk4_tile_vme_matrix_tk4_tile_test/test.log \
  coralnpu-Yangg152/bazel-testlogs/tests/mxu/mxu_fullcore_tile_mxu_fullcore_tile_test/test.log
```

Return `[FULLCORE_PAIR_MANIFEST]` and all seven `[FULLCORE_PAIR]` lines, or
the **first** build/test error plus its log path. The ratio field is strictly
`official Tk=4 simulated cycles / fork simulated cycles` for this particular
program and fixture endpoint—not measured silicon speedup. The same nominal
1.25 ns simulator clock and 4 MiB external-memory backing are used, but
different core RTL, toolchains, instruction counts, memory transactions,
physical Fmax, area, power and model-software dispatch remain confounders.
Record those before a SoC choice. A test pass must not be inferred from a
compiler success alone.
