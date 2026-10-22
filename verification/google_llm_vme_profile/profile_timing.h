// Diagnostic probes perturb scheduling. Never call these pure array cycles.
#pragma once
#include <cstdint>
namespace llm_vme {
enum ProfilePhase { kInputPack, kAccumulatorInit, kLoadIssue, kReadback, kOutputLayout, kPhases };
inline uint32_t ProfileCycle() {
#ifdef LV_HOST
  return 0;
#else
  uint32_t value;asm volatile("fence rw,rw\ncsrr %0,mcycle":"=r"(value)::"memory");return value;
#endif
}
struct ProfileStats {
  uint32_t cycles[kPhases]{};
  uint32_t counts[kPhases]{};
  void Add(ProfilePhase phase,uint32_t elapsed) {cycles[phase]+=elapsed;++counts[phase];}
};
}
