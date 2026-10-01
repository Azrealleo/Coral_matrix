#!/usr/bin/env python3
"""Measure MXU weight-SRAM reuse within the same fork core and batch ELF."""

import argparse
import json
from pathlib import Path

from compare_fullcore_batch import parse_rows, validate
from mxu_fullcore_tile_vectors import shared_weight_batch_cases


def compare(reuse_records, reload_records):
    cases = shared_weight_batch_cases()
    reuse, reuse_digest = validate(reuse_records, cases, "fork")
    reload, reload_digest = validate(reload_records, cases, "fork_reload")
    assert reuse_digest == reload_digest
    rows = []
    for a, b in zip(reuse, reload):
        key = ("case", "K", "tiles", "logical_sha256", "useful_macs")
        assert tuple(a[k] for k in key) == tuple(b[k] for k in key)
        ac = a["launch_wait_to_halt_cycles"]
        bc = b["launch_wait_to_halt_cycles"]
        rows.append(dict(case=a["case"], K=a["K"], tiles=a["tiles"],
                         reuse_cycles=ac, reload_cycles=bc,
                         cycles_saved_by_reuse=bc - ac,
                         reuse_over_reload_cycle_ratio=round(ac / bc, 6),
                         scope="same_fork_core_ELF_vectors_one_launch_only_weight_reload_flag_differs"))
    return rows, reuse_digest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reuse_log")
    parser.add_argument("reload_log")
    args = parser.parse_args()
    reuse_log = Path(args.reuse_log).read_text(encoding="utf-8")
    reload_log = Path(args.reload_log).read_text(encoding="utf-8")
    assert "[YANGG_BATCH_CHECK] cases=9 repeats=3 passed" in reuse_log
    assert "[YANGG_BATCH_RELOAD_CHECK] cases=9 repeats=3 passed" in reload_log
    rows, digest = compare(parse_rows(reuse_log, "[YANGG_BATCH] "),
                           parse_rows(reload_log, "[YANGG_BATCH_RELOAD] "))
    print("[FORK_WEIGHT_REUSE_MANIFEST] cases=9 repeats=3 logical_set_sha256=" + digest)
    for row in rows:
        print("[FORK_WEIGHT_REUSE_PAIR] " + json.dumps(row, sort_keys=True))
