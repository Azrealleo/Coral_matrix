// Fixed-model functional baseline; not a VME-accelerated kernel library.
#pragma once
#include <cstdint>
constexpr unsigned kPersonModelBytes = 300568;
constexpr unsigned kPersonInputBytes = 96 * 96;
constexpr unsigned kPersonArenaBytes = 160 * 1024;
extern "C" {
extern const unsigned char pd_model[kPersonModelBytes];
extern int8_t pd_input[kPersonInputBytes];
extern int8_t pd_output[2];
extern uint8_t pd_tensor_arena[kPersonArenaBytes];
extern volatile uint32_t pd_status, pd_arena_used, pd_invoke_cycles;
}
