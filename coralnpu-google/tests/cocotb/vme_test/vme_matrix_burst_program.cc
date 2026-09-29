// Verification-only reused-operand stream, NOT a general GEMM kernel.
// Load one 16x4 A / 4x16 B chunk once, then issue consecutive instructions
// accumulating the SAME Tile 0. There are no loads or scalar loop branches
// between matrix instructions. The harness checks all final INT32 elements.
#include <cstdint>

#include "vme_test_utils.h"

constexpr uint32_t kTe = 16;
constexpr uint32_t kMaxK = 256;
constexpr uint32_t kSew8Lmul1 = 0xC0;
constexpr uint32_t kSew32Lmul4 = 0xD2;

extern "C" {
// Keep the common harness's upload layout; only the first four rows are used.
uint8_t perf_a[(kMaxK + 4) * kTe]
    __attribute__((section(".data"), aligned(16))) = {};
uint8_t perf_b[(kMaxK + 4) * kTe]
    __attribute__((section(".data"), aligned(16))) = {};
uint32_t perf_out[kTe * kTe]
    __attribute__((section(".data"), aligned(16))) = {};
volatile uint32_t perf_k __attribute__((section(".data"))) = 16;
volatile uint32_t perf_tk __attribute__((section(".data"))) = 4;
volatile uint32_t perf_signed_b __attribute__((section(".data"))) = 1;
volatile uint32_t perf_status __attribute__((section(".data"))) = 0;
volatile uint32_t perf_mtype __attribute__((section(".data"))) = 0;
volatile uint32_t perf_vtype __attribute__((section(".data"))) = 0;
}

static inline __attribute__((always_inline)) void ConfigureMoves() {
  vme_msetmtype(MtypeValue(kTe, 1, 1), kSew32Lmul4);
  (void)vme_msettn(kTe);
}

template <uint32_t Repeats>
static inline __attribute__((always_inline)) void MatrixBurst() {
  asm volatile(".rept %1\n.word %0\n.endr\n"
               : : "i"(ZvtMatmulIntWord(0, true)), "i"(Repeats) : "memory");
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
  if ((k != 16 && k != 64 && k != 256) || perf_tk != 4 ||
      perf_signed_b > 1) {
    perf_status = 2;
    return 0;
  }
  ConfigureMoves();
  asm volatile(".word %0" : : "i"(ZvtVtzeroWord(0)) : "memory");
  vme_msetmtype(MtypeValue(kTe, 4, 3),
               kSew8Lmul1 | (perf_signed_b << 8));
  (void)vme_msettn(kTe);
  perf_mtype = vme_read_mtype();
  uint32_t vtype;
  asm volatile("csrr %0, vtype" : "=r"(vtype));
  perf_vtype = vtype;

  const uint8_t *a = perf_a;
  const uint8_t *b = perf_b;
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
  // Selection happens before each straight-line stream, not between commands.
  switch (k) {
    case 16: MatrixBurst<4>(); break;
    case 64: MatrixBurst<16>(); break;
    case 256: MatrixBurst<64>(); break;
  }
  Readback();
  perf_status = 1;
  return 0;
}
