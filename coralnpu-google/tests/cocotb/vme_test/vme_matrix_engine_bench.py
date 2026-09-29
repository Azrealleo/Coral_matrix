"""Read-only array traces: original common workload and reused-operand stream."""

import json

import cocotb
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture
from vme_matrix_engine_probe import ZvtArrayProbe
from vme_matrix_perf_bench import _common_cases, _elf_path, _run_case, _vector_hash
from vme_matrix_burst_vectors import INPUT_SCHEDULE, burst_cases, validate_reuse_case


@cocotb.test()
async def vme_matrix_engine_profile_test(dut):
    fixture = await VerilatorTestFixture.Create(dut)
    probe = ZvtArrayProbe(dut)
    elf = _elf_path()
    baseline = {"tc1_tk16": 432, "tc2_tk64": 722, "tc3_tk256": 1876, "tc4_unsigned": 432}
    for case in _common_cases():
        previous = None
        for repeat in range(3):
            cycles = await _run_case(fixture, elf, case, repeat=repeat, observer=probe)
            # Selective visibility must not change the prior core behavior.
            assert cycles == baseline[case[0]], f"{case[0]}: instrumented model changed core cycles {cycles}"
            record = probe.summary(case[1].shape[1])
            if previous is not None:
                assert record == previous, f"{case[0]}: non-repeatable array trace"
            previous = record.copy()
            record.update({"case": case[0], "repeat": repeat, "K": case[1].shape[1],
                           "input_schedule": "existing_common_program_vector_loads_per_command",
                           "vector_sha256": _vector_hash(case[1], case[2]),
                           "launch_wait_to_halt_cycles": cycles})
            cocotb.log.info("[GOOGLE_ARRAY_PERF] " + json.dumps(record, sort_keys=True))
    cocotb.log.info("[GOOGLE_ARRAY_CHECK] 4 common cases x 3 repeats passed")


@cocotb.test()
async def vme_matrix_engine_burst_test(dut):
    fixture = await VerilatorTestFixture.Create(dut)
    probe = ZvtArrayProbe(dut)
    elf = _elf_path("vme_matrix_burst_program")
    for case in burst_cases():
        validate_reuse_case(case)
        previous = None
        previous_cycles = None
        for repeat in range(3):
            cycles = await _run_case(fixture, elf, case, repeat=repeat,
                                     observer=probe, input_schedule=INPUT_SCHEDULE)
            record = probe.summary(case[1].shape[1])
            # Check the executed instruction PCs as well as the source .rept:
            # no vector reloads/branches slipped into the measured stream.
            pcs = [command["pc"] for command in probe.counter.commands]
            offsets = [pc - pcs[0] for pc in pcs]
            assert offsets == [4 * i for i in range(len(pcs))], (
                f"{case[0]}: matrix instructions were not consecutive: {offsets}"
            )
            record["command_pc_offsets_bytes"] = offsets
            if previous is not None:
                assert record == previous and cycles == previous_cycles, (
                    f"{case[0]}: non-repeatable burst trace/cycles"
                )
            previous, previous_cycles = record.copy(), cycles
            record.update({"case": case[0], "repeat": repeat, "K": case[1].shape[1],
                           "input_schedule": INPUT_SCHEDULE,
                           "vector_sha256": _vector_hash(case[1], case[2]),
                           "launch_wait_to_halt_cycles": cycles})
            # Only emit array performance AFTER golden/protocol checks pass.
            cocotb.log.info("[GOOGLE_ARRAY_BURST_PERF] " + json.dumps(record, sort_keys=True))
    cocotb.log.info("[GOOGLE_ARRAY_BURST_CHECK] 4 reused-chunk cases x 3 repeats passed")
