"""Stage 1: frontdoor RAM geometry only; NOT NPU workload performance."""
import json
import os

import cocotb
import numpy as np

from capacity_spec import BANK_BYTES, DTCM_BASE, geometry, probes
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def tcm_capacity_test(dut):
    kib = int(os.environ["TCM_DTCM_KIB"])
    g = geometry(kib)
    fixture = await VerilatorTestFixture.Create(dut, csr_base_addr=g["csr_base"])
    assert int(await fixture.read_word(g["csr_base"])) == 3
    expected = {addr: bytearray(data) for addr, data in probes(kib)}
    # Do not start the core. Do not use DPI loading or assume reset zeros RAM.
    for addr, data in expected.items():
        await fixture.write(addr, np.frombuffer(bytes(data), dtype=np.uint8))
    masked = (DTCM_BASE, DTCM_BASE + g["dtcm_bytes"] - BANK_BYTES)
    for addr in masked:
        replacement = bytes((0x11, 0x23, 0x35, 0x47, 0x59, 0x6B, 0x7D))
        await fixture.write(addr + 1, np.frombuffer(replacement, dtype=np.uint8))
        expected[addr][1:8] = replacement
    # Bank-end and following bank-start accesses are separate legal AXI
    # transactions, not an illegal burst crossing a 4-KiB boundary.
    for addr, data in expected.items():
        got = await fixture.read(addr, 16)
        assert bytes(got) == bytes(data), f"RAM mismatch/alias at {addr:#x}"
    assert int(await fixture.read_word(g["csr_base"])) == 3
    result = dict(g, schema=1, checked_words=len(expected),
                  checked_bytes=16 * len(expected), byte_mask_cases=len(masked),
                  scope="frontdoor_geometry_not_performance", status="PASS")
    dut._log.info("[GOOGLE_TCM_CAPACITY] " + json.dumps(result, sort_keys=True))
    dut._log.info("[GOOGLE_TCM_CAPACITY_CHECK] passed")
