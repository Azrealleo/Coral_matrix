"""Shared signed-INT8 logical layers crossing M/N tiles or K=256 passes."""

import hashlib

import numpy as np


# One multi-output-tile case and one three-pass, thin-output case.
LAYER_SHAPES = (
    ("multi_tile_m20_n23_k272", 20, 23, 272),
    ("three_pass_m1_n10_k528", 1, 10, 528),
)


def reference(a, b):
    wide = a.astype(np.int64) @ b.astype(np.int64)
    assert np.all(wide >= -(2**31)) and np.all(wide < 2**31)
    return wide.astype("<i4")


def layer_hash(a, b):
    return hashlib.sha256(a.tobytes() + b.tobytes() + reference(a, b).tobytes()).hexdigest()


def layer_cases():
    cases = []
    for name, m, n, k in LAYER_SHAPES:
        row, depth = np.indices((m, k))
        bdepth, column = np.indices((k, n))
        a = (((17 * row + 23 * depth + 9) % 256) - 128).astype(np.int8)
        b = (((29 * bdepth + 11 * column + 7) % 256) - 128).astype(np.int8)
        cases.append((name, a, b))
    return cases


def tiles(a, b):
    m, k = a.shape
    assert b.shape[0] == k
    n = b.shape[1]
    for row in range(0, m, 16):
        for column in range(0, n, 16):
            tile_a = np.zeros((16, k), dtype=np.int8)
            tile_b = np.zeros((k, 16), dtype=np.int8)
            valid_m = min(16, m - row)
            valid_n = min(16, n - column)
            tile_a[:valid_m] = a[row:row + valid_m]
            tile_b[:, :valid_n] = b[:, column:column + valid_n]
            yield row, column, valid_m, valid_n, tile_a, tile_b


def passes(k):
    assert k > 256
    result = []
    for start in range(0, k, 256):
        logical = min(256, k - start)
        physical = ((logical + 15) // 16) * 16
        assert physical <= 256
        result.append((start, logical, physical))
    return result
