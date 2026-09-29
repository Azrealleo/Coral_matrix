"""Full 16x16 matrices with the same K-boundary vectors as the fork diagnosis."""

import json

import cocotb
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture
from vme_matrix_boundary_vectors import boundary_cases
from vme_matrix_perf_bench import _elf_path, _run_case, _vector_hash


@cocotb.test()
async def vme_matrix_k_boundary_test(dut):
    fixture = await VerilatorTestFixture.Create(dut)
    elf = _elf_path()
    count = 0
    for case in boundary_cases():
        await _run_case(fixture, elf, case,
                        input_schedule="shared_k_boundary_tk1_functional_only")
        record = dict(case=case[0], K=case[1].shape[1], checked_elements=256,
                      tk_per_instruction=1, vector_sha256=_vector_hash(case[1], case[2]))
        cocotb.log.info("[GOOGLE_K_BOUNDARY] " + json.dumps(record, sort_keys=True))
        count += 1
    assert count == 21
    cocotb.log.info("[GOOGLE_K_BOUNDARY_CHECK] cases=21 checked_elements=5376 passed")
