"""Same-vector full tiles plus signed-B/Tk arithmetic diagnostics.

Launch-to-halt cycles include startup, configuration, vector loads, repeated
matrix instructions, output stores and halt. They must NOT be compared with
Yangg152's standalone MMA latency as if the scopes matched.
"""

import hashlib
import json

import cocotb
import numpy as np
from bazel_tools.tools.python.runfiles import runfiles
from coralnpu_test_utils.sim_backends.verilator_test_fixture import VerilatorTestFixture

MAX_K = 256
TE = 16
SYMBOLS = [
    "perf_a", "perf_b", "perf_out", "perf_k", "perf_tk", "perf_signed_b",
    "perf_status", "perf_mtype", "perf_vtype",
]


def _common_cases():
    # EXACT legacy RNG, draw order and dtype used by the fork's golden.py.
    # Do not replace RandomState with default_rng: that changes the vectors.
    rng = np.random.RandomState(42)
    result = []
    for name, k, lo, hi, signed_b in [
        ("tc1_tk16", 16, -64, 64, True),
        ("tc2_tk64", 64, -128, 127, True),
        ("tc3_tk256", 256, -50, 50, True),
        ("tc4_unsigned", 16, 0, 127, False),
    ]:
        a = rng.randint(lo, hi, size=(TE, k), dtype=np.int8)
        b = rng.randint(lo, hi, size=(k, TE), dtype=np.int8)
        result.append((name, a, b, 4, signed_b))
    return result


def _signed_cases():
    # Fill unused row slots with nonzero values in _run_case to test Tk masks.
    cases = []
    for tk in (1, 2, 3, 4):
        a = ((np.arange(TE * tk).reshape(TE, tk) % 17) - 8).astype(np.int8)
        b = -((np.arange(tk * TE).reshape(tk, TE) % 7) + 1).astype(np.int8)
        cases.append((f"signed_b_tk{tk}", a, b, tk, True))
    edges = np.array([-128, -127, -1, 0, 1, 126, 127], dtype=np.int8)
    a = np.resize(edges, (TE, 16)).copy()
    b = np.resize(edges[::-1], (16, TE)).copy()
    cases.append(("signed_extremes_accumulate", a, b, 4, True))
    # Each sign quadrant separately; B is never interpreted as signed by guess.
    for a_neg, b_neg in ((False, False), (True, False), (False, True), (True, True)):
        a = np.full((TE, 16), -7 if a_neg else 7, dtype=np.int8)
        b = np.full((16, TE), -11 if b_neg else 11, dtype=np.int8)
        cases.append((f"sign_quadrant_{int(a_neg)}{int(b_neg)}", a, b, 4, b_neg))
    return cases


def _reference(a, b):
    # Widen BEFORE multiplying; these int8/K<=256 workloads cannot overflow i32.
    return (a.astype(np.int64) @ b.astype(np.int64)).astype("<i4")


def _vector_hash(a, b):
    # Logical A (16xK), B (Kx16), C (16x16), in that order; C is little-endian i32.
    return hashlib.sha256(a.tobytes() + b.tobytes() + _reference(a, b).tobytes()).hexdigest()


async def _run_case(fixture, elf, case, repeat=0, observer=None, input_schedule=None,
                    max_k=MAX_K):
    name, a, b, tk, signed_b = case
    k = a.shape[1]
    assert a.shape == (TE, k) and b.shape == (k, TE)
    assert 0 < k <= max_k and 1 <= tk <= 4 and k % tk == 0
    assert signed_b or np.all(b >= 0)
    await fixture.load_elf_and_lookup_symbols(elf, SYMBOLS, optional=False)
    # Nonzero padding also catches arithmetic using masked-off row slots.
    packed_a = np.full((max_k + 4, TE), 37, dtype=np.int8)
    packed_b = np.full((max_k + 4, TE), 53, dtype=np.int8)
    packed_a[:k] = a.T
    packed_b[:k] = b
    await fixture.write("perf_a", packed_a.view(np.uint8).reshape(-1))
    await fixture.write("perf_b", packed_b.view(np.uint8).reshape(-1))
    # Poison rather than zero so a missing output write does not pass by chance.
    await fixture.write("perf_out", np.full(TE * TE, 0xDEADBEEF, dtype=np.uint32))
    await fixture.write_word("perf_k", k)
    await fixture.write_word("perf_tk", tk)
    await fixture.write_word("perf_signed_b", int(signed_b))
    if observer is not None:
        observer.start()
    try:
        cycles = await fixture.run_to_halt(timeout_cycles=200000)
    finally:
        if observer is not None:
            observer.stop()
    assert not fixture.fault(), f"{name}: core fault"
    assert int(await fixture.read_word("perf_status")) == 1, f"{name}: program did not complete"
    mtype = int(await fixture.read_word("perf_mtype"))
    vtype = int(await fixture.read_word("perf_vtype"))
    assert mtype == ((TE << 10) | (tk << 5) | 3), f"{name}: mtype={mtype:#x}"
    assert ((vtype >> 8) & 1) == int(signed_b), f"{name}: altfmt={vtype:#x}"
    actual = await fixture.read("perf_out", dtype=np.dtype("<i4"), shape=(TE, TE))
    np.testing.assert_array_equal(actual, _reference(a, b), err_msg=name)
    assert cycles > 0
    record = {
        "case": name, "repeat": repeat, "M": TE, "N": TE, "K": k,
        "tk_per_instruction": tk, "matrix_instructions": k // tk,
        "signed_a": True, "signed_b": signed_b, "checked_elements": TE * TE,
        "vector_sha256": _vector_hash(a, b),
        "scope": "full_core_fixture_launch_wait_to_halt",
        "launch_wait_to_halt_cycles": cycles, "useful_macs": TE * TE * k,
        "mac_per_launch_wait_cycle": round(TE * TE * k / cycles, 6),
    }
    if input_schedule is not None:
        record["input_schedule"] = input_schedule
    cocotb.log.info("[GOOGLE_MATRIX_PERF] " + json.dumps(record, sort_keys=True))
    return cycles


def _elf_path(program="vme_matrix_perf_program"):
    path = runfiles.Create().Rlocation(
        f"coralnpu_hw/tests/cocotb/vme_test/{program}.elf"
    )
    if not path:
        raise ValueError(f"Missing {program}.elf")
    return path


@cocotb.test()
async def vme_matrix_signed_diagnostic_test(dut):
    fixture = await VerilatorTestFixture.Create(dut)
    elf = _elf_path()
    for case in _signed_cases():
        await _run_case(fixture, elf, case)
    cocotb.log.info("[GOOGLE_MATRIX_CHECK] 9 diagnostic cases passed")


@cocotb.test()
async def vme_matrix_common_perf_test(dut):
    fixture = await VerilatorTestFixture.Create(dut)
    elf = _elf_path()
    for case in _common_cases():
        counts = [await _run_case(fixture, elf, case, repeat=i) for i in range(3)]
        # The model/inputs/reset are deterministic. Investigate variation before
        # treating the cycle counts as a baseline; never silently take the best.
        assert len(set(counts)) == 1, f"{case[0]}: non-repeatable counts {counts}"
    cocotb.log.info("[GOOGLE_MATRIX_CHECK] 4 common cases x 3 repeats passed")
