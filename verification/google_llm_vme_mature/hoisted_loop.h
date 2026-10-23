// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Original Coral adaptation of configure-once / accumulator-resident GEMM.
// Design references and exact revisions are documented in SOURCES.md.
#pragma once
#include <cstdint>

namespace llm_vme {
#ifndef LV_HOST
// Packed operands contain four 16-byte rows per Tk4. Keep all configuration
// and the complete K loop in ONE asm statement: neither the compiler nor a
// helper may insert an ordinary VSET (which clears mtype) inside this window.
// Full-width and partial-width instantiations are audited separately in ELF.
template<bool Partial>
inline __attribute__((noinline)) void HoistedKLoop(
    const int8_t* a,const uint8_t* b,int channels,int tokens,int kp,
    uint32_t* commands) {
  uint32_t steps=static_cast<uint32_t>(kp/4),issued=0;
  asm volatile(
    "li t0,16515\n" // TM16 | TK4 | TWIDEN4. Old pinned Zvt encodings.
    "li t1,192\n"   // SEW8, LMUL1, ta/ma, altfmt=0: B stays UNSIGNED.
    ".insn r 0x57,7,0x41,x0,t0,t1\n"
    ".insn r 0x57,7,0x42,x0,%[channels],x1\n"
    "li t0,16\n"
    ".insn r 0x57,7,0x42,x0,t0,x0\n"
    "1:\n"
    ".if %c[partial]\n"
    ".insn r 0x57,7,0x42,x0,t0,x0\n" // full operand loads
    ".endif\n"
    "vle8.v v8,(%[a])\naddi %[a],%[a],16\n"
    "vle8.v v10,(%[a])\naddi %[a],%[a],16\n"
    "vle8.v v12,(%[a])\naddi %[a],%[a],16\n"
    "vle8.v v14,(%[a])\naddi %[a],%[a],16\n"
    "vle8.v v16,(%[b])\naddi %[b],%[b],16\n"
    "vle8.v v18,(%[b])\naddi %[b],%[b],16\n"
    "vle8.v v20,(%[b])\naddi %[b],%[b],16\n"
    "vle8.v v22,(%[b])\naddi %[b],%[b],16\n"
    ".if %c[partial]\n"
    ".insn r 0x57,7,0x42,x0,%[tokens],x0\n" // compute only valid tokens
    ".endif\n"
    ".word 0xf28800f7\n" // unchanged signed-A / unsigned-B matmul, tile0
    "addi %[issued],%[issued],1\n"
    "addi %[steps],%[steps],-1\n"
    "bnez %[steps],1b\n"
    : [a] "+&r"(a),[b] "+&r"(b),[steps] "+&r"(steps),[issued] "+&r"(issued)
    : [channels] "r"(channels),[tokens] "r"(tokens),[partial] "i"(Partial?1:0)
    : "t0","t1","v8","v10","v12","v14","v16","v18","v20","v22",
      "vl","vtype","memory");
  // Software record of loop iterations, NOT an independent hardware counter.
  *commands+=issued;
}
#endif
} // namespace llm_vme
