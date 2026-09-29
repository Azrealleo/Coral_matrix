"""Pure-Python accounting for the current VLEN128, full-tile INT8 PE array.

Samples describe signals BEFORE the rising edge that accepts work/writes MT.
No simulator dependencies: synthetic traces can unit-test the accounting.
This is deliberately fail-closed and only supports tile 0, M=N=16, Tk=4.
"""

from collections import deque


class ArrayCounter:
    def __init__(self):
        self.cycle = -1
        self.commands = []
        self.issue_command = None
        self.pending = [deque() for _ in range(4)]
        self.flags = []

    def step(self, sample):
        self.cycle += 1
        cycle = self.cycle
        if not sample["rst_n"]:
            assert not self.commands, "Reset after matrix work began"
            return
        if sample["flush"]:
            assert self.issue_command is None and all(not queue for queue in self.pending), "Flush with matrix work in flight"
            self.flags.append((cycle, False, False, False, bool(sample["busy"])))
            return
        issue = bool(sample["blkCmdVld"] & sample["blkCmdRdy"] & 1)
        offered = sample["peCmdVld"] == 15
        consumed = (sample["peCmdVld"] & sample["peCmdRdy"]) == 15
        self.flags.append((cycle, offered, bool(sample["hitRaw"]), issue, bool(sample["busy"])))

        if issue:
            assert offered and sample["canStart"], "PE issue without a full command"
            cnt = sample["cnt"]
            if cnt == 0:
                assert self.issue_command is None, "New command before previous strips finished"
                command = {
                    "start": cycle, "strip_count": 0, "consumed": None,
                    "block_end": [None] * 4, "addresses": set(), "pc": None,
                    "block_addresses": [set() for _ in range(4)],
                }
                index = len(self.commands)
                self.commands.append(command)
                self.issue_command = index
                for queue in self.pending:
                    queue.append(index)
            assert self.issue_command is not None, "Strip without a command start"
            command = self.commands[self.issue_command]
            assert cnt == command["strip_count"], "Skipped/repeated M strip"
            command["strip_count"] += 1
            if cnt == 3:
                assert consumed, "Last strip did not consume the command"
                command["consumed"] = cycle
                self.issue_command = None
            else:
                assert not consumed, "Command consumed before its last strip"
        elif consumed:
            raise AssertionError("Command consumed without a PE strip issue")

        writes = sample["writeEn"]
        if writes:
            # zvt_ctrl arbitrates PE vs zero/move/load writes. Confirm the PE's
            # writes really reach MT at this edge, not merely the adder output.
            assert writes == sample["mtWriteEn"], "PE writes suppressed/changed by MT arbitration"
        for block in range(4):
            block_mask = (writes >> (block * 64)) & ((1 << 64) - 1)
            retire = bool(sample["peRtVld"] & (1 << block))
            if not block_mask:
                assert not retire, "Retire without a final MT write"
                continue
            assert self.pending[block], "MT write without a pending matrix command"
            command = self.commands[self.pending[block][0]]
            pc = (sample["writePc"] >> (block * 32)) & 0xFFFFFFFF
            if command["pc"] is None:
                command["pc"] = pc
            assert command["pc"] == pc, "Instruction PC changed within one matrix command"
            for port in range(4):
                mask = (block_mask >> (port * 16)) & 0xFFFF
                flat_port = block * 4 + port
                mt = (sample["writeMtIdx"] >> (flat_port * 4)) & 15
                sub = (sample["writeSubIdx"] >> (flat_port * 4)) & 15
                assert not mask or mt in range(4), "Writes outside logical tile 0"
                for word in range(4):
                    assert ((mask >> (word * 4)) & 15) in (0, 15), "Partial INT32 write"
                for byte in range(16):
                    if mask & (1 << byte):
                        address = (mt, sub, byte)
                        assert address not in command["addresses"], "Duplicate tile-byte write"
                        command["addresses"].add(address)
                        command["block_addresses"][block].add(address)
            count = len(command["block_addresses"][block])
            assert count <= 256, "More than one quadrant written for a command"
            if count == 256:
                assert retire, "Full quadrant write missing final-strip retire"
                command["block_end"][block] = cycle
                self.pending[block].popleft()
            else:
                assert not retire, "Retired before all quadrant bytes were written"

    def summary(self, k):
        assert k in (16, 64, 256)
        assert len(self.commands) == k // 4, "Wrong number of matrix commands"
        assert self.issue_command is None and all(not queue for queue in self.pending), "Incomplete matrix command"
        intervals = []
        latencies = []
        for command in self.commands:
            assert command["strip_count"] == 4 and command["consumed"] is not None
            assert all(end is not None for end in command["block_end"])
            assert len(command["addresses"]) == 1024, "Incomplete full-tile write coverage"
            end = max(command["block_end"])
            assert end >= command["consumed"] >= command["start"]
            intervals.append((command["start"], end))
            latencies.append(end - command["start"])
        first = intervals[0][0]
        last = max(end for _, end in intervals)
        elapsed = last - first
        assert elapsed > 0
        # Union of half-open [first issue, final write) intervals. Summing
        # per-command latency would double-count overlapping pipeline work.
        union = 0
        lo, hi = intervals[0]
        for start, end in intervals[1:]:
            if start <= hi:
                hi = max(hi, end)
            else:
                union += hi - lo
                lo, hi = start, end
        union += hi - lo
        flags = [row for row in self.flags if first <= row[0] < last]
        assert len(flags) == elapsed, "Missing clock samples in the array window"
        starts = [start - first for start, _ in intervals]
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        return {
            "probe_version": 1,
            "scope": "array_first_strip_issue_to_final_committed_tile_write",
            "matrix_commands": len(self.commands), "useful_macs": 256 * k,
            "tile_bytes_written": len(self.commands) * 1024,
            "array_schedule_elapsed_cycles": elapsed,
            "array_schedule_mac_per_cycle": round(256 * k / elapsed, 6),
            "command_latency_cycles": latencies,
            "command_start_offsets": starts,
            "command_consumed_offsets": [c["consumed"] - first for c in self.commands],
            "command_final_write_offsets": [end - first for _, end in intervals],
            "command_block_final_write_offsets": [[end - first for end in c["block_end"]] for c in self.commands],
            "command_start_intervals": gaps,
            "command_active_union_elapsed_cycles": union,
            "no_command_inflight_elapsed_cycles": elapsed - union,
            "no_full_command_offered_cycles": sum(not row[1] for row in flags),
            "raw_wait_cycles": sum(row[1] and row[2] for row in flags),
            "full_offer_no_strip_no_raw_cycles": sum(row[1] and not row[2] and not row[3] for row in flags),
            "block0_strip_issue_cycles": sum(row[3] for row in flags),
            "array_busy_cycles_in_window": sum(row[4] for row in flags),
        }
