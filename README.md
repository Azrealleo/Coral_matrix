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

## Windows compatibility

The Google repository contains both `SRAM.scala` and `Sram.scala`. Windows uses a
case-insensitive filesystem, so the latter is stored here as `SramBlock.scala` and
the matching Bazel source entry has been updated.
