// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Compile-only probe. An object file is NOT an execution/RTL test.
#include "vme_tile.h"
extern "C" void PersonVmeCompileProbe(const int8_t* a, const uint8_t* b,
                                     const int32_t* bias, int32_t* out,
                                     uint32_t* commands) {
  person_vme::HardwareTile backend(commands);
  backend.Run(a, b, bias, 15, 13, 256, out);
}
