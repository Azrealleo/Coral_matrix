#!/usr/bin/env python3
"""Check common vectors against golden.py without importing Cocotb.

This validates Python syntax, vector layout and reference values ONLY. It does
not compile the C++ program, exercise Zvt instructions or simulate hardware.
Needs NumPy; writes golden.py's outputs to a temporary directory, not the repo.
"""

import ast
import hashlib
import os
from pathlib import Path
import runpy
import tempfile

import numpy as np


def main():
    root = Path(__file__).resolve().parent.parent
    bench = root / "coralnpu-google/tests/cocotb/vme_test/vme_matrix_perf_bench.py"
    tree = ast.parse(bench.read_text(encoding="utf-8"), filename=str(bench))
    names = {"_common_cases", "_signed_cases", "_reference", "_vector_hash"}
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(selected) == len(names)
    namespace = {"np": np, "hashlib": hashlib, "TE": 16, "MAX_K": 256}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(bench), "exec"), namespace)
    common = namespace["_common_cases"]()

    original_dir = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="coral_matrix_vectors_") as temp:
        try:
            os.chdir(temp)
            runpy.run_path(str(root / "coralnpu-Yangg152/hdl/mxu/golden.py"))
        finally:
            os.chdir(original_dir)
        cases_dir = Path(temp) / "cases"

        def unpack(name, suffix):
            lines = (cases_dir / f"{name}_{suffix}.hex").read_text().splitlines()
            return b"".join(int(line, 16).to_bytes(16, "little") for line in lines)

        for name, a, b, tk, signed_b in common:
            k = a.shape[1]
            a_hex = np.frombuffer(unpack(name, "act"), dtype=np.int8).reshape(16, k)
            b_hex = np.frombuffer(unpack(name, "weight"), dtype=np.int8).reshape(k, 16)
            c_hex = np.frombuffer(unpack(name, "golden"), dtype="<i4").reshape(16, 16)
            np.testing.assert_array_equal(a, a_hex)
            np.testing.assert_array_equal(b, b_hex)
            np.testing.assert_array_equal(namespace["_reference"](a, b), c_hex)
            assert tk == 4 and (signed_b or np.all(b >= 0))
            print(f"[VECTOR_MATCH] case={name} K={k} sha256={namespace['_vector_hash'](a, b)}")

    diagnostics = namespace["_signed_cases"]()
    assert len(diagnostics) == 9
    for name, a, b, tk, signed_b in diagnostics:
        k = a.shape[1]
        assert a.shape == (16, k) and b.shape == (k, 16)
        assert 1 <= tk <= 4 and k % tk == 0
        assert signed_b or np.all(b >= 0)
        # Check an independent scalar dot product at every output element.
        scalar = [[sum(int(a[i, p]) * int(b[p, j]) for p in range(k))
                   for j in range(16)] for i in range(16)]
        np.testing.assert_array_equal(namespace["_reference"](a, b), scalar)
    print("[STATIC_CHECK] syntax OK; 4 common vector sets match; 9 diagnostic references match")
    print("[STATIC_CHECK] C++ compilation and RTL simulation NOT performed")


if __name__ == "__main__":
    main()
