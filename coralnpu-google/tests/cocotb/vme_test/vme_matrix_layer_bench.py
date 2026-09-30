"""Long-K and multi-M/N-tile full-core arithmetic diagnostics."""

import json

import cocotb
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture

from vme_matrix_layer_vectors import layer_cases, layer_hash, reference, tiles
from vme_matrix_perf_bench import _elf_path, _run_case


@cocotb.test()
async def vme_matrix_layer_test(dut):
    fixture = await VerilatorTestFixture.Create(dut)
    elf = _elf_path("vme_matrix_layer_program")
    for name, a, b in layer_cases():
        m, k = a.shape
        n = b.shape[1]
        expected = reference(a, b)
        tile_list = list(tiles(a, b))
        assert len(tile_list) == ((m + 15) // 16) * ((n + 15) // 16)
        counts = []
        for repeat in range(3):
            total = 0
            for row, column, valid_m, valid_n, tile_a, tile_b in tile_list:
                # Each tile is one long-K program launch. _run_case verifies
                # all 256 physical outputs and completion before timing.
                cycles = await _run_case(
                    fixture, elf,
                    ("{}_r{}_c{}".format(name, row, column), tile_a, tile_b, 1, True),
                    repeat=repeat, input_schedule="long_k_tk1_one_launch_per_tile",
                    max_k=528)
                assert (reference(tile_a, tile_b)[:valid_m, :valid_n] ==
                        expected[row:row + valid_m, column:column + valid_n]).all()
                total += cycles
                cocotb.log.info("[GOOGLE_LAYER_TILE] " + json.dumps(
                    dict(case=name, repeat=repeat, row=row, column=column,
                         valid_m=valid_m, valid_n=valid_n, K=k,
                         launch_wait_to_halt_cycles=cycles,
                         logical_sha256=layer_hash(a, b)), sort_keys=True))
            counts.append(total)
            cocotb.log.info("[GOOGLE_LAYER] " + json.dumps(
                dict(case=name, repeat=repeat, M=m, N=n, K=k,
                     tiles=len(tile_list), checked_elements=m * n,
                     useful_macs=m * n * k,
                     sum_tile_launch_wait_to_halt_cycles=total,
                     logical_sha256=layer_hash(a, b),
                     scope="sum_sequential_full_core_tile_launches_not_model_runtime"),
                sort_keys=True))
        assert len(set(counts)) == 1, "{}: nondeterministic cycles {}".format(name, counts)
    cocotb.log.info("[GOOGLE_LAYER_CHECK] cases=2 tiles=5 repeats=3 passed")
