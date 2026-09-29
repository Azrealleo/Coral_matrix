#!/usr/bin/env python3
"""Validate 12 observer records and print four compact console summaries."""

import json
from pathlib import Path
import sys

HASHES = {
    "tc1_tk16": "0b83744e50e117938f5171279af42e4089d4e2b8e65ee99f161c662a0de106b9",
    "tc2_tk64": "cc2af619ea54e0e13ef8179b79ad3445de069c353d9c94f5156f332811d73c23",
    "tc3_tk256": "646408f38ed740f164f2429117262201f64659757b6504d0f6299ecce2c7205d",
    "tc4_unsigned": "2d3322739a606b23aa3ab195b34a754cd3ed4ee4e26a8048d8efe138160b0ccc",
}
BURST_HASHES = {
    "burst_signed_k16": "84882972f41abfaedf7b290ed649c7aa88856face413c1ef963a34f36986fbbe",
    "burst_signed_k64": "4b8d8f349862e4e662513141e50e6f185357ec8add8d425f9b7b33a68fad2238",
    "burst_signed_k256": "0cdc4ae60644ce8b12933be81bb9119b8f63320ab007691b912a0317e8c96061",
    "burst_nonnegative_k16": "6ed7f9b1a37fe47838be738b50cfbefb7283046d71357ef209c560aea0f627a5",
}
COMMON_SCHEDULE = "existing_common_program_vector_loads_per_command"
BURST_SCHEDULE = "preloaded_reused_operands_straight_line_same_tile"


def summarize(records, hashes=HASHES, input_schedule=COMMON_SCHEDULE):
    assert len(records) == 12, f"Expected 12 array records, got {len(records)}"
    assert {row["case"] for row in records} == set(hashes)
    summaries = []
    for name, fingerprint in hashes.items():
        rows = sorted((row for row in records if row["case"] == name), key=lambda row: row["repeat"])
        assert [row["repeat"] for row in rows] == [0, 1, 2], f"{name}: missing/duplicate repeats"
        first = rows[0]
        for row in rows:
            assert row["vector_sha256"] == fingerprint
            assert row["scope"] == "array_first_strip_issue_to_final_committed_tile_write"
            assert row["input_schedule"] == input_schedule
            assert row["K"] in (16, 64, 256) and row["probe_version"] == 1
            assert row["matrix_commands"] == row["K"] // 4
            assert row["useful_macs"] == 256 * row["K"]
            assert row["tile_bytes_written"] == 256 * row["K"]
            if input_schedule == BURST_SCHEDULE:
                assert row["command_pc_offsets_bytes"] == [4 * i for i in range(row["matrix_commands"])]
            assert {key: value for key, value in row.items() if key != "repeat"} == {
                key: value for key, value in first.items() if key != "repeat"
            }, f"{name}: changed counters across repeats"
        latency = first["command_latency_cycles"]
        gaps = first["command_start_intervals"]
        assert len(latency) == first["matrix_commands"] and len(gaps) == len(latency) - 1
        result = {key: first[key] for key in (
            "case", "K", "input_schedule", "matrix_commands", "launch_wait_to_halt_cycles",
            "array_schedule_elapsed_cycles", "array_schedule_mac_per_cycle",
            "command_active_union_elapsed_cycles", "no_command_inflight_elapsed_cycles",
            "no_full_command_offered_cycles", "raw_wait_cycles",
            "full_offer_no_strip_no_raw_cycles", "block0_strip_issue_cycles",
            "array_busy_cycles_in_window",
        )}
        result.update(
            repeats=3, latency_min=min(latency), latency_max=max(latency),
            start_interval_min=min(gaps), start_interval_max=max(gaps),
            start_interval_mean=round(sum(gaps) / len(gaps), 6),
        )
        summaries.append(result)
    return summaries


def main():
    burst = len(sys.argv) == 3 and sys.argv[1] == "--burst"
    if not burst and len(sys.argv) != 2:
        raise SystemExit("Usage: python verification/summarize_google_array.py [--burst] PATH_TO_TEST_LOG")
    marker = "[GOOGLE_ARRAY_BURST_PERF] " if burst else "[GOOGLE_ARRAY_PERF] "
    log = Path(sys.argv[-1]).read_text(encoding="utf-8")
    assert ("[GOOGLE_ARRAY_BURST_CHECK] 4 reused-chunk cases x 3 repeats passed" if burst else
            "[GOOGLE_ARRAY_CHECK] 4 common cases x 3 repeats passed") in log, "Missing completion marker"
    records = [json.loads(line.split(marker, 1)[1])
               for line in log.splitlines() if marker in line]
    # Validate every record BEFORE emitting any summary.
    summaries = summarize(records, BURST_HASHES, BURST_SCHEDULE) if burst else summarize(records)
    for row in summaries:
        print(("[GOOGLE_ARRAY_BURST_SUMMARY] " if burst else "[GOOGLE_ARRAY_SUMMARY] ")
              + json.dumps(row, sort_keys=True))


if __name__ == "__main__":
    main()
