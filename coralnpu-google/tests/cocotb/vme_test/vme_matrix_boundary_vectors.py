"""Common full-tile K boundary cases; no RNG/version-dependent draw order."""

import numpy as np

K_VALUES = (1, 2, 3, 4, 7, 15, 16, 17, 31, 32, 33, 63, 64, 65,
            127, 128, 129, 240, 241, 255, 256)


def boundary_cases():
    cases = []
    for k in K_VALUES:
        m, p = np.indices((16, k))
        q, n = np.indices((k, 16))
        a = (((19 * m + 7 * p + 3) % 256) - 128).astype(np.int8)
        b = (((11 * q + 13 * n + 5) % 256) - 128).astype(np.int8)
        # The official test uses Tk=1 for every command, reusing the original
        # ELF. This is FUNCTIONAL coverage, not a Tk=4 mixed-tail benchmark.
        cases.append(("boundary_k{}".format(k), a, b, 1, True))
    return cases
