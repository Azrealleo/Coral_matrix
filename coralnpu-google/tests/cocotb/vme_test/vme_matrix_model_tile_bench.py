"""Model-like signed-INT8 tile arithmetic and full-core cycle diagnostics."""

import json

import cocotb
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture

from vme_matrix_model_tile_vectors import full_tile, logical_hash, model_cases
from vme_matrix_perf_bench import _elf_path, _run_case, _vector_hash


@cocotb.test()
async def vme_matrix_model_tile_test(dut):
    fixture = await VerilatorTestFixture.Create(dut)
    elf = _elf_path()
    for name, a, b in model_cases():
        m, k = a.shape
        n = b.shape[1]
        full_a, full_b = full_tile(a, b)
        counts = []
        for repeat in range(3):
            cycles = await _run_case(
                fixture, elf, (name, full_a, full_b, 1, True), repeat=repeat,
                input_schedule="model_tile_tk1_full_core_fixture")
            counts.append(cycles)
            row = dict(case=name, repeat=repeat, M=m, N=n, K=k,
                       K_hw=k, tk_per_instruction=1, checked_elements=256,
                       useful_macs=m * n * k, physical_macs=256 * k,
                       logical_sha256=logical_hash(a, b),
                       physical_vector_sha256=_vector_hash(full_a, full_b),
                       launch_wait_to_halt_cycles=cycles,
                       scope="full_core_fixture_not_mxu_unit")
            cocotb.log.info("[GOOGLE_MODEL_TILE] " + json.dumps(row, sort_keys=True))
        assert len(set(counts)) == 1, f"{name}: nondeterministic cycles {counts}"
    cocotb.log.info("[GOOGLE_MODEL_TILE_CHECK] cases=7 repeats=3 passed")
