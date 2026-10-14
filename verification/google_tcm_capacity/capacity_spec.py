"""Pure configuration for a single-core, capacity-only experiment (not SoC)."""
import struct

UPSTREAM = "8e4df09b4ea7e065e02d14ce3ae033d40dfd973a"
TEAM = "95e06e872bff13b3625721a837b4b739a93bed6f"
CAPACITIES = (32, 128, 512, 1024, 2048, 4096)
ITCM_KIB = 8
DTCM_BASE = 0x01000000
CSR_BASE = 0x02000000
EXTERNAL_BASE = 0x20000000
BANK_BYTES = 8192
PATCHES = {
    "rtl/npu-generator-patches/0001-order-core-csr-addresses.patch":
        "a3cb2de716d3c14c1675ddf5ff638af6ac96b159a8f1cb0859bbd03da8b93acc",
    "rtl/npu-generator-patches/0002-fix-cvfpu-sticky-width-at-source.patch":
        "9bf28f7f33038ceb4c808910cde4da25d94a9bdea207bf4e664dabc7b1ef615b",
}


def geometry(kib):
    if kib not in CAPACITIES:
        raise ValueError("unsupported DTCM KiB: " + str(kib))
    size = kib * 1024
    if DTCM_BASE + size > CSR_BASE:
        raise ValueError("overlapping DTCM/CSR")
    top = ("VmeCoreMiniAxi" if kib == 32 else
           f"VmeCoreMini_ITCM8KB_DTCM{kib}KBAxi")
    return dict(itcm_kib=ITCM_KIB, dtcm_kib=kib, dtcm_bytes=size,
                dtcm_base=DTCM_BASE, csr_base=CSR_BASE,
                dtcm_banks=size // BANK_BYTES, bank_bytes=BANK_BYTES,
                hdl_top=top, package=f"tests/cocotb/tcm_capacity/d{kib}")


def probes(kib):
    """Distinct 16-byte words; write all first, then read all to detect aliases."""
    g = geometry(kib)
    addresses = [0, ITCM_KIB * 1024 - 16]
    for bank in range(g["dtcm_banks"]):
        start = DTCM_BASE + bank * BANK_BYTES
        addresses.extend((start, start + BANK_BYTES // 2,
                          start + BANK_BYTES - 16))
    return [(addr, struct.pack("<IIII", addr, addr ^ 0xA5C319EF,
                              addr ^ g["dtcm_bytes"], index))
            for index, addr in enumerate(addresses)]


def checked_parameters(text, kib):
    import re
    values = dict(re.findall(r"^#define\s+KP_(\w+)\s+(\S+)", text, re.M))
    expected = dict(xlen="32", axi2IdBits="6", itcmSizeKBytes="8", dtcmSizeKBytes=str(kib),
                    enableVerification="false", enableRvv="true",
                    enableVme="true", rvvVlen="128", enableFloat="true",
                    enableZfbfmin="true", enableVectorBf16="true",
                    enableAxiInstructionFetch="true", enableFetchL0="false",
                    fetchDataBits="128", lsuDataBits="128")
    for key, value in expected.items():
        if values.get(key) != value:
            raise ValueError(f"parameter {key}: {values.get(key)} != {value}")
    return expected
