// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Scheduling adapted from cheshire-coral-soc fa4b83e4:
// sw/models/h4-resnet8/npu.cc (Google LLC, Apache-2.0).
// Encodings: pinned official tests/cocotb/vme_test/vme_test_utils.h.
#pragma once
#include <cstdint>

namespace person_vme {
// All configuration and vector register effects are kept in single asm blocks.
// Build this translation unit with auto-vectorization disabled. No vector ABI
// live values may cross a VME call; do not enable LTO on this experiment.
struct HardwareTile {
  uint32_t* commands;
  explicit HardwareTile(uint32_t* count) : commands(count) {}
  void Run(const int8_t* a, const uint8_t* b, const int32_t* bias,
           int m, int n, int k, int32_t* out) {
    alignas(16) int32_t row[16];
    const uint32_t move_type = (16u << 10) | (1u << 5) | 1u;
    for (int r = 0; r < 16; ++r) {
      for (int c = 0; c < 16; ++c) row[c] = r < m && c < n ? bias[r] : 0;
      // A compiler-generated memset for the row fill may use RVV and change
      // vl/vtype. Configure AFTER all C++ filling and before the vector load.
      Set(move_type, 0xd2, 16, 16);
      register uint32_t index asm("a0") = r;
      asm volatile("vle32.v v4,(%0)\n.word 0x5e456057"
                   : : "r"(row), "r"(index) : "v4", "v5", "v6", "v7", "memory");
    }
    // K is padded to four with zero weights/inputs, avoiding stale lanes and
    // out-of-range loads in the last Tk4 command.
    for (int d = 0; d < k; d += 4) {
      Set((16u << 10) | (4u << 5) | 3u, 0xc0, m, 16);
      const int8_t* pa = a + d * 16;
      const uint8_t* pb = b + d * 16;
      asm volatile("vle8.v v8,(%0)\nvle8.v v10,(%1)\nvle8.v v12,(%2)\nvle8.v v14,(%3)"
                   : : "r"(pa), "r"(pa+16), "r"(pa+32), "r"(pa+48)
                   : "v8", "v10", "v12", "v14", "memory");
      asm volatile("vle8.v v16,(%0)\nvle8.v v18,(%1)\nvle8.v v20,(%2)\nvle8.v v22,(%3)"
                   : : "r"(pb), "r"(pb+16), "r"(pb+32), "r"(pb+48)
                   : "v16", "v18", "v20", "v22", "memory");
      register uint32_t width asm("a0") = n;
      // msettn t0,a0; vtmms tile0,v8,v16. B is unsigned by ISA design.
      asm volatile(".insn r 0x57,7,0x42,t0,a0,x0\n.word 0xf28800f7"
                   : : "r"(width) : "t0", "vl", "memory");
      ++*commands;  // Issued commands; NOT an independent retire counter.
    }
    Set(move_type, 0xd2, 16, 16);
    for (int r = 0; r < 16; ++r) {
      register uint32_t index asm("a0") = r;
      asm volatile(".word 0x43f56257\nvse32.v v4,(%0)"
                   : : "r"(out+r*16), "r"(index)
                   : "v4", "v5", "v6", "v7", "memory");
    }
  }
 private:
  static inline __attribute__((always_inline)) void Set(
      uint32_t mt, uint32_t vt, uint32_t m, uint32_t n) {
    register uint32_t type asm("a0") = mt;
    register uint32_t vtype asm("a1") = vt;
    asm volatile(".insn r 0x57,7,0x41,x0,a0,a1"
                 : : "r"(type), "r"(vtype) : "vl", "vtype", "memory");
    register uint32_t rows asm("a0") = m;
    asm volatile(".insn r 0x57,7,0x42,t0,a0,x1" : : "r"(rows) : "t0", "memory");
    register uint32_t cols asm("a0") = n;
    asm volatile(".insn r 0x57,7,0x42,t0,a0,x0" : : "r"(cols) : "t0", "vl", "memory");
  }
};
}  // namespace person_vme
