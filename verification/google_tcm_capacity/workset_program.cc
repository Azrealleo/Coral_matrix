// Fixed input-major scheduling experiment, not an optimized model runtime.
// Runtime capacity changes prefix residency only; same ELF for all capacities.
#include <cstdint>
#include "vme_test_utils.h"

constexpr uint32_t kBlock = 4096, kRows = 16, kK = 256, kRounds = 3;
constexpr uintptr_t kExtA = 0x20000000, kExtB = 0x20010000;
constexpr uintptr_t kExtOut = 0x20400000, kPool = 0x01004000;
extern "C" {
uint8_t ws_a[kBlock] __attribute__((section(".data"), aligned(16))) = {};
uint32_t ws_out[256] __attribute__((section(".data"), aligned(16))) = {};
volatile uint32_t ws_tiles __attribute__((section(".data"))) = 12;
volatile uint32_t ws_dtcm_kib __attribute__((section(".data"))) = 32;
volatile uint32_t ws_cache __attribute__((section(".data"))) = 0;
volatile uint32_t ws_status __attribute__((section(".data"))) = 0;
volatile uint32_t ws_input_bytes __attribute__((section(".data"))) = 0;
volatile uint32_t ws_weight_bytes __attribute__((section(".data"))) = 0;
volatile uint32_t ws_output_bytes __attribute__((section(".data"))) = 0;
volatile uint32_t ws_input_cycles __attribute__((section(".data"))) = 0;
volatile uint32_t ws_weight_cycles __attribute__((section(".data"))) = 0;
volatile uint32_t ws_compute_cycles __attribute__((section(".data"))) = 0;
volatile uint32_t ws_output_cycles __attribute__((section(".data"))) = 0;
volatile uint32_t ws_total_cycles __attribute__((section(".data"))) = 0;
volatile uint32_t ws_round_cycles[3] __attribute__((section(".data"))) = {};
}

static inline __attribute__((always_inline)) uint32_t Cycles() {
  uint32_t value;
  asm volatile("fence rw, rw\ncsrr %0, 0xb00" : "=r"(value) : : "memory");
  return value;
}

static void Copy16(void *dst, const void *src, uint32_t bytes) {
  auto *d = static_cast<uint8_t *>(dst);
  auto *s = static_cast<const uint8_t *>(src);
  // Each load/store is a complete aligned 128-bit line, no libc memcpy.
  asm volatile("vsetivli zero, 16, e8, m1, ta, ma" : : : "memory");
  for (uint32_t i = 0; i < bytes; i += 16) {
    asm volatile("vle8.v v0, (%0)\nvse8.v v0, (%1)"
                 : : "r"(s + i), "r"(d + i) : "v0", "memory");
  }
}

static inline __attribute__((always_inline)) void Moves() {
  vme_msetmtype(MtypeValue(16, 1, 1), 0xD2);
  (void)vme_msettn(16);
}

static void Matmul(const uint8_t *weight) {
  Moves();
  asm volatile(".word %0" : : "i"(ZvtVtzeroWord(0)) : "memory");
  vme_msetmtype(MtypeValue(16, 4, 3), 0x1C0);
  (void)vme_msettn(16);
  for (uint32_t base = 0; base < kK; base += 4) {
    const uint8_t *a = ws_a + base * 16;
    const uint8_t *b = weight + base * 16;
    asm volatile("vle8.v v8, (%0)\nvle8.v v10, (%1)\nvle8.v v12, (%2)\nvle8.v v14, (%3)"
                 : : "r"(a), "r"(a + 16), "r"(a + 32), "r"(a + 48)
                 : "v8", "v10", "v12", "v14", "memory");
    asm volatile("vle8.v v16, (%0)\nvle8.v v18, (%1)\nvle8.v v20, (%2)\nvle8.v v22, (%3)"
                 : : "r"(b), "r"(b + 16), "r"(b + 32), "r"(b + 48)
                 : "v16", "v18", "v20", "v22", "memory");
    asm volatile(".word %0" : : "i"(ZvtMatmulIntWord(0, true)) : "memory");
  }
  Moves();
  for (uint32_t row = 0; row < kRows; ++row) {
    register uint32_t a0_arg asm("a0") = row;
    asm volatile(".word %0" : : "i"(kZvtVtmvVTWord), "r"(a0_arg)
                 : "v4", "v5", "v6", "v7", "memory");
    asm volatile("vse32.v v4, (%0)" : : "r"(ws_out + row * 16) : "memory");
  }
}

int main() {
  const uint32_t tiles = ws_tiles, kib = ws_dtcm_kib, cache = ws_cache;
  if ((tiles != 2 && tiles != 12 && tiles != 120 && tiles != 192 && tiles != 384 && tiles != 768) ||
      (kib != 32 && kib != 128 && kib != 512 && kib != 1024 && kib != 2048 && kib != 4096) || cache > 1) {
    ws_status = 2;
    return 0;
  }
  const uint32_t slots = (kib * 1024 - 16384) / kBlock;
  const uint32_t resident = cache ? (tiles <= slots ? tiles : slots - 1) : 0;
  const uint32_t begin = Cycles();
  for (uint32_t round = 0; round < kRounds; ++round) {
    const uint32_t round_begin = Cycles();
    uint32_t stamp = Cycles();
    Copy16(ws_a, reinterpret_cast<const void *>(kExtA + round * kBlock), kBlock);
    ws_input_cycles += Cycles() - stamp;
    ws_input_bytes += kBlock;
    for (uint32_t tile = 0; tile < tiles; ++tile) {
      auto *weight = reinterpret_cast<uint8_t *>(kPool + (tile < resident ? tile : resident) * kBlock);
      // Same number of timing reads/barriers on hits and misses.
      stamp = Cycles();
      if (round == 0 || tile >= resident) {
        Copy16(weight, reinterpret_cast<const void *>(kExtB + tile * kBlock), kBlock);
        ws_weight_bytes += kBlock;
      }
      ws_weight_cycles += Cycles() - stamp;
      stamp = Cycles();
      Matmul(weight);
      ws_compute_cycles += Cycles() - stamp;
      stamp = Cycles();
      Copy16(reinterpret_cast<void *>(kExtOut + (round * tiles + tile) * 1024), ws_out, 1024);
      ws_output_cycles += Cycles() - stamp;
      ws_output_bytes += 1024;
    }
    ws_round_cycles[round] = Cycles() - round_begin;
  }
  ws_total_cycles = Cycles() - begin;
  ws_status = 1;
  return 0;
}
