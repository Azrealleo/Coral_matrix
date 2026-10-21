"""Resident INT8 linear-layer microbenchmarks, not a language model."""
import hashlib
import json
import re
import struct

UPSTREAM = "8e4df09b4ea7e065e02d14ce3ae033d40dfd973a"
PACKAGE = "tests/cocotb/llm_linear_v1"
TOP = "VmeCoreMini_ITCM256KB_DTCM512KBAxi"
SCOPE = "resident_synthetic_INT8_linear_scalar_vs_official_RVV_not_model_or_VME"
SAMPLES = 4
CASES = (
    ("decode_tiny", 1, 32, 32),
    ("prefill_tiny", 16, 32, 32),
    ("decode_small", 1, 64, 64),
    ("prefill_small", 16, 64, 64),
)
MARKER = "[LLM_LINEAR_OBSERVATION] "


def vectors(index):
    _, m, k, n = CASES[index]
    state = 137 + index

    def random():
        nonlocal state
        state ^= (state << 13) & 0xffffffff
        state ^= state >> 17
        state ^= (state << 5) & 0xffffffff
        return state

    x = [(random() & 255) - 128 for _ in range(m * k)]
    # The official kernel explicitly forbids -128 on BOTH operands. Preserve
    # that domain: activation [-128,127], symmetric weight [-127,127].
    w = [random() % 255 - 127 for _ in range(k * n)]
    x[0], w[0] = -128, -127
    x[-1], w[-1] = 127, 127
    y = [sum(x[r*k+d] * w[d*n+c] for d in range(k))
         for r in range(m) for c in range(n)]
    raw_x, raw_w = bytes(v & 255 for v in x), bytes(v & 255 for v in w)
    signature = 2166136261
    for _ in range(SAMPLES):
        for value in struct.pack("<" + "i" * len(y), *y):
            signature = ((signature ^ value) * 16777619) & 0xffffffff
    return dict(x=raw_x, w=raw_w, y=y, signature=signature,
                vector_sha256=hashlib.sha256(raw_x + raw_w).hexdigest())


def accept(row, index):
    name, m, k, n = CASES[index]
    golden = vectors(index)
    required = dict(schema=1, scope=SCOPE, case_id=index, case=name,
        M=m, K=k, N=n, itcm_kib=256, dtcm_kib=512,
        fault=False, natural_halt=True, firmware_status=3,
        mismatches=0, guard_ok=True, stack_low_canary_intact=True,
        checked_elements=SAMPLES*m*n, signature=golden["signature"],
        vector_sha256=golden["vector_sha256"], input_readback_equal=True,
        output_readback_equal=True, rvv_calls=SAMPLES, samples=SAMPLES)
    if any(type(row.get(key)) is not type(value) or row[key] != value
           for key, value in required.items()):
        raise ValueError("Incomplete or wrong LLM linear result")
    for key in ("elf_sha256", "rtl_sha256"):
        if not re.fullmatch("[a-f0-9]{64}", row.get(key, "")):
            raise ValueError("Missing ELF/RTL identity")
    total = row.get("observation_elapsed_cycles")
    empty = row.get("empty_boundary_cycles")
    if type(total) is not int or total <= 0 or type(empty) is not int or empty < 0:
        raise ValueError("Invalid elapsed/boundary cycles")
    arrays = [row.get("scalar_cycles"), row.get("rvv_cycles")]
    if any(not isinstance(a, list) or len(a) != SAMPLES or
           any(type(c) is not int or c <= empty or c > total for c in a) for a in arrays):
        raise ValueError("Invalid per-call mcycle samples")
    if sum(map(sum, arrays)) > total:
        raise ValueError("Timed calls exceed whole firmware observation")
    scalar, rvv = arrays
    return dict(case=name, M=m, K=k, N=n, useful_macs_per_call=m*k*n,
        scalar_cycles=scalar, rvv_cycles=rvv, empty_boundary_cycles=empty,
        first_scalar_over_rvv=scalar[0]/rvv[0],
        steady_scalar_over_rvv=sum(scalar[1:])/sum(rvv[1:]),
        scope=SCOPE, full_model="NOT_RUN", VME="NOT_RUN")


def checked_log(text, index):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    rows = [json.loads(line.split(MARKER, 1)[1])
            for line in text.splitlines() if MARKER in line]
    summaries = re.findall(r"TESTS=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)\s+SKIP=(\d+)", text)
    if len(rows) != 1 or not summaries or summaries[-1] != ("1", "1", "0", "0"):
        raise ValueError("Missing, duplicate, timed-out or failed RTL test")
    return accept(rows[0], index)
