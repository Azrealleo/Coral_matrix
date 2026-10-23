// Copyright 2026. SPDX-License-Identifier: Apache-2.0
#pragma once
#include <cstdint>
namespace llm_vme {
#ifndef LV_HOST
// Two full output-channel tiles: A0 at v8/10/12/14, shared B at
// v16/18/20/22, A1 at v24/26/28/30. No source group exceeds v31.
// Old ISA rd=(tile<<1)|signed_A: tile0=0xf28800f7, tile4=0xf38804f7
// (the latter also changes vs2 from v8 to v24). No signed-B/ISA upgrade.
template<bool Partial>
inline __attribute__((noinline)) void PairKLoop(
    const int8_t* a0,const int8_t* a1,const uint8_t* b,int tokens,int kp,
    uint32_t* commands) {
  uint32_t steps=static_cast<uint32_t>(kp/4),issued=0;
  asm volatile(
    "li t0,16515\nli t1,192\n"
    ".insn r 0x57,7,0x41,x0,t0,t1\n"
    "li t0,16\n.insn r 0x57,7,0x42,x0,t0,x0\n"
    "1:\n"
    ".if %c[partial]\n.insn r 0x57,7,0x42,x0,t0,x0\n.endif\n"
    "vle8.v v8,(%[a0])\naddi %[a0],%[a0],16\n"
    "vle8.v v10,(%[a0])\naddi %[a0],%[a0],16\n"
    "vle8.v v12,(%[a0])\naddi %[a0],%[a0],16\n"
    "vle8.v v14,(%[a0])\naddi %[a0],%[a0],16\n"
    "vle8.v v16,(%[b])\naddi %[b],%[b],16\n"
    "vle8.v v18,(%[b])\naddi %[b],%[b],16\n"
    "vle8.v v20,(%[b])\naddi %[b],%[b],16\n"
    "vle8.v v22,(%[b])\naddi %[b],%[b],16\n"
    "vle8.v v24,(%[a1])\naddi %[a1],%[a1],16\n"
    "vle8.v v26,(%[a1])\naddi %[a1],%[a1],16\n"
    "vle8.v v28,(%[a1])\naddi %[a1],%[a1],16\n"
    "vle8.v v30,(%[a1])\naddi %[a1],%[a1],16\n"
    ".if %c[partial]\n.insn r 0x57,7,0x42,x0,%[tokens],x0\n.endif\n"
    ".word 0xf28800f7\naddi %[issued],%[issued],1\n"
    ".word 0xf38804f7\naddi %[issued],%[issued],1\n"
    "addi %[steps],%[steps],-1\nbnez %[steps],1b\n"
    : [a0] "+&r"(a0),[a1] "+&r"(a1),[b] "+&r"(b),
      [steps] "+&r"(steps),[issued] "+&r"(issued)
    : [tokens] "r"(tokens),[partial] "i"(Partial?1:0)
    : "t0","t1","v8","v10","v12","v14","v16","v18","v20","v22",
      "v24","v26","v28","v30","vl","vtype","memory");
  *commands+=issued; // executed software iterations, NOT hardware retire count
}
#endif
} // namespace llm_vme
