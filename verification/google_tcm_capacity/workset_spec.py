"""Fixed-order weight reuse experiment; not a claim of optimal GEMM scheduling."""
import hashlib

import numpy as np

from capacity_spec import CAPACITIES, DTCM_BASE, EXTERNAL_BASE

TILE_CHOICES = (2, 12, 120, 192, 384, 768)
DELAYS = (0, 8)
K = 256
ROUNDS = 3
REPEATS = 3
WEIGHT_BYTES = 4096
OUTPUT_BYTES = 1024
LOW_DTCM_BYTES = 16384
EXT_A = EXTERNAL_BASE
EXT_B = EXTERNAL_BASE + 0x10000
EXT_OUT = EXTERNAL_BASE + 0x400000
EXT_BYTES = 16 * 1024 * 1024
SCOPE = "single_npu_fixed_input_major_prefix_cache_with_cpu_vector_copy"
STRATEGIES = ("stream", "prefix_cache")
SYMBOL_SIZES = dict(ws_a=4096, ws_out=1024, ws_tiles=4, ws_dtcm_kib=4,
                    ws_cache=4, ws_status=4, ws_input_bytes=4, ws_weight_bytes=4,
                    ws_output_bytes=4, ws_input_cycles=4, ws_weight_cycles=4,
                    ws_compute_cycles=4, ws_output_cycles=4, ws_total_cycles=4,
                    ws_round_cycles=12)


def plan(kib, tiles, strategy):
    if kib not in CAPACITIES or tiles not in TILE_CHOICES or strategy not in STRATEGIES:
        raise ValueError("invalid workset configuration")
    slots = (kib * 1024 - LOW_DTCM_BYTES) // WEIGHT_BYTES
    if slots < 1:
        raise ValueError("no DTCM staging slot")
    resident = (tiles if tiles <= slots else slots - 1) if strategy == "prefix_cache" else 0
    misses = tiles + (ROUNDS - 1) * (tiles - resident)
    used_slots = resident + int(resident < tiles)
    return dict(dtcm_kib=kib, tiles=tiles, K=K, M=ROUNDS*16, N=tiles*16, rounds=ROUNDS, strategy=strategy,
                pool_slots=slots, resident_tiles=resident, used_slots=used_slots,
                weight_set_bytes=tiles * WEIGHT_BYTES,
                input_read_bytes=ROUNDS * WEIGHT_BYTES,
                weight_read_bytes=misses * WEIGHT_BYTES,
                output_write_bytes=ROUNDS * tiles * OUTPUT_BYTES,
                checked_elements=ROUNDS * tiles * 256,
                useful_macs=ROUNDS * tiles * 256 * K)


def vectors(tiles):
    if tiles not in TILE_CHOICES:
        raise ValueError("invalid tiles")
    x = np.arange(16 * K, dtype=np.int64).reshape(16, K)
    a = np.stack([((x * 37 + 11 + r * 19 + (x >> 8) * (r + 1)) % 256 - 128).astype(np.int8)
                  for r in range(ROUNDS)])
    y = np.arange(K * 16, dtype=np.int64).reshape(K, 16)
    b = np.stack([((y * 53 + t * 29 + (t >> 8) * 47 + (y >> 8) * (t + 3) * 7 + 7)
                   % 256 - 128).astype(np.int8) for t in range(tiles)])
    expected = (a.astype(np.int64)[:, None] @ b.astype(np.int64)[None]).astype("<i4")
    sha = hashlib.sha256(a.tobytes() + b.tobytes() + expected.tobytes()).hexdigest()
    return a, b, expected, sha


def classify_request(address, byte_count, tiles, writing=False):
    if byte_count <= 0:
        raise ValueError("empty AXI request")
    regions = (("output", EXT_OUT, ROUNDS * tiles * OUTPUT_BYTES),) if writing else (
        ("input", EXT_A, ROUNDS * WEIGHT_BYTES), ("weight", EXT_B, tiles * WEIGHT_BYTES))
    for name, base, size in regions:
        if base <= address and address + byte_count <= base + size:
            return name
    raise ValueError(f"unexpected external {'write' if writing else 'read'} {address:#x}+{byte_count}")


