"""Full-core Tk=4 cycle sweep over K boundaries and M/N tile occupancy."""

import hashlib
import json

import cocotb
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture

from vme_matrix_model_tile_vectors import (
    full_tile, logical_hash, reference, speed_sweep_cases,
)
from vme_matrix_perf_bench import _elf_path, _run_case


@cocotb.test()
async def vme_matrix_speed_sweep_test(dut):
    fixture = await VerilatorTestFixture.Create(dut)
    elf = _elf_path()
    cases = speed_sweep_cases()
    for name, a, b in cases:
        m, k = a.shape
        n = b.shape[1]
        k_hw = ((k + 3) // 4) * 4
        full_a, full_b = full_tile(a, b, k_hw)
        physical_sha = hashlib.sha256(
            full_a.tobytes() + full_b.tobytes() +
            reference(full_a, full_b).tobytes()).hexdigest()
        counts = []
        for repeat in range(3):
            cycles = await _run_case(
                fixture, elf, (name, full_a, full_b, 4, True), repeat=repeat,
                input_schedule="tk4_full_core_speed_sweep_k_padded_to_4")
            counts.append(cycles)
            row = dict(case=name, repeat=repeat, M=m, N=n, K=k, K_hw=k_hw,
                       tk_per_instruction=4, checked_elements=256,
                       useful_macs=m * n * k, physical_macs=256 * k_hw,
                       logical_sha256=logical_hash(a, b),
                       physical_vector_sha256=physical_sha,
                       launch_wait_to_halt_cycles=cycles,
                       scope="official_tk4_full_core_speed_sweep")
            cocotb.log.info("[GOOGLE_TK4_SWEEP] " + json.dumps(row, sort_keys=True))
        assert len(set(counts)) == 1, name + ": nondeterministic cycles"
    cocotb.log.info(f"[GOOGLE_TK4_SWEEP_CHECK] cases={len(cases)} repeats=3 passed")
