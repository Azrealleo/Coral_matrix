"""Small-resident control only: not the benefit of extra capacity."""
import hashlib

import numpy as np

SCOPE = "same_elf_small_resident_wait_for_halt_not_capacity_benefit"
REPEATS = 3
SYMBOL_SIZES = dict(ctrl_a=4160, ctrl_b=4160, ctrl_out=1024,
                    ctrl_k=4, ctrl_status=4, ctrl_mtype=4, ctrl_vtype=4)


def cases():
    result = []
    for k in (16, 64, 256):
        # Integer formulas avoid dependence on a NumPy RNG implementation.
        a = ((np.arange(16 * k, dtype=np.int64).reshape(16, k) * 37 + 11)
             % 256 - 128).astype(np.int8)
        b = ((np.arange(k * 16, dtype=np.int64).reshape(k, 16) * 53 + 7)
             % 256 - 128).astype(np.int8)
        result.append((f"signed_k{k}", a, b))
    edges = np.array([-128, -127, -1, 0, 1, 126, 127], dtype=np.int8)
    result.append(("signed_edges_k16", np.resize(edges, (16, 16)).copy(),
                   np.resize(edges[::-1], (16, 16)).copy()))
    return result


def reference(a, b):
    return (a.astype(np.int64) @ b.astype(np.int64)).astype("<i4")


def vector_hash(a, b):
    return hashlib.sha256(a.tobytes() + b.tobytes() + reference(a, b).tobytes()).hexdigest()


def check_layout(segments, entry, symbols, sizes, dtcm_base):
    """No externally resident code/data, same low32KiB layout in every model."""
    if not 0 <= entry < 8192:
        raise ValueError("entry not in ITCM")
    count = 0
    for address, size in segments:
        if size == 0:
            continue
        if size < 0 or not (0 <= address and address + size <= 8192 or
                           dtcm_base <= address and address + size <= dtcm_base + 32768):
            raise ValueError("ELF segment outside ITCM8KiB / low DTCM32KiB")
        count += 1
    if not count:
        raise ValueError("empty ELF")
    if not any(start <= entry < start + size for start, size in segments):
        raise ValueError("entry outside ELF segments")
    ranges = []
    for name, length in SYMBOL_SIZES.items():
        address = symbols[name]
        if sizes[name] != length or not dtcm_base <= address < address + length <= dtcm_base + 32768:
            raise ValueError("invalid DTCM symbol: " + name)
        if address % (16 if name in ("ctrl_a", "ctrl_b", "ctrl_out") else 4):
            raise ValueError("unaligned symbol: " + name)
        if not any(start <= address and address + length <= start + size
                   for start, size in segments):
            raise ValueError("symbol not covered by ELF segment: " + name)
        ranges.append((address, address + length))
    if any(a[1] > b[0] for a, b in zip(sorted(ranges), sorted(ranges)[1:])):
        raise ValueError("overlapping symbols")
