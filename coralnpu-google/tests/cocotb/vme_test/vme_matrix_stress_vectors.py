"""Shared signed-INT8 arithmetic vectors for both full 16x16 matrix units.

Pure NumPy; compatible with the lab's Python 3.6 / NumPy 1.19.5. These do not
test uint8 values above 127, partial tiles, ready/valid stalls or reset timing.
"""

import hashlib

import numpy as np

BATCH_NAMES = (
    "positive_positive", "positive_negative", "negative_positive", "negative_negative",
    "signed_edges", "random_seed137", "all_minus128", "alternating_extremes",
)
LEGACY_NAMES = ("tc1_tk16", "tc2_tk64", "tc3_tk256", "tc4_unsigned")


def reference(a, b):
    wide = a.astype(np.int64) @ b.astype(np.int64)
    assert np.all(wide >= -(2**31)) and np.all(wide < 2**31)
    return wide.astype("<i4")


def vector_hash(a, b):
    return hashlib.sha256(a.tobytes() + b.tobytes() + reference(a, b).tobytes()).hexdigest()


def batch_hash(cases):
    # Digest of the four logical A/B/C fingerprints in legacy testcase order.
    fingerprints = "".join(vector_hash(case[1], case[2]) for case in cases)
    return hashlib.sha256(fingerprints.encode("ascii")).hexdigest()


def stress_batches():
    batches = []
    for batch in BATCH_NAMES:
        # Fresh fixed RNG for each batch; no dependency on execution order.
        rng = np.random.RandomState(137)
        cases = []
        for k in (16, 64, 256):
            if batch in BATCH_NAMES[:4]:
                a_negative = batch.startswith("negative_")
                b_negative = batch.endswith("_negative")
                a_lo, a_hi = (-128, 0) if a_negative else (1, 128)
                b_lo, b_hi = (-128, 0) if b_negative else (1, 128)
                a = rng.randint(a_lo, a_hi, size=(16, k), dtype=np.int8)
                b = rng.randint(b_lo, b_hi, size=(k, 16), dtype=np.int8)
            elif batch == "signed_edges":
                edges = np.array([-128, -127, -1, 0, 1, 126, 127], dtype=np.int8)
                m, p = np.indices((16, k))
                q, n = np.indices((k, 16))
                a = edges[(11 * m + 3 * p + p // 4) % 7]
                b = edges[(5 * q + 3 * n + q // 8) % 7]
            elif batch == "random_seed137":
                a = rng.randint(-128, 128, size=(16, k), dtype=np.int8)
                b = rng.randint(-128, 128, size=(k, 16), dtype=np.int8)
            elif batch == "all_minus128":
                a = np.full((16, k), -128, dtype=np.int8)
                b = np.full((k, 16), -128, dtype=np.int8)
            else:
                m, p = np.indices((16, k))
                q, n = np.indices((k, 16))
                a = np.where((m + p) % 2, -128, 127).astype(np.int8)
                b = np.where((q + n) % 2, 127, -128).astype(np.int8)
            cases.append(("stress_{}_k{}".format(batch, k), a, b, 4, True))
        # The legacy testbench's fourth case remains nonnegative. Do not turn
        # its misleading old 'unsigned' filename into a real uint8 test.
        m, p = np.indices((16, 16))
        a = ((17 * m + 3 * p + 1) % 128).astype(np.int8)
        b = ((7 * m + 11 * p + 9) % 128).astype(np.int8)
        cases.append(("stress_{}_nonnegative_k16".format(batch), a, b, 4, False))
        batches.append((batch, cases))
    return batches
