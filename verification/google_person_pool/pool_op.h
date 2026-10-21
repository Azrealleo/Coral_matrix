// Copyright 2026. SPDX-License-Identifier: Apache-2.0
#pragma once
#include <cstdint>
#include "tensorflow/lite/micro/micro_common.h"
namespace person_pool { TFLMRegistration RegisterAveragePool(); }
extern "C" {
extern uint32_t pd_pool_calls,pd_pool_fallbacks,pd_pool_vector_blocks,pd_pool_emulated_blocks;
extern uint32_t pd_pool_validated,pd_pool_mismatches;
}
