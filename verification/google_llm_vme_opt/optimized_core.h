// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Candidate only: new instructions require the separate RTL probe before use.
#pragma once
#include "linear_core.h"
#ifndef LV_HOST
#include "vme_tile.h"
#endif
namespace llm_vme {
struct OptimizationCounts {uint32_t fast_tiles=0,fallback_tiles=0;};

#ifndef LV_HOST
inline __attribute__((always_inline)) void Zero16(uint8_t* destination) {
  asm volatile("vsetivli zero,16,e8,m1,ta,ma\nvmv.v.i v24,0\nvse8.v v24,(%0)"
    : : "r"(destination) : "v24","vl","vtype","memory");
}
inline __attribute__((always_inline)) void ZeroBias16(int32_t* destination) {
  asm volatile("vsetivli zero,16,e32,m4,ta,ma\nvmv.v.i v20,0\nvse32.v v20,(%0)"
    : : "r"(destination) : "v20","v21","v22","v23","vl","vtype","memory");
}
#endif

// W is row-major K*N. Each row contributes 16 adjacent channels; accumulate
// signed per-channel sums in INT16 (K<=64 => [-8192,8128]), widen before <<7.
inline __attribute__((noinline)) bool PrepareOptimizedWeights(const int8_t* w,int k,int n,PackedWeights& packed) {
  if(!w || !Shape(1,k,n))return false;
  const int kp=(k+3)&~3;
  for(int first=0;first<n;first+=16) {
    const int channels=n-first<16?n-first:16;
#ifdef LV_HOST
    int sums[16]{};
    for(int d=0;d<kp;++d)for(int r=0;r<16;++r) {
      const int8_t value=d<k && r<channels?w[d*n+first+r]:0;
      packed.data[first*kp+d*16+r]=value;sums[r]+=value;
    }
    for(int r=0;r<16;++r)packed.initial[first+r]=-128*sums[r];
#else
    // Clear only real padding. Full K/N tiles pay no separate zeroing pass.
    if(channels<16) {
      for(int d=0;d<kp;++d)Zero16(reinterpret_cast<uint8_t*>(packed.data+first*kp+d*16));
      ZeroBias16(packed.initial+first);
    } else for(int d=k;d<kp;++d)Zero16(reinterpret_cast<uint8_t*>(packed.data+first*kp+d*16));
    asm volatile("vsetivli zero,16,e16,m2,ta,ma\nvmv.v.i v26,0"
      : : : "v26","v27","vl","vtype","memory");
    for(int d=0;d<k;++d) {
      const int8_t* src=w+d*n+first;int8_t* dst=packed.data+first*kp+d*16;
      asm volatile("vsetvli zero,%2,e8,m1,ta,ma\nvle8.v v24,(%0)\nvse8.v v24,(%1)\n"
                   "vwadd.vx v28,v24,zero\nvsetvli zero,%2,e16,m2,ta,ma\nvadd.vv v26,v26,v28"
        : : "r"(src),"r"(dst),"r"(channels)
        : "v24","v26","v27","v28","v29","vl","vtype","memory");
    }
    asm volatile("vsetvli zero,%1,e16,m2,ta,ma\nvwadd.vx v20,v26,zero\n"
                 "vsetvli zero,%1,e32,m4,ta,ma\nvsll.vi v20,v20,7\nvrsub.vx v20,v20,zero\nvse32.v v20,(%0)"
      : : "r"(packed.initial+first),"r"(channels)
      : "v20","v21","v22","v23","vl","vtype","memory");
#endif
  }
  return true;
}

// Transpose tokens into the physical columns using strided vector loads.
// XOR 0x80 is bit-exact signed-byte +128 modulo 256. Do NOT add after widening.
inline __attribute__((noinline)) bool PackOptimizedInput(const int8_t* x,int m,int k,Workspace& work) {
  if(!x || !Shape(m,k,1))return false;
  const int kp=(k+3)&~3;
#ifdef LV_HOST
  for(int d=0;d<kp;++d)for(int lane=0;lane<16;++lane)
    work.input[d*16+lane]=d<k && lane<m?static_cast<uint8_t>(int(x[lane*k+d])+128):0;
#else
  if(m<16)for(int d=0;d<kp;++d)Zero16(work.input+d*16);
  else for(int d=k;d<kp;++d)Zero16(work.input+d*16);
  const uint32_t flip=128;
  for(int d=0;d<k;++d) {
    asm volatile("vsetvli zero,%3,e8,m1,ta,ma\nvlse8.v v24,(%0),%2\n"
                 "vxor.vx v24,v24,%4\nvse8.v v24,(%1)"
      : : "r"(x+d),"r"(work.input+d*16),"r"(k),"r"(m),"r"(flip)
      : "v24","vl","vtype","memory");
  }
#endif
  return true;
}

#ifndef LV_HOST
inline __attribute__((always_inline)) void OptSet(uint32_t mt,uint32_t vt,uint32_t m,uint32_t n) {
  register uint32_t type asm("a0")=mt;register uint32_t vtype asm("a1")=vt;
  asm volatile(".insn r 0x57,7,0x41,x0,a0,a1" : : "r"(type),"r"(vtype) : "vl","vtype","memory");
  register uint32_t rows asm("a0")=m;
  asm volatile(".insn r 0x57,7,0x42,t0,a0,x1" : : "r"(rows) : "t0","memory");
  register uint32_t cols asm("a0")=n;
  asm volatile(".insn r 0x57,7,0x42,t0,a0,x0" : : "r"(cols) : "t0","vl","memory");
}

inline __attribute__((noinline)) void FastTileToRowMajor(const int8_t* a,const uint8_t* b,const int32_t* bias,
    int channels,int tokens,int kp,int32_t* y,int output_columns,uint32_t* commands) {
  const uint32_t move_type=(16u<<10)|(1u<<5)|1u;
  OptSet(move_type,0xd2,16,16);
  for(int r=0;r<16;++r) {
    const int32_t initial=r<channels?bias[r]:0;
    register uint32_t index asm("a0")=r;
    if(tokens==1) {
      asm volatile("vmv.v.i v4,0\nvmv.s.x v4,%0\n.word 0x5e456057"
        : : "r"(initial),"r"(index) : "v4","v5","v6","v7","memory");
    } else {
      asm volatile("vmv.v.x v4,%0\n.word 0x5e456057"
        : : "r"(initial),"r"(index) : "v4","v5","v6","v7","memory");
    }
  }
  for(int d=0;d<kp;d+=4) {
    OptSet((16u<<10)|(4u<<5)|3u,0xc0,channels,16);
    const int8_t* pa=a+d*16;const uint8_t* pb=b+d*16;
    asm volatile("vle8.v v8,(%0)\nvle8.v v10,(%1)\nvle8.v v12,(%2)\nvle8.v v14,(%3)"
      : : "r"(pa),"r"(pa+16),"r"(pa+32),"r"(pa+48)
      : "v8","v10","v12","v14","memory");
    asm volatile("vle8.v v16,(%0)\nvle8.v v18,(%1)\nvle8.v v20,(%2)\nvle8.v v22,(%3)"
      : : "r"(pb),"r"(pb+16),"r"(pb+32),"r"(pb+48)
      : "v16","v18","v20","v22","memory");
    register uint32_t width asm("a0")=tokens;
    asm volatile(".insn r 0x57,7,0x42,t0,a0,x0\n.word 0xf28800f7"
      : : "r"(width) : "t0","vl","memory");
    ++*commands;
  }
  OptSet(move_type,0xd2,16,16);
  for(int r=0;r<channels;++r) {
    register uint32_t index asm("a0")=r;
    const uint32_t stride=uint32_t(output_columns)*4;
    // Read full row, narrow VL for valid stores, restore VL16 for NEXT read.
    // CRITICAL: ordinary vsetvli/vsetivli clears mtype in this Zvt frontend.
    // Use msettn for BOTH transitions, preserving SEW32/LMUL4 and mtype.
    const uint32_t full_width=16;
    if(tokens==16) {
      asm volatile(".word 0x43f56257\nvsse32.v v4,(%0),%1"
        : : "r"(y+r),"r"(stride),"r"(index) : "v4","v5","v6","v7","memory");
    } else {
      asm volatile(".word 0x43f56257\n.insn r 0x57,7,0x42,t0,%2,x0\n"
                   "vsse32.v v4,(%0),%1\n.insn r 0x57,7,0x42,t0,%3,x0"
        : : "r"(y+r),"r"(stride),"r"(tokens),"r"(full_width),"r"(index)
        : "v4","v5","v6","v7","t0","vl","memory");
    }
  }
}
#endif

inline __attribute__((noinline)) bool RunOptimizedPrepared(const int8_t* x,int m,int k,int n,const PackedWeights& weights,
    Workspace& work,uint32_t* commands,OptimizationCounts& counts,int32_t* y) {
  if(!y || !commands || !Shape(m,k,n) || !PackOptimizedInput(x,m,k,work))return false;
  const int kp=(k+3)&~3;
  for(int first=0;first<n;first+=16) {
    const int channels=n-first<16?n-first:16;
    if(m==1 || m==16) {
#ifdef LV_HOST
      // Independent native model of direct row-major stores, not RVV timing.
      for(int c=0;c<channels;++c)for(int r=0;r<m;++r) {
        int64_t value=weights.initial[first+c];
        for(int d=0;d<kp;++d)value+=int(weights.data[first*kp+d*16+c])*int(work.input[d*16+r]);
        y[r*n+first+c]=static_cast<int32_t>(value);
      }
      *commands+=kp/4;
#else
      FastTileToRowMajor(weights.data+first*kp,work.input,weights.initial+first,channels,m,kp,y+first,n,commands);
#endif
      ++counts.fast_tiles;
    } else {
#ifdef LV_HOST
      EmulatedTile backend(commands);
#else
      person_vme::HardwareTile backend(commands);
#endif
      backend.Run(weights.data+first*kp,work.input,weights.initial+first,channels,m,kp,work.accum);
      for(int r=0;r<m;++r)for(int c=0;c<channels;++c)y[r*n+first+c]=work.accum[c*16+r];
      ++counts.fallback_tiles;
    }
  }
  return true;
}
inline __attribute__((noinline)) bool RunOptimizedComplete(const int8_t* x,const int8_t* w,int m,int k,int n,
    PackedWeights& weights,Workspace& work,uint32_t* commands,OptimizationCounts& counts,int32_t* y) {
  return Shape(m,k,n) && PrepareOptimizedWeights(w,k,n,weights) &&
      RunOptimizedPrepared(x,m,k,n,weights,work,commands,counts,y);
}
}  // namespace llm_vme
