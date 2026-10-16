# Coral_matrix

This repository keeps two Coral NPU codebases side by side for comparison and development:

- `coralnpu-google/`: based on <https://github.com/google-coral/coralnpu>
- `coralnpu-Yangg152/`: based on <https://github.com/Yangg152/coralnpu>

## Work record and handoff

The detailed Chinese [work record and takeover guide](verification/WORKLOG-and-handover.md)
covers environment setup, Git/proxy workflows, functional failures and passes,
full-core performance results, RTL package identities, and pending work.
For the current synthesis RTL package, use the
[simulated-RTL handoff](verification/HANDOFF-simulated-rtl.md); do not substitute
the older `prod` package with a different instruction-fetch configuration.

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
has a user-reported RTL pass for the 32 KiB/T12/zero-extra-read-delay pilot,
recorded in [workset results](verification/google_tcm_capacity/WORKSET-results.md).
Cross-capacity benefit measurements remain pending; the pilot compares residency
strategies at the same capacity.

## Windows compatibility

The Google repository contains both `SRAM.scala` and `Sram.scala`. Windows uses a
case-insensitive filesystem, so the latter is stored here as `SramBlock.scala` and
the matching Bazel source entry has been updated.
