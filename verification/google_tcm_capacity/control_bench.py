"""Same ELF / inputs / placement for each capacity; no host loading in timing."""
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
from control_spec import REPEATS, SCOPE, SYMBOL_SIZES, cases, check_layout, reference, vector_hash


def elf_layout(path):
    with open(path, "rb") as stream:
        elf = ELFFile(stream)
        segments = [(int(s["p_paddr"]), int(s["p_memsz"]))
                    for s in elf.iter_segments() if s["p_type"] == "PT_LOAD"]
        return int(elf.header["e_entry"]), segments


@cocotb.test(timeout_time=100, timeout_unit="ms")
async def tcm_control_test(dut):
    assert os.environ.get("COCOTB_USE_FRONTDOOR") == "1", "relocated map requires frontdoor loader"
    g = geometry(int(os.environ["TCM_DTCM_KIB"]))
    fixture = await VerilatorTestFixture.Create(dut, csr_base_addr=g["csr_base"])
    path = runfiles.Create().Rlocation("coralnpu_hw/tests/cocotb/tcm_control/control_program.elf")
    assert path, "missing control ELF runfile"
    elf_sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    entry, segments = elf_layout(path)
    for name, a, b in cases():
        k = a.shape[1]
        counts = []
        for repeat in range(REPEATS):
            await fixture.core_mini_axi.reset()
            # Pad random ITCM tail with legal NOPs before loading the ELF.
            # Host initialization is outside every measured execution window.
            await fixture.write(0, np.tile(np.array([0x13, 0, 0, 0], dtype=np.uint8), 2048))
            await fixture.load_elf_and_lookup_symbols(path, list(SYMBOL_SIZES), optional=False)
            check_layout(segments, entry, fixture.symbols, fixture.symbol_sizes, DTCM_BASE)
            pa = np.full((260, 16), 37, dtype=np.int8)
            pb = np.full((260, 16), 53, dtype=np.int8)
            pa[:k] = a.T
            pb[:k] = b
            await fixture.write("ctrl_a", pa.view(np.uint8).reshape(-1))
            await fixture.write("ctrl_b", pb.view(np.uint8).reshape(-1))
            await fixture.write("ctrl_out", np.full(256, 0xDEADBEEF, dtype="<u4"))
            await fixture.write_word("ctrl_status", 0)
            await fixture.write_word("ctrl_k", k)
            cycles = await fixture.run_to_halt(timeout_cycles=200000)
            assert not fixture.fault(), f"{name}: NPU fault"
            assert int(await fixture.read_word("ctrl_status")) == 1, f"{name}: incomplete"
            assert int(await fixture.read_word("ctrl_mtype")) == ((16 << 10) | (4 << 5) | 3)
            assert ((int(await fixture.read_word("ctrl_vtype")) >> 8) & 1) == 1
            actual = await fixture.read("ctrl_out", dtype=np.dtype("<i4"), shape=(16, 16))
            np.testing.assert_array_equal(actual, reference(a, b), err_msg=name)
            assert cycles > 0
            counts.append(cycles)
            row = dict(schema=1, status="PASS", dtcm_kib=g["dtcm_kib"],
                       itcm_kib=8, case=name, K=k, M=16, N=16, repeat=repeat,
                       checked_elements=256, useful_macs=256 * k,
                       active_matrix_bytes=32 * k + 1024, reserved_buffer_bytes=9344,
                       vector_sha256=vector_hash(a, b), elf_sha256=elf_sha,
                       symbols={s: fixture.symbols[s] for s in SYMBOL_SIZES},
                       elf_entry=entry, elf_load_segments=segments, wait_for_halt_cycles=cycles,
                       scope=SCOPE, input_schedule="host_frontdoor_preloaded_low_dtcm32k",
                       elf_loading="frontdoor", itcm_tail="full_8k_nop_before_elf")
            dut._log.info("[GOOGLE_TCM_CONTROL] " + json.dumps(row, sort_keys=True))
        assert len(set(counts)) == 1, f"{name}: nonrepeatable cycles {counts}"
    dut._log.info(f"[GOOGLE_TCM_CONTROL_CHECK] cases={len(cases())} repeats={REPEATS} passed")
