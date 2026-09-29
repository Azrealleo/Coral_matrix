"""Synthetic reused-chunk operands, distinct from the common random GEMM."""

import numpy as np

INPUT_SCHEDULE = "preloaded_reused_operands_straight_line_same_tile"


def burst_cases():
    edges = np.array([-128, -127, -1, 0, 1, 126, 127], dtype=np.int8)
    m, p = np.indices((16, 4))
    q, n = np.indices((4, 16))
    a_chunk = edges[(3 * m + 2 * p) % len(edges)]
    b_chunk = edges[(5 * q + 3 * n + 1) % len(edges)]
    cases = []
    for k in (16, 64, 256):
        cases.append((f"burst_signed_k{k}", np.tile(a_chunk, (1, k // 4)),
                      np.tile(b_chunk, (k // 4, 1)), 4, True))
    a_chunk = ((np.arange(64).reshape(16, 4) * 17 + 3) % 127).astype(np.int8)
    b_chunk = ((np.arange(64).reshape(4, 16) * 11 + 9) % 127).astype(np.int8)
    cases.append(("burst_nonnegative_k16", np.tile(a_chunk, (1, 4)),
                  np.tile(b_chunk, (4, 1)), 4, False))
    return cases


def validate_reuse_case(case):
    name, a, b, tk, signed_b = case
    k = a.shape[1]
    assert k in (16, 64, 256) and tk == 4, name
    assert a.shape == (16, k) and b.shape == (k, 16), name
    assert a.dtype == np.int8 and b.dtype == np.int8, name
    assert signed_b or np.all(b >= 0), name
    # The executable reads ONLY the first chunk. Reject accidental ordinary
    # GEMM vectors rather than silently validating the wrong workload.
    for base in range(0, k, 4):
        np.testing.assert_array_equal(a[:, base:base + 4], a[:, :4], err_msg=name)
        np.testing.assert_array_equal(b[base:base + 4], b[:4], err_msg=name)
