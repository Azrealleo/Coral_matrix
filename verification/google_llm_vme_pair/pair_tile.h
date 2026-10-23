// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Included after the qualified packing / single-tile helper declarations.
#pragma once
#include "pair_loop.h"
namespace llm_vme {
#ifndef LV_HOST
inline __attribute__((noinline)) void PairTileToRowMajor(
    const int8_t* a0,const int8_t* a1,const uint8_t* b,const int32_t* bias,
    int tokens,int kp,int32_t* y,int output_columns,uint32_t* commands) {
  const uint32_t move_type=(16u<<10)|(1u<<5)|1u;
  OptSet(move_type,0xd2,16,16);
  for(int tile=0;tile<2;++tile)for(int r=0;r<16;++r) {
    const int32_t initial=bias[tile*16+r];
    // TSS tile[30:27], row[23:0]; INT32 group starts must be 0,4,8,12.
    register uint32_t index asm("a0")=(tile?0x20000000u:0u)|static_cast<uint32_t>(r);
    if(tokens==1) {
      asm volatile("vmv.v.i v4,0\nvmv.s.x v4,%0\n.word 0x5e456057"
          : : "r"(initial),"r"(index) : "v4","v5","v6","v7","memory");
    } else {
      asm volatile("vmv.v.x v4,%0\n.word 0x5e456057"
          : : "r"(initial),"r"(index) : "v4","v5","v6","v7","memory");
    }
  }
  if(tokens==16)PairKLoop<false>(a0,a1,b,tokens,kp,commands);
  else PairKLoop<true>(a0,a1,b,tokens,kp,commands);
  OptSet(move_type,0xd2,16,16);
  for(int tile=0;tile<2;++tile)for(int r=0;r<16;++r) {
    register uint32_t index asm("a0")=(tile?0x20000000u:0u)|static_cast<uint32_t>(r);
    int32_t* destination=y+tile*16+r;
    const uint32_t stride=static_cast<uint32_t>(output_columns)*4u,full_width=16;
    if(tokens==16) {
      asm volatile(".word 0x43f56257\nvsse32.v v4,(%0),%1"
          : : "r"(destination),"r"(stride),"r"(index)
          : "v4","v5","v6","v7","memory");
    } else {
      asm volatile(".word 0x43f56257\n.insn r 0x57,7,0x42,t0,%2,x0\n"
                   "vsse32.v v4,(%0),%1\n.insn r 0x57,7,0x42,t0,%3,x0"
          : : "r"(destination),"r"(stride),"r"(tokens),"r"(full_width),"r"(index)
          : "v4","v5","v6","v7","t0","vl","memory");
    }
  }
}
#endif

inline __attribute__((noinline)) bool RunPairPrepared(
    const int8_t* x,int m,int k,int n,const PackedWeights& weights,Workspace& work,
    uint32_t* commands,OptimizationCounts& counts,int32_t* y) {
  if(!y||!commands||!Shape(m,k,n)||!PackOptimizedInput(x,m,k,work))return false;
  const int kp=(k+3)&~3;
  int first=0;
  for(;first+32<=n;first+=32) {
#ifdef LV_HOST
    // Independent native model of TWO accumulator groups, not instruction
    // execution. Distinct weights/biases must stay associated with each group.
    int64_t accum[2][16][16]{};
    for(int t=0;t<2;++t)for(int c=0;c<16;++c)for(int r=0;r<m;++r) {
      int64_t value=weights.initial[first+t*16+c];
      for(int d=0;d<kp;++d)value+=int(weights.data[(first+t*16)*kp+d*16+c])*int(work.input[d*16+r]);
      accum[t][c][r]=value;
    }
    for(int t=0;t<2;++t)for(int r=0;r<m;++r)for(int c=0;c<16;++c)
      y[r*n+first+t*16+c]=static_cast<int32_t>(accum[t][c][r]);
    *commands+=2u*static_cast<uint32_t>(kp/4);
#else
    PairTileToRowMajor(weights.data+first*kp,weights.data+(first+16)*kp,
        work.input,weights.initial+first,m,kp,y+first,n,commands);
#endif
    counts.fast_tiles+=2;++counts.pair_groups;
  }
  // At most two leftovers: do not compute/store an incomplete second tile as
  // though it were a full pair. Use the qualified configure-once single path.
  for(;first<n;first+=16) {
    const int channels=n-first<16?n-first:16;
#ifdef LV_HOST
    for(int c=0;c<channels;++c)for(int r=0;r<m;++r) {
      int64_t value=weights.initial[first+c];
      for(int d=0;d<kp;++d)value+=int(weights.data[first*kp+d*16+c])*int(work.input[d*16+r]);
      y[r*n+first+c]=static_cast<int32_t>(value);
    }
    *commands+=static_cast<uint32_t>(kp/4);
#else
    FastTileToRowMajor(weights.data+first*kp,work.input,weights.initial+first,
        channels,m,kp,y+first,n,commands);
#endif
    ++counts.fast_tiles;++counts.single_groups;
  }
  return true;
}
} // namespace llm_vme
