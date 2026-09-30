// Verification-only long-K variant of vme_matrix_perf_program.cc. Keep the
// established <=256 ELF unchanged; this probes accumulation across K=256.
#include <cstdint>

#include "vme_test_utils.h"

constexpr uint32_t kTe = 16;
constexpr uint32_t kMaxK = 528;
constexpr uint32_t kSew8Lmul1 = 0xC0;
constexpr uint32_t kSew32Lmul4 = 0xD2;

extern "C" {
uint8_t perf_a[(kMaxK + 4) * kTe]
    __attribute__((section(".data"), aligned(16))) = {};
uint8_t perf_b[(kMaxK + 4) * kTe]
    __attribute__((section(".data"), aligned(16))) = {};
uint32_t perf_out[kTe * kTe]
    __attribute__((section(".data"), aligned(16))) = {};
volatile uint32_t perf_k __attribute__((section(".data"))) = 272;
volatile uint32_t perf_tk __attribute__((section(".data"))) = 1;
volatile uint32_t perf_signed_b __attribute__((section(".data"))) = 1;
volatile uint32_t perf_status __attribute__((section(".data"))) = 0;
volatile uint32_t perf_mtype __attribute__((section(".data"))) = 0;
volatile uint32_t perf_vtype __attribute__((section(".data"))) = 0;
}

static inline __attribute__((always_inline)) void ConfigureMoves() {
  vme_msetmtype(MtypeValue(kTe, 1, 1), kSew32Lmul4);
  (void)vme_msettn(kTe);
}

static void Readback() {
  ConfigureMoves();
  for (uint32_t row = 0; row < kTe; ++row) {
    register uint32_t a0_arg asm("a0") = row;
    asm volatile(".word %0" : : "i"(kZvtVtmvVTWord), "r"(a0_arg)
                 : "v4", "v5", "v6", "v7", "memory");
    asm volatile("vse32.v v4, (%0)" : : "r"(&perf_out[row * kTe])
                 : "memory");
  }
}

int main() {
  const uint32_t k = perf_k;
  const uint32_t tk = perf_tk;
  if (k <= 256 || k > kMaxK || tk != 1 || perf_signed_b != 1) {
    perf_status = 2;
    return 0;
  }

  ConfigureMoves();
  asm volatile(".word %0" : : "i"(ZvtVtzeroWord(0)) : "memory");
  vme_msetmtype(MtypeValue(kTe, tk, 3), kSew8Lmul1 | (perf_signed_b << 8));
  (void)vme_msettn(kTe);
  perf_mtype = vme_read_mtype();
  uint32_t vtype;
  asm volatile("csrr %0, vtype" : "=r"(vtype));
  perf_vtype = vtype;

  for (uint32_t base = 0; base < k; ++base) {
    const uint8_t *a = &perf_a[base * kTe];
    const uint8_t *b = &perf_b[base * kTe];
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

  Readback();
  perf_status = 1;
  return 0;
}
