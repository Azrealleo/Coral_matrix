// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Logical M blocking only. Inner arithmetic/encodings remain the pinned path.
#pragma once
#include "optimized_core.h"
namespace llm_vme {
constexpr int kLogicalM=32;
inline bool LogicalShape(int m,int k,int n) {return m>=1 && m<=kLogicalM && Shape(1,k,n);}
template<class Backend>
inline __attribute__((noinline)) bool RunBlockedLegacyPrepared(const int8_t* x,int m,int k,int n,
    const PackedWeights& weights,Workspace& work,Backend& backend,int32_t* y) {
  if(!x || !y || !LogicalShape(m,k,n))return false;
  for(int first=0;first<m;first+=16) {
    const int tokens=m-first<16?m-first:16;
    if(!RunPrepared(x+first*k,tokens,k,n,weights,work,backend,y+first*n))return false;
  }
  return true;
}
template<class Backend>
inline __attribute__((noinline)) bool RunBlockedLegacyComplete(const int8_t* x,const int8_t* w,int m,int k,int n,
    PackedWeights& weights,Workspace& work,Backend& backend,int32_t* y) {
  return x && y && LogicalShape(m,k,n) && PrepareWeights(w,k,n,weights) &&
    RunBlockedLegacyPrepared(x,m,k,n,weights,work,backend,y);
}
inline __attribute__((noinline)) bool RunBlockedOptimizedPrepared(const int8_t* x,int m,int k,int n,
    const PackedWeights& weights,Workspace& work,uint32_t* commands,OptimizationCounts& counts,int32_t* y) {
  if(!x || !y || !commands || !LogicalShape(m,k,n))return false;
  for(int first=0;first<m;first+=16) {
    const int tokens=m-first<16?m-first:16;
    if(!RunOptimizedPrepared(x+first*k,tokens,k,n,weights,work,commands,counts,y+first*n))return false;
  }
  return true;
}
inline __attribute__((noinline)) bool RunBlockedOptimizedComplete(const int8_t* x,const int8_t* w,int m,int k,int n,
    PackedWeights& weights,Workspace& work,uint32_t* commands,OptimizationCounts& counts,int32_t* y) {
  // Pack once for the WHOLE logical call, not once for each M tile.
  return x && y && commands && LogicalShape(m,k,n) && PrepareOptimizedWeights(w,k,n,weights) &&
    RunBlockedOptimizedPrepared(x,m,k,n,weights,work,commands,counts,y);
}
}  // namespace llm_vme
