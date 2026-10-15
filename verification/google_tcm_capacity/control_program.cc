// Verification-only small working-set control; same ELF for all capacities.
// Kernel follows the previously exercised Tk=4 VME test, no RTL changes.
#include <cstdint>

#include "vme_test_utils.h"

constexpr uint32_t kTe = 16;
constexpr uint32_t kMaxK = 256;
extern "C" {
uint8_t ctrl_a[(kMaxK + 4) * kTe]
    __attribute__((section(".data"), aligned(16))) = {};
uint8_t ctrl_b[(kMaxK + 4) * kTe]
    __attribute__((section(".data"), aligned(16))) = {};
uint32_t ctrl_out[kTe * kTe]
    __attribute__((section(".data"), aligned(16))) = {};
volatile uint32_t ctrl_k __attribute__((section(".data"))) = 16;
volatile uint32_t ctrl_status __attribute__((section(".data"))) = 0;
volatile uint32_t ctrl_mtype __attribute__((section(".data"))) = 0;
volatile uint32_t ctrl_vtype __attribute__((section(".data"))) = 0;
}

static inline __attribute__((always_inline)) void ConfigureMoves() {
  vme_msetmtype(MtypeValue(kTe, 1, 1), 0xD2);  // SEW32, LMUL4.
  (void)vme_msettn(kTe);
}

int main() {
  const uint32_t k = ctrl_k;
  if (k != 16 && k != 64 && k != 256) {
    ctrl_status = 2;
    return 0;
  }
  ConfigureMoves();
  asm volatile(".word %0" : : "i"(ZvtVtzeroWord(0)) : "memory");
  // Signed A in the opcode, signed B via altfmt bit8 of vtype.
  vme_msetmtype(MtypeValue(kTe, 4, 3), 0xC0 | (1u << 8));
  (void)vme_msettn(kTe);
  ctrl_mtype = vme_read_mtype();
  uint32_t vtype;
  asm volatile("csrr %0, vtype" : "=r"(vtype));
  ctrl_vtype = vtype;
  for (uint32_t base = 0; base < k; base += 4) {
    const uint8_t *a = &ctrl_a[base * kTe];
    const uint8_t *b = &ctrl_b[base * kTe];
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
  ConfigureMoves();
  for (uint32_t row = 0; row < kTe; ++row) {
    register uint32_t a0_arg asm("a0") = row;
    asm volatile(".word %0" : : "i"(kZvtVtmvVTWord), "r"(a0_arg)
                 : "v4", "v5", "v6", "v7", "memory");
    asm volatile("vse32.v v4, (%0)" : : "r"(&ctrl_out[row * kTe])
                 : "memory");
  }
  ctrl_status = 1;
  return 0;
}
