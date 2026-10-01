"""Seven deterministic model-like single-tile shapes shared by both RTL runs.

Logical M/N/K are deliberately distinct from each engine's execution tile.
These are GEMM-shaped arithmetic microbenchmarks, not complete AI models.
"""

import hashlib

import numpy as np


# name, valid rows, valid columns, reduction depth. K<=256 for the reused ELF.
MODEL_SHAPES = (
    ("control_m16_n16_k64", 16, 16, 64),
    ("conv3x3_c3_m16_n16", 16, 16, 27),
    ("conv3x3_c8_m7_n13", 7, 13, 72),
    ("pointwise_c17_m15_n11", 15, 11, 17),
    ("pointwise_c65_m16_n16", 16, 16, 65),
    ("fc_batch1_out10_k127", 1, 10, 127),
    ("tail_m16_n9_k241", 16, 9, 241),
)

# Reduction-depth boundaries plus output-tile occupancy at a fixed K.
# Both engines execute physical 16x16 tiles; M/N tails are zero-padded.
SPEED_SWEEP_SHAPES = (
    tuple((f"k_sweep_m16_n16_k{k}", 16, 16, k)
          for k in (1, 4, 8, 15, 16, 17, 31, 32, 33, 63, 64, 65,
                    127, 128, 129, 255, 256))
    + (("tail_m01_n01_k64", 1, 1, 64),
       ("tail_m01_n16_k64", 1, 16, 64),
       ("tail_m16_n01_k64", 16, 1, 64),
       ("tail_m08_n08_k64", 8, 8, 64),
       ("tail_m15_n15_k64", 15, 15, 64))
)


def reference(a, b):
    product = a.astype(np.int64) @ b.astype(np.int64)
    assert np.all(product >= -(2**31)) and np.all(product < 2**31)
    return product.astype("<i4")


def logical_hash(a, b):
    return hashlib.sha256(a.tobytes() + b.tobytes() + reference(a, b).tobytes()).hexdigest()


def model_cases():
    cases = []
    for name, m, n, k in MODEL_SHAPES:
        assert 1 <= m <= 16 and 1 <= n <= 16 and 1 <= k <= 256
        row, depth = np.indices((m, k))
        bdepth, column = np.indices((k, n))
        a = (((19 * row + 7 * depth + 3) % 256) - 128).astype(np.int8)
        b = (((11 * bdepth + 13 * column + 5) % 256) - 128).astype(np.int8)
        cases.append((name, a, b))
    return cases


def speed_sweep_cases():
    cases = []
    for name, m, n, k in SPEED_SWEEP_SHAPES:
        assert 1 <= m <= 16 and 1 <= n <= 16 and 1 <= k <= 256
        row, depth = np.indices((m, k))
        bdepth, column = np.indices((k, n))
        a = (((19 * row + 7 * depth + 3) % 256) - 128).astype(np.int8)
        b = (((11 * bdepth + 13 * column + 5) % 256) - 128).astype(np.int8)
        cases.append((name, a, b))
    return cases


def full_tile(a, b, padded_k=None):
    m, k = a.shape
    assert b.shape[0] == k
    n = b.shape[1]
    if padded_k is None:
        padded_k = k
    assert k <= padded_k <= 256
    full_a = np.zeros((16, padded_k), dtype=np.int8)
    full_b = np.zeros((padded_k, 16), dtype=np.int8)
    full_a[:m, :k] = a
    full_b[:k, :n] = b
    return full_a, full_b
