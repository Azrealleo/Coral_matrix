"""Single official NPU: vary ITCM only; stage 1 is not a performance test."""
import re
import struct

UPSTREAM = "8e4df09b4ea7e065e02d14ce3ae033d40dfd973a"
CAPACITIES = (8, 16, 32, 64, 128)
DTCM_KIB = 2048
DTCM_BASE = 0x01000000
CSR_BASE = 0x02000000
BLOCK_BYTES = 8192
SCOPE = "single_npu_itcm_frontdoor_geometry_not_performance"


def geometry(kib):
    if type(kib) is not int or kib not in CAPACITIES:
        raise ValueError("ITCM KiB must be 8/16/32/64/128")
    size = kib * 1024
    if size > DTCM_BASE:
        raise ValueError("ITCM overlaps DTCM")
    return dict(itcm_kib=kib, itcm_base=0, itcm_bytes=size,
                dtcm_kib=DTCM_KIB, dtcm_base=DTCM_BASE, csr_base=CSR_BASE,
                probe_block_bytes=BLOCK_BYTES, itcm_probe_blocks=size // BLOCK_BYTES,
                hdl_top=f"VmeCoreMini_ITCM{kib}KB_DTCM{DTCM_KIB}KBAxi",
                package=f"tests/cocotb/itcm_capacity/i{kib}")


def probes(kib):
    """Unique first/middle/last words per 8KiB slice, plus two DTCM guards."""
    g = geometry(kib)
    addresses = []
    for start in range(0, g["itcm_bytes"], BLOCK_BYTES):
        addresses.extend((start, start + BLOCK_BYTES // 2, start + BLOCK_BYTES - 16))
    addresses.extend((DTCM_BASE, DTCM_BASE + DTCM_KIB * 1024 - 16))
    return [(addr, struct.pack("<IIII", addr, addr ^ 0xA5C319EF,
                              addr ^ g["itcm_bytes"], i))
            for i, addr in enumerate(addresses)]


def mask_addresses(kib):
    g = geometry(kib)
    return sorted({0, g["itcm_bytes"] - 16, DTCM_BASE,
                   DTCM_BASE + DTCM_KIB * 1024 - 16})


def checked_parameters(text, kib):
    geometry(kib)
    values = dict(re.findall(r"^#define\s+KP_(\w+)\s+(\S+)", text, re.M))
    expected = dict(xlen="32", axi2IdBits="6", itcmSizeKBytes=str(kib),
                    dtcmSizeKBytes=str(DTCM_KIB), enableVerification="false",
                    enableRvv="true", enableVme="true", rvvVlen="128",
                    enableFloat="true", enableZfbfmin="true", enableVectorBf16="true",
                    enableAxiInstructionFetch="true", enableFetchL0="false",
                    fetchDataBits="128", lsuDataBits="128")
    for key, value in expected.items():
        if values.get(key) != value:
            raise ValueError(f"parameter {key}: {values.get(key)} != {value}")
    return expected
