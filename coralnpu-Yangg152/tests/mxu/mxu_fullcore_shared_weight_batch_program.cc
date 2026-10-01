// Verification-only full-core batch: one launch, multiple 16x16 signed-INT8
// outputs. Weight SRAM is loaded once and reused; no production RTL/SW edit.
#include <cstdint>

constexpr uint32_t kTile = 16;
constexpr uint32_t kMaxK = 256;
constexpr uint32_t kMaxTiles = 16;

extern "C" {
uint8_t batch_a[kMaxTiles * kTile * kMaxK]
    __attribute__((section(".extbss"), aligned(16)));
uint8_t batch_b[kMaxK * kTile]
    __attribute__((section(".extbss"), aligned(16)));
uint32_t batch_out[kMaxTiles * kTile * kTile]
    __attribute__((section(".extbss"), aligned(16)));
volatile uint32_t batch_k __attribute__((section(".data"))) = 16;
volatile uint32_t batch_tiles __attribute__((section(".data"))) = 1;
volatile uint32_t batch_reload_weights __attribute__((section(".data"))) = 0;
volatile uint32_t batch_status __attribute__((section(".data"))) = 0;
}

static inline __attribute__((always_inline)) void Configure(uint32_t k) {
  register uint32_t a0_val asm("a0") = ((k == 256 ? 0 : k) | 0x100u);
  asm volatile(".word 0x02051057" :: "r"(a0_val) : "memory");
}

static inline __attribute__((always_inline)) void Zero() {
  asm volatile(".word 0x0E001057" ::: "memory");
}

static inline __attribute__((always_inline)) void LoadA(const uint8_t *src,
                                                         bool last) {
  if (last) {
    asm volatile("vsetvli zero, %1, e8, m1, ta, ma\n\t"
                 "vle8.v v16, (%0)\n\t"
                 ".word 0x09001057"
                 :: "r"(src), "r"(16) : "memory", "v16");
  } else {
    asm volatile("vsetvli zero, %1, e8, m1, ta, ma\n\t"
                 "vle8.v v16, (%0)\n\t"
                 ".word 0x0B001057"
                 :: "r"(src), "r"(16) : "memory", "v16");
  }
}

static inline __attribute__((always_inline)) void LoadW(const uint8_t *src,
                                                         bool last) {
  if (last) {
    asm volatile("vsetvli zero, %1, e8, m1, ta, ma\n\t"
                 "vle8.v v16, (%0)\n\t"
                 ".word 0x05001057"
                 :: "r"(src), "r"(16) : "memory", "v16");
  } else {
    asm volatile("vsetvli zero, %1, e8, m1, ta, ma\n\t"
                 "vle8.v v16, (%0)\n\t"
                 ".word 0x07001057"
                 :: "r"(src), "r"(16) : "memory", "v16");
  }
}

static inline __attribute__((always_inline)) void MultiplyAccumulate() {
  asm volatile(".word 0x12001057" ::: "memory");
}

static inline __attribute__((always_inline)) void Store(uint32_t *dst) {
  asm volatile(".word 0x16001857\n\t"
               "vsetvli zero, %1, e32, m1, ta, ma\n\t"
               "vse32.v v16, (%0)"
               :: "r"(dst), "r"(4) : "memory", "v16");
}

int main() {
  const uint32_t k = batch_k;
  const uint32_t tiles = batch_tiles;
  if ((k != 16 && k != 64 && k != 256) ||
      (tiles != 1 && tiles != 4 && tiles != 16) ||
      batch_reload_weights > 1) {
    batch_status = 2;
    return 0;
  }
  asm volatile("vsetvli zero, %0, e8, m1, ta, ma"
               :: "r"(kTile) : "memory");
  Configure(k);
  for (uint32_t tile = 0; tile < tiles; ++tile) {
    const uint8_t *a = &batch_a[tile * kMaxK * kTile];
    Zero();
    for (uint32_t row = 0; row < kTile; ++row) {
      for (uint32_t chunk = 0; chunk < k / kTile; ++chunk) {
        const bool last = row == kTile - 1 && chunk == k / kTile - 1;
        LoadA(&a[row * k + chunk * kTile], last);
      }
    }
    if (tile == 0 || batch_reload_weights != 0) {
      for (uint32_t depth = 0; depth < k; ++depth)
        LoadW(&batch_b[depth * kTile], depth == k - 1);
    }
    MultiplyAccumulate();
    for (uint32_t beat = 0; beat < 64; ++beat)
      Store(&batch_out[tile * kTile * kTile + beat * 4]);
  }
  batch_status = 1;
  return 0;
}
