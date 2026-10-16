"""Actual NPU external copies + matrix outputs, not host-preloaded weights in TCM."""
import hashlib
import json
import os
from pathlib import Path

import cocotb
import numpy as np
from bazel_tools.tools.python.runfiles import runfiles
from elftools.elf.elffile import ELFFile
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture

from capacity_spec import DTCM_BASE, geometry
from workset_spec import (DELAYS, EXT_A, EXT_B, EXT_OUT, EXT_BYTES, K, LOW_DTCM_BYTES,
                          REPEATS, ROUNDS, SCOPE, STRATEGIES, SYMBOL_SIZES,
                          TILE_CHOICES, WEIGHT_BYTES, check_elf_layout, plan, vectors)
from workset_axi_probe import WorksetAxiProbe


def inspect_elf(path):
    with open(path, "rb") as stream:
        elf = ELFFile(stream)
        segments = [(int(s["p_paddr"]), int(s["p_memsz"])) for s in elf.iter_segments()
                    if s["p_type"] == "PT_LOAD"]
        table = elf.get_section_by_name(".symtab")
        symbols, sizes = {}, {}
        for name in SYMBOL_SIZES:
            found = table.get_symbol_by_name(name)
            assert found and len(found) == 1, "missing/duplicate ELF symbol: " + name
            symbols[name], sizes[name] = int(found[0]["st_value"]), int(found[0]["st_size"])
        entry = int(elf.header["e_entry"])
    check_elf_layout(entry, segments, symbols, sizes)
    return entry, segments, symbols, sizes


@cocotb.test(timeout_time=2, timeout_unit="s")
async def tcm_workset_test(dut):
    assert os.environ.get("COCOTB_USE_FRONTDOOR") == "1"
    kib = int(os.environ["TCM_DTCM_KIB"])
    tiles = int(os.environ["TCM_WS_TILES"])
    delay = int(os.environ["TCM_WS_READ_DELAY"])
    assert tiles in TILE_CHOICES and delay in DELAYS
    g = geometry(kib)
    path = runfiles.Create().Rlocation("coralnpu_hw/tests/cocotb/tcm_workset/workset_program.elf")
    assert path, "missing workset ELF"
    entry, segments, symbols, sizes = inspect_elf(path)
    elf_sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    a, b, expected, vector_sha = vectors(tiles)
    packed_a = a.transpose(0, 2, 1).copy().view(np.uint8).reshape(-1)
    packed_b = b.copy().view(np.uint8).reshape(-1)
    fixture = await VerilatorTestFixture.Create(dut, csr_base_addr=g["csr_base"],
                                               ext_mem_size=EXT_BYTES, read_delay_cycles=delay)
    for strategy in STRATEGIES:
        config = plan(kib, tiles, strategy)
        repeats = []
        for repeat in range(REPEATS):
            await fixture.core_mini_axi.reset()
            await fixture.write(0, np.tile(np.array([0x13, 0, 0, 0], dtype=np.uint8), 2048))
            await fixture.load_elf_and_lookup_symbols(path, list(SYMBOL_SIZES), optional=False)
            # Fixture also auto-probes CRT/simulator metadata symbols.
            assert {name: fixture.symbols[name] for name in SYMBOL_SIZES} == symbols
            assert {name: fixture.symbol_sizes[name] for name in SYMBOL_SIZES} == sizes
            await fixture.write(EXT_A, packed_a)
            await fixture.write(EXT_B, packed_b)
            await fixture.write(EXT_OUT, np.full(expected.size, 0xDEADBEEF, dtype="<u4"))
            await fixture.write("ws_a", np.full(4096, 0xA5, dtype=np.uint8))
            await fixture.write("ws_out", np.full(256, 0xDEADBEEF, dtype="<u4"))
            await fixture.write(DTCM_BASE + LOW_DTCM_BYTES,
                                np.full(config["used_slots"] * WEIGHT_BYTES, 0xA5, dtype=np.uint8))
            await fixture.write_word("ws_tiles", tiles)
            await fixture.write_word("ws_dtcm_kib", kib)
            await fixture.write_word("ws_cache", int(strategy == "prefix_cache"))
            probe = WorksetAxiProbe(dut, tiles)
            probe.start()
            wait_cycles = await fixture.run_to_halt(timeout_cycles=100000000)
            traffic = probe.stop(config)
            assert not fixture.fault(), "NPU fault"
            assert int(await fixture.read_word("ws_status")) == 1, "workset incomplete"
            counters = {name: int(await fixture.read_word(name)) for name in SYMBOL_SIZES
                        if name.endswith("_bytes") or name.endswith("_cycles") and name != "ws_round_cycles"}
            for prefix, key in (("input", "input_read_bytes"), ("weight", "weight_read_bytes"),
                                ("output", "output_write_bytes")):
                assert counters[f"ws_{prefix}_bytes"] == config[key], "software copy count: " + prefix
            round_cycles = list(map(int, await fixture.read("ws_round_cycles", dtype=np.dtype("<u4"), shape=(3,))))
            phase_sum = sum(counters["ws_" + p + "_cycles"] for p in ("input", "weight", "compute", "output"))
            assert 0 < phase_sum <= counters["ws_total_cycles"] <= wait_cycles
            assert len(round_cycles) == ROUNDS and all(c > 0 for c in round_cycles)
            assert sum(round_cycles) <= counters["ws_total_cycles"]
            actual = await fixture.read(EXT_OUT, dtype=np.dtype("<i4"), shape=expected.shape)
            np.testing.assert_array_equal(actual, expected, err_msg=f"{strategy}/repeat{repeat}")
            signature = (wait_cycles, counters, round_cycles, traffic)
            assert not repeats or signature == repeats[0], "nonrepeatable cycles/counters/traffic"
            repeats.append(signature)
            record = dict(config, schema=1, status="PASS", repeat=repeat, itcm_kib=8,
                          read_delay_cycles=delay, scope=SCOPE, elf_sha256=elf_sha,
                          vector_sha256=vector_sha, elf_entry=entry, symbols=symbols,
                          elf_load_segments=segments, wait_for_halt_cycles=wait_cycles,
                          csr_counters=counters, round_cycles=round_cycles, axi=traffic,
                          external_memory_bytes=EXT_BYTES, elf_loading="frontdoor",
                          input_schedule="round_outer_weight_tile_inner_outputs_external",
                          timing="cold_start_copies_compute_output_included_host_init_excluded")
            dut._log.info("[GOOGLE_TCM_WORKSET] " + json.dumps(record, sort_keys=True))
    dut._log.info(f"[GOOGLE_TCM_WORKSET_CHECK] tiles={tiles} strategies=2 repeats={REPEATS} passed")
