// Verification-only full-core INT8 tile program. No TFLM, im2col or RTL edit.
// Mirrors the fork's existing MXU instruction wrappers in sw/opt/litert-micro/mxu.cc.
#include <cstdint>

constexpr uint32_t kTile = 16;
constexpr uint32_t kMaxK = 256;

extern "C" {
uint8_t bench_a[kTile * kMaxK]
    __attribute__((section(".data"), aligned(16))) = {};
uint8_t bench_b[kMaxK * kTile]
    __attribute__((section(".data"), aligned(16))) = {};
uint32_t bench_out[kTile * kTile]
    __attribute__((section(".data"), aligned(16))) = {};
volatile uint32_t bench_k_hw __attribute__((section(".data"))) = 16;
volatile uint32_t bench_status __attribute__((section(".data"))) = 0;
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
  const uint32_t k = bench_k_hw;
  if (k < 16 || k > kMaxK || k % 16 != 0) {
    bench_status = 2;
    return 0;
  }
  Configure(k);
  Zero();
  for (uint32_t row = 0; row < kTile; ++row) {
    for (uint32_t chunk = 0; chunk < k / kTile; ++chunk) {
      const bool last = row == kTile - 1 && chunk == k / kTile - 1;
      LoadA(&bench_a[row * k + chunk * kTile], last);
    }
  }
  for (uint32_t depth = 0; depth < k; ++depth)
    LoadW(&bench_b[depth * kTile], depth == k - 1);
  MultiplyAccumulate();
  for (uint32_t beat = 0; beat < 64; ++beat)
    Store(&bench_out[beat * 4]);
  bench_status = 1;
  return 0;
}
