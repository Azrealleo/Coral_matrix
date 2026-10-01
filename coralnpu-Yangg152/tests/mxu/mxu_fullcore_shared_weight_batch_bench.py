"""One full-core launch for 1/4/16 outputs with fork weight-SRAM reuse."""

import hashlib
import json

import cocotb
import numpy as np
from bazel_tools.tools.python.runfiles import runfiles
from coralnpu_test_utils.sim_test_fixture import Fixture

from mxu_fullcore_tile_vectors import shared_weight_batch_cases


async def _run_batch(dut, reload_weights):
    fixture = await Fixture.Create(dut, clock_ns=1.25, ext_mem_size=4 * 1024 * 1024)
    elf = runfiles.Create().Rlocation(
        "coralnpu_hw/tests/mxu/mxu_fullcore_shared_weight_batch_program.elf")
    assert elf, "Missing fork batch ELF"
    symbols = ["batch_a", "batch_b", "batch_out", "batch_k", "batch_tiles",
               "batch_reload_weights", "batch_status"]
    cases = shared_weight_batch_cases()
    for name, a, b in cases:
        tiles, m, k = a.shape
        assert m == 16 and b.shape == (k, 16)
        expected = (a.astype(np.int64) @ b.astype(np.int64)).astype("<i4")
        packed_a = np.zeros((16, 4096), dtype=np.int8)
        for tile in range(tiles):
            packed_a[tile, :16 * k] = a[tile].reshape(-1)
        packed_b = np.zeros((256, 16), dtype=np.int8)
        packed_b[:k] = b
        digest = hashlib.sha256(
            a.tobytes() + b.tobytes() + expected.tobytes()).hexdigest()
        counts = []
        for repeat in range(3):
            await fixture.load_elf_and_lookup_symbols(elf, symbols)
            await fixture.write("batch_a", packed_a.reshape(-1))
            await fixture.write("batch_b", packed_b.reshape(-1))
            await fixture.write("batch_out", np.full(16 * 256, 0xDEADBEEF,
                                                     dtype="<u4"))
            await fixture.write_word("batch_k", k)
            await fixture.write_word("batch_tiles", tiles)
            await fixture.write_word("batch_reload_weights", int(reload_weights))
            cycles = await fixture.run_to_halt(timeout_cycles=300000)
            assert not fixture.fault(), name + ": core fault"
            status = int.from_bytes(bytes(await fixture.read_word("batch_status")), "little")
            assert status == 1, name + ": program incomplete"
            actual = (await fixture.read("batch_out", 16 * 1024)).view("<i4")
            actual = actual.reshape(16, 16, 16)
            np.testing.assert_array_equal(actual[:tiles], expected, err_msg=name)
            assert cycles > 0
            counts.append(cycles)
            row = dict(case=name, repeat=repeat, K=k, tiles=tiles,
                       checked_elements=tiles * 256, useful_macs=tiles * 256 * k,
                       program_schema=2,
                       logical_sha256=digest, launch_wait_to_halt_cycles=cycles,
                       weight_load_schedule=("B_reloaded_into_MXU_SRAM_per_tile"
                                             if reload_weights else "B_loaded_once_into_MXU_SRAM"),
                       scope=("fork_full_core_shared_weight_batch_reload"
                              if reload_weights else "fork_full_core_shared_weight_batch"))
            marker = "[YANGG_BATCH_RELOAD] " if reload_weights else "[YANGG_BATCH] "
            cocotb.log.info(marker + json.dumps(row, sort_keys=True))
        assert len(set(counts)) == 1, name + ": unstable cycles"
    marker = "[YANGG_BATCH_RELOAD_CHECK]" if reload_weights else "[YANGG_BATCH_CHECK]"
    cocotb.log.info(f"{marker} cases={len(cases)} repeats=3 passed")


@cocotb.test()
async def mxu_fullcore_shared_weight_batch_test(dut):
    await _run_batch(dut, False)


@cocotb.test()
async def mxu_fullcore_shared_weight_batch_reload_test(dut):
    await _run_batch(dut, True)
