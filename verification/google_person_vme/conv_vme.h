// Copyright 2026. SPDX-License-Identifier: Apache-2.0
#pragma once
#include <cstdint>
#include "tensorflow/lite/micro/micro_common.h"
namespace person_vme {
TFLMRegistration RegisterPointwise();
}
extern "C" {
extern uint32_t pd_vme_conv_calls, pd_vme_fallback_calls;
extern uint32_t pd_vme_commands, pd_vme_emulated_tiles;
extern uint32_t pd_vme_validated_layers, pd_vme_mismatches;
extern uint32_t pd_vme_first_bad_index;
}
