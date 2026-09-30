"""Fork full-core counterpart of the official seven model-like tile cases."""

import hashlib
import json

import cocotb
import numpy as np
from bazel_tools.tools.python.runfiles import runfiles
from coralnpu_test_utils.sim_test_fixture import Fixture

from mxu_fullcore_tile_vectors import full_tile, logical_hash, model_cases, reference


@cocotb.test()
async def mxu_fullcore_tile_test(dut):
    # Match the official fixture's nominal clock and external-memory size.
    fixture = await Fixture.Create(dut, clock_ns=1.25, ext_mem_size=4 * 1024 * 1024)
    elf = runfiles.Create().Rlocation(
        "coralnpu_hw/tests/mxu/mxu_fullcore_tile_program.elf")
    assert elf, "Missing fork full-core tile ELF"
    symbols = ["bench_a", "bench_b", "bench_out", "bench_k_hw", "bench_status"]
    for name, a, b in model_cases():
        m, k = a.shape
        n = b.shape[1]
        k_hw = ((k + 15) // 16) * 16
        full_a, full_b = full_tile(a, b, k_hw)
        expected = reference(full_a, full_b)
        packed_a = np.zeros((16 * 256,), dtype=np.int8)
        packed_b = np.zeros((256 * 16,), dtype=np.int8)
        packed_a[:16 * k_hw] = full_a.reshape(-1)
        packed_b[:k_hw * 16] = full_b.reshape(-1)
        physical_sha = hashlib.sha256(
            full_a.tobytes() + full_b.tobytes() + expected.tobytes()).hexdigest()
        counts = []
        for repeat in range(3):
            await fixture.load_elf_and_lookup_symbols(elf, symbols)
            await fixture.write("bench_a", packed_a)
            await fixture.write("bench_b", packed_b)
            await fixture.write("bench_out", np.full(256, 0xDEADBEEF, dtype="<u4"))
            await fixture.write_word("bench_k_hw", k_hw)
            cycles = await fixture.run_to_halt(timeout_cycles=200000)
            if fixture.fault():
                status = int.from_bytes(bytes(await fixture.read_word("bench_status")), "little")
                # CoreAxiCSR maps CsrOutIO mepc/mtval/mcause to 0x104/0x108/0x10c.
                mepc, mtval, mcause = [
                    int.from_bytes(bytes(await fixture.core_mini_axi.read_csr(addr)), "little")
                    for addr in (0x104, 0x108, 0x10c)
                ]
                cocotb.log.error(
                    "[YANGG_FULLCORE_FAULT] case=%s repeat=%d cycles=%d "
                    "bench_status=%d mepc=0x%08x mtval=0x%08x mcause=0x%08x",
                    name, repeat, cycles, status, mepc, mtval, mcause)
            assert not fixture.fault(), name + ": core fault"
            status_bytes = await fixture.read_word("bench_status")
            assert int.from_bytes(bytes(status_bytes), "little") == 1, name + ": program incomplete"
            actual = (await fixture.read("bench_out", 1024)).view("<i4").reshape(16, 16)
            np.testing.assert_array_equal(actual, expected, err_msg=name)
            assert cycles > 0
            counts.append(cycles)
            row = dict(case=name, repeat=repeat, M=m, N=n, K=k, K_hw=k_hw,
                       checked_elements=256, useful_macs=m * n * k,
                       physical_macs=256 * k_hw,
                       logical_sha256=logical_hash(a, b),
                       physical_vector_sha256=physical_sha,
                       launch_wait_to_halt_cycles=cycles,
                       scope="fork_full_core_fixture_not_standalone_unit")
            cocotb.log.info("[YANGG_FULLCORE_TILE] " + json.dumps(row, sort_keys=True))
        assert len(set(counts)) == 1, name + ": nondeterministic cycles"
    cocotb.log.info("[YANGG_FULLCORE_TILE_CHECK] cases=7 repeats=3 passed")
