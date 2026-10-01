// Verification-only full-core batch: one launch, multiple 16x16 signed-INT8
// outputs, distinct A per tile and one shared B. No production RTL/SW change.
#include <cstdint>

#include "vme_test_utils.h"

constexpr uint32_t kTe = 16;
constexpr uint32_t kMaxK = 256;
constexpr uint32_t kMaxTiles = 16;
constexpr uint32_t kSew8Lmul1 = 0xC0;
constexpr uint32_t kSew32Lmul4 = 0xD2;

extern "C" {
uint8_t batch_a[kMaxTiles * kMaxK * kTe]
    __attribute__((section(".data"), aligned(16))) = {};
uint8_t batch_b[kMaxK * kTe]
    __attribute__((section(".data"), aligned(16))) = {};
uint32_t batch_out[kMaxTiles * kTe * kTe]
    __attribute__((section(".data"), aligned(16))) = {};
volatile uint32_t batch_k __attribute__((section(".data"))) = 16;
volatile uint32_t batch_tiles __attribute__((section(".data"))) = 1;
volatile uint32_t batch_status __attribute__((section(".data"))) = 0;
}

static inline __attribute__((always_inline)) void ConfigureMoves() {
  vme_msetmtype(MtypeValue(kTe, 1, 1), kSew32Lmul4);
  (void)vme_msettn(kTe);
}

static void Readback(uint32_t *dst) {
  ConfigureMoves();
  for (uint32_t row = 0; row < kTe; ++row) {
    register uint32_t a0_arg asm("a0") = row;
    asm volatile(".word %0" : : "i"(kZvtVtmvVTWord), "r"(a0_arg)
                 : "v4", "v5", "v6", "v7", "memory");
    asm volatile("vse32.v v4, (%0)" : : "r"(&dst[row * kTe]) : "memory");
  }
}

int main() {
  const uint32_t k = batch_k;
  const uint32_t tiles = batch_tiles;
  if ((k != 16 && k != 64 && k != 256) ||
      (tiles != 1 && tiles != 4 && tiles != 16)) {
    batch_status = 2;
    return 0;
  }
  for (uint32_t tile = 0; tile < tiles; ++tile) {
    ConfigureMoves();
    asm volatile(".word %0" : : "i"(ZvtVtzeroWord(0)) : "memory");
    vme_msetmtype(MtypeValue(kTe, 4, 3), kSew8Lmul1 | (1u << 8));
    (void)vme_msettn(kTe);
    for (uint32_t base = 0; base < k; base += 4) {
      const uint8_t *a = &batch_a[tile * kMaxK * kTe + base * kTe];
      const uint8_t *b = &batch_b[base * kTe];
      asm volatile(
          "vle8.v v8,  (%0)\n"
          "vle8.v v10, (%1)\n"
          "vle8.v v12, (%2)\n"
          "vle8.v v14, (%3)\n"
          : : "r"(a), "r"(a + kTe), "r"(a + 2 * kTe), "r"(a + 3 * kTe)
          : "v8", "v10", "v12", "v14", "memory");
      asm volatile(
          "vle8.v v16, (%0)\n"
          "vle8.v v18, (%1)\n"
          "vle8.v v20, (%2)\n"
          "vle8.v v22, (%3)\n"
          : : "r"(b), "r"(b + kTe), "r"(b + 2 * kTe), "r"(b + 3 * kTe)
          : "v16", "v18", "v20", "v22", "memory");
      asm volatile(".word %0" : : "i"(ZvtMatmulIntWord(0, true)) : "memory");
    }
    Readback(&batch_out[tile * kTe * kTe]);
  }
  batch_status = 1;
  return 0;
}