class TrafficCounter:
    """Counts handshakes, never valid-only cycles. No changes to AXI agents."""
    def __init__(self, tiles):
        self.tiles = tiles
        self.stats = dict(input_read_bytes=0, weight_read_bytes=0,
                          output_requested_bytes=0, output_write_bytes=0,
                          read_requests=0, write_requests=0, read_beats=0,
                          read_completed_bytes=0, read_completed_transactions=0,
                          write_beats=0, write_completed_transactions=0)
        self.pending_reads = {}
        self.pending_writes = {}

    def ar(self, address, size, length, ident):
        self._shape(address, size, length)
        nbytes = (length + 1) << size
        region = classify_request(address, nbytes, self.tiles)
        self.stats[region + "_read_bytes"] += nbytes
        self.stats["read_requests"] += 1
        self.pending_reads.setdefault(ident, []).append([size, length + 1])

    def aw(self, address, size, length, ident):
        self._shape(address, size, length)
        nbytes = (length + 1) << size
        classify_request(address, nbytes, self.tiles, writing=True)
        self.stats["output_requested_bytes"] += nbytes
        self.stats["write_requests"] += 1
        self.pending_writes[ident] = self.pending_writes.get(ident, 0) + 1

    @staticmethod
    def _shape(address, size, length):
        if (not 0 <= size <= 4 or not 0 <= length <= 255 or address < 0 or
                address // 4096 != (address + ((length + 1) << size) - 1) // 4096):
            raise ValueError("illegal AXI request geometry")

    def r(self, ident, last, response):
        if response != 0 or not self.pending_reads.get(ident):
            raise ValueError("failed/unmatched AXI read response")
        item = self.pending_reads[ident][0]
        self.stats["read_beats"] += 1
        self.stats["read_completed_bytes"] += 1 << item[0]
        item[1] -= 1
        if bool(last) != (item[1] == 0):
            raise ValueError("AXI RLAST mismatch")
        if last:
            self.pending_reads[ident].pop(0)
            self.stats["read_completed_transactions"] += 1

    def w(self, strobe):
        if not 0 <= strobe < 65536:
            raise ValueError("invalid 128bit AXI WSTRB")
        self.stats["output_write_bytes"] += strobe.bit_count()
        self.stats["write_beats"] += 1

    def b(self, ident, response):
        if response != 0 or self.pending_writes.get(ident, 0) == 0:
            raise ValueError("failed/unmatched AXI write response")
        self.pending_writes[ident] -= 1
        self.stats["write_completed_transactions"] += 1

    def finish(self, expected):
        if any(self.pending_reads.values()) or any(self.pending_writes.values()):
            raise ValueError("in-flight AXI requests at halt")
        for key in ("input_read_bytes", "weight_read_bytes", "output_write_bytes"):
            if self.stats[key] != expected[key]:
                raise ValueError("AXI byte count disagrees with copy plan: " + key)
        if (self.stats["read_completed_bytes"] != expected["input_read_bytes"] + expected["weight_read_bytes"] or
                self.stats["output_requested_bytes"] != expected["output_write_bytes"] or
                self.stats["read_requests"] != self.stats["read_completed_transactions"] or
                self.stats["write_requests"] != self.stats["write_completed_transactions"]):
            raise ValueError("incomplete AXI transactions")
        return dict(self.stats)


def check_elf_layout(entry, segments, symbols, sizes):
    if not 0 <= entry < 8192 or not segments:
        raise ValueError("invalid ITCM entry")
    for address, size in segments:
        if size and not (0 <= address < address + size <= 8192 or
                         DTCM_BASE <= address < address + size <= DTCM_BASE + LOW_DTCM_BYTES):
            raise ValueError("workset ELF must fit ITCM8K / low DTCM16K")
    if not any(address <= entry < address + size for address, size in segments):
        raise ValueError("entry outside ELF")
    ranges = []
    for name, length in SYMBOL_SIZES.items():
        address = symbols[name]
        if sizes[name] != length or not DTCM_BASE <= address < address + length <= DTCM_BASE + LOW_DTCM_BYTES:
            raise ValueError("invalid low-DTCM symbol: " + name)
        if address % (16 if name in ("ws_a", "ws_out") else 4):
            raise ValueError("unaligned symbol: " + name)
        if not any(start <= address and address + length <= start + size for start, size in segments):
            raise ValueError("symbol outside ELF segment: " + name)
        ranges.append((address, address + length))
    if any(a[1] > b[0] for a, b in zip(sorted(ranges), sorted(ranges)[1:])):
        raise ValueError("overlapping workset symbols")
