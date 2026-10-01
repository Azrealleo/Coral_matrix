"""One full-core launch for 1/4/16 outputs with shared signed-INT8 B."""

import hashlib
import json

import cocotb
import numpy as np
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture

from vme_matrix_model_tile_vectors import shared_weight_batch_cases
from vme_matrix_perf_bench import _elf_path


@cocotb.test()
async def vme_matrix_shared_weight_batch_test(dut):
    fixture = await VerilatorTestFixture.Create(dut)
    elf = _elf_path("vme_matrix_shared_weight_batch_program")
    symbols = ["batch_a", "batch_b", "batch_out", "batch_k", "batch_tiles",
               "batch_status"]
    cases = shared_weight_batch_cases()
    for name, a, b in cases:
        tiles, m, k = a.shape
        assert m == 16 and b.shape == (k, 16)
        expected = (a.astype(np.int64) @ b.astype(np.int64)).astype("<i4")
        packed_a = np.zeros((16, 256, 16), dtype=np.int8)
        packed_a[:tiles, :k] = a.transpose(0, 2, 1)
        packed_b = np.zeros((256, 16), dtype=np.int8)
        packed_b[:k] = b
        digest = hashlib.sha256(
            a.tobytes() + b.tobytes() + expected.tobytes()).hexdigest()
        counts = []
        for repeat in range(3):
            await fixture.load_elf_and_lookup_symbols(elf, symbols, optional=False)
            await fixture.write("batch_a", packed_a.view(np.uint8).reshape(-1))
            await fixture.write("batch_b", packed_b.view(np.uint8).reshape(-1))
            await fixture.write("batch_out", np.full(16 * 256, 0xDEADBEEF,
                                                     dtype=np.uint32))
            await fixture.write_word("batch_k", k)
            await fixture.write_word("batch_tiles", tiles)
            cycles = await fixture.run_to_halt(timeout_cycles=300000)
            assert not fixture.fault(), name + ": core fault"
            assert int(await fixture.read_word("batch_status")) == 1
            actual = await fixture.read("batch_out", dtype=np.dtype("<i4"),
                                        shape=(16, 16, 16))
            np.testing.assert_array_equal(actual[:tiles], expected, err_msg=name)
            assert cycles > 0
            counts.append(cycles)
            row = dict(case=name, repeat=repeat, K=k, tiles=tiles,
                       checked_elements=tiles * 256, useful_macs=tiles * 256 * k,
                       logical_sha256=digest, launch_wait_to_halt_cycles=cycles,
                       weight_load_schedule="B_reloaded_from_memory_per_tile",
                       scope="official_tk4_full_core_shared_weight_batch")
            cocotb.log.info("[GOOGLE_BATCH] " + json.dumps(row, sort_keys=True))
        assert len(set(counts)) == 1, name + ": unstable cycles"
    cocotb.log.info(f"[GOOGLE_BATCH_CHECK] cases={len(cases)} repeats=3 passed")
