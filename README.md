# Coral_matrix

This repository preserves the original two-codebase evaluation and the ongoing
official CoralNPU verification work. The team has selected the official version;
the Yangg152 comparison is historical, not the current workstream.

- `coralnpu-google/`: based on <https://github.com/google-coral/coralnpu>
- `coralnpu-Yangg152/`: based on <https://github.com/Yangg152/coralnpu>

## Work record and handoff

Current task (2026-10-19): one NPU with **512 KiB DTCM**, a complete pretrained
**two-class MobileNetV1 person-detection** model, and ITCM assessed from firmware
up to 512 KiB. See the [active model and firmware-resource step](verification/google_person_detect/README.md).
The original model has a desktop LiteRT metadata-compatibility failure; the
pinned native TFLM host test and firmware link/audit are the next VM commands,
not completed passes. The [1001-output model and host golden](verification/google_mobilenet_v1/README.md)
are preserved for later. No NPU model-inference or accuracy pass is claimed.
The capacity sweeps below remain historical, not the default next run.

Start with the Chinese [current handoff guide](verification/HANDOFF-current.md),
updated through 2026-10-19. It identifies the exact resumption point, environments,
immutable packages, accepted results, pending runs, and safe commands.
The detailed Chinese [full work record](verification/WORKLOG-and-handover.md)
covers environment setup, Git/proxy workflows, functional failures and passes,
full-core performance results, RTL package identities, and pending work.
For the historical 2026-10-04 synthesis package, use the
[simulated-RTL handoff](verification/HANDOFF-simulated-rtl.md). Its older upstream
and 8/32 KiB configuration are distinct from the newer TCM experiment; do not
substitute the `prod` package with different instruction-fetch settings.

## Official single-NPU memory study

The [ITCM/DTCM capacity experiment](verification/google_tcm_capacity/README.md)
uses the team's newer pinned official source and generation fixes. Stage 1
qualifies six DTCM capacities (32 KiB through 4 MiB) with ITCM fixed at 8 KiB;
it is not yet a workload-performance result or a SoC configuration change.
All six capacity runs have user-reported RTL passes, recorded in
[stage 1 results](verification/google_tcm_capacity/STAGE1-results.md).
The [same-ELF small-workset control](verification/google_tcm_capacity/CONTROL.md)
also has six user-reported RTL passes with identical cycle counts, recorded in
[control results](verification/google_tcm_capacity/CONTROL-results.md).
The six full control logs have also passed cross-capacity auditing on Ubuntu.
The [fixed-order weight-residency experiment](verification/google_tcm_capacity/WORKSET.md)
has accepted Ubuntu T12 results at 32/128 KiB and 1 MiB, plus complete paired
T384 results at 1/2 MiB. The same prefix strategy uses 17.07% fewer cycles at
2 MiB for T384, with 40.92% fewer external weight bytes. This is a fixed-schedule
synthetic workload, not a complete model or a 4 MiB benefit claim. Exact results,
measurement boundaries and log paths are in [workset results](verification/google_tcm_capacity/WORKSET-results.md).

The [standalone VCS export flow](verification/google_tcm_vcs/README.md) prepares
fixed ITCM8 KiB / DTCM1, 2 or 4 MiB packages on Ubuntu. The CentOS7 server compiles
and runs them without Bazel. It preserves the original RTL, firmware, SRAM DPI
source and cocotb checks. All three exports are verified; server VCS 1 MiB T12/T384
and 2 MiB T12 have passed. The 2 MiB T384 job was started, but its completion has
not been reported. No server 4 MiB run is confirmed.

The [standalone server Verilator flow](verification/google_tcm_verilator/README.md)
has passed the corrected 1 MiB T12 test with exact VCS-reference agreement. It
reused the existing model and ran in 429.077 seconds versus the previous normal
VCS run's 1178.5 seconds on the same server (about 2.75x for this configuration).
The earlier trace-launch failure is retained separately. Server Verilator 1 MiB
T384 has now also passed with exact VCS-reference agreement in 13979.842 seconds
(about 3h53m). The earlier server VCS run took 37619.46 seconds, while the VM's
Verilator Bazel test took 6736.5 seconds. These are observed workflow timings,
not isolated CPU/engine benchmarks. Next: qualify each new capacity's own model
and T12 before the 2/4 MiB T768 pair. Compilation or local tool tests alone are
still not RTL simulation passes.
The separate [ITCM sweep tools](verification/google_itcm_capacity/README.md) are
prepared but paused, with no reported RTL pass. The current DTCM runs keep ITCM
at 8 KiB. Real-model, physical SRAM timing, 200 MHz and gate-level validation
remain outside the completed evidence.

## Windows compatibility

The Google repository contains both `SRAM.scala` and `Sram.scala`. Windows uses a
case-insensitive filesystem, so the latter is stored here as `SramBlock.scala` and
the matching Bazel source entry has been updated.
