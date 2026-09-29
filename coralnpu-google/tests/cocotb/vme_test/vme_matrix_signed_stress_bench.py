"""Functional signed-INT8 regression with the same vectors as the VCS fork run."""

import json

import cocotb
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture
from vme_matrix_perf_bench import _elf_path, _run_case, _vector_hash
from vme_matrix_stress_vectors import stress_batches


@cocotb.test()
async def vme_matrix_signed_stress_test(dut):
    fixture = await VerilatorTestFixture.Create(dut)
    elf = _elf_path()
    count = 0
    for batch, cases in stress_batches():
        for case in cases:
            await _run_case(fixture, elf, case,
                            input_schedule="shared_signed_stress_vector_loads_per_command")
            record = dict(batch=batch, case=case[0], K=case[1].shape[1],
                          checked_elements=256, vector_sha256=_vector_hash(case[1], case[2]))
            cocotb.log.info("[GOOGLE_SIGNED_STRESS] " + json.dumps(record, sort_keys=True))
            count += 1
    assert count == 32
    cocotb.log.info("[GOOGLE_SIGNED_STRESS_CHECK] batches=8 cases=32 checked_elements=8192 passed")
