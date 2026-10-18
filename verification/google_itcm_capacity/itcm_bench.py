"""RAM frontdoor geometry only; core remains halted, no instruction timing."""
import json
import os

import cocotb
import numpy as np

from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture
from itcm_spec import SCOPE, geometry, mask_addresses, probes


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def itcm_geometry_test(dut):
    g = geometry(int(os.environ["TCM_ITCM_KIB"]))
    fixture = await VerilatorTestFixture.Create(dut, csr_base_addr=g["csr_base"])
    assert int(await fixture.read_word(g["csr_base"])) == 3
    expected = {addr: bytearray(data) for addr, data in probes(g["itcm_kib"])}
    # Write ALL probes before reading, so truncated/aliased upper addresses fail.
    # No reset-to-zero assumption, backdoor load, core start or out-of-range access.
    for addr, data in expected.items():
        await fixture.write(addr, np.frombuffer(bytes(data), dtype=np.uint8))
    masked = mask_addresses(g["itcm_kib"])
    for addr in masked:
        replacement = bytes((0x11, 0x23, 0x35, 0x47, 0x59, 0x6B, 0x7D))
        await fixture.write(addr + 1, np.frombuffer(replacement, dtype=np.uint8))
        expected[addr][1:8] = replacement
    for addr, data in expected.items():
        actual = await fixture.read(addr, 16)
        assert bytes(actual) == bytes(data), f"RAM alias/mismatch at {addr:#x}"
    assert int(await fixture.read_word(g["csr_base"])) == 3
    row = dict(g, schema=1, scope=SCOPE, status="PASS",
               checked_words=len(expected), checked_bytes=16 * len(expected),
               byte_mask_cases=len(masked), core_started=False)
    dut._log.info("[GOOGLE_ITCM_GEOMETRY] " + json.dumps(row, sort_keys=True))
    dut._log.info("[GOOGLE_ITCM_GEOMETRY_CHECK] passed")
