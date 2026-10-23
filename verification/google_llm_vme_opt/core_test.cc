// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Native packing/scheduling arithmetic only, no RVV/VME hardware execution.
#include "linear_core.h"
#include "optimized_core.h"
#include <cstdio>
#include <cstring>
using namespace llm_vme;
namespace {
int8_t x[kMaxM*kMaxK],w[kMaxK*kMaxN];
PackedWeights packed,cached,saved,optimized;Workspace work,opt_work;
GuardedOutput complete,reuse,opt_complete,opt_reuse;
}
int main() {
#ifdef LV_EXHAUSTIVE
  int ms[16],ks[64],ns[64];
  for(int i=0;i<16;++i)ms[i]=i+1;
  for(int i=0;i<64;++i)ks[i]=ns[i]=i+1;
  const int patterns[]={2};
#else
  const int ms[]={1,2,7,15,16},ks[]={1,3,4,17,32,63,64},ns[]={1,15,16,17,32,63,64};
  const int patterns[]={0,1,2,3};
#endif
  unsigned cases=0;
  for(int m:ms)for(int k:ks)for(int n:ns)for(int pattern:patterns) {
    for(int i=0;i<m*k;++i)x[i]=static_cast<int8_t>(pattern==0?-128:pattern==1?127:(i*73+31)%256-128);
    for(int i=0;i<k*n;++i)w[i]=static_cast<int8_t>(pattern==0?(i%2?-127:127):pattern==1?-127:pattern==3?-128:(i*29+17)%255-127);
    Reset(packed);Reset(cached);Reset(work);Reset(complete);Reset(reuse);
    uint32_t full_commands=0,reuse_commands=0;EmulatedTile full(&full_commands),warm(&reuse_commands);
    if(!PrepareWeights(w,k,n,cached))return 1;
    saved=cached;
    if(!RunComplete(x,w,m,k,n,packed,work,full,complete.data)||!RunPrepared(x,m,k,n,cached,work,warm,reuse.data))return 2;
    Reset(optimized);Reset(opt_work);Reset(opt_complete);Reset(opt_reuse);
    uint32_t opt_commands=0;OptimizationCounts opt_counts{};
    if(!RunOptimizedComplete(x,w,m,k,n,optimized,opt_work,&opt_commands,opt_counts,opt_complete.data)||
       !RunOptimizedPrepared(x,m,k,n,optimized,opt_work,&opt_commands,opt_counts,opt_reuse.data))return 9;
    if(std::memcmp(&optimized,&cached,sizeof(cached)))return 10;
    const unsigned tiles=(n+15)/16;
    if(opt_commands!=2u*tiles*((k+3)/4)||opt_counts.fast_tiles!=(m==1||m==16?2u*tiles:0u)||
       opt_counts.fallback_tiles!=(m==1||m==16?0u:2u*tiles))return 11;
    if(!OutputGuard(opt_complete,m*n)||!OutputGuard(opt_reuse,m*n)||!PackedGuard(optimized,k,n)||!WorkGuard(opt_work,k))return 12;
    for(int r=0;r<m;++r)for(int c=0;c<n;++c) {
      int64_t gold=0;for(int d=0;d<k;++d)gold+=int(x[r*k+d])*int(w[d*n+c]);
      if(complete.data[r*n+c]!=gold || reuse.data[r*n+c]!=gold || opt_complete.data[r*n+c]!=gold || opt_reuse.data[r*n+c]!=gold) {
        std::printf("FAIL shape=%d,%d,%d pattern=%d\n",m,k,n,pattern);return 3;
      }
    }
    if(!OutputGuard(complete,m*n)||!OutputGuard(reuse,m*n)||!PackedGuard(packed,k,n)||!PackedGuard(cached,k,n)||!WorkGuard(work,k))return 4;
    if(std::memcmp(&cached,&saved,sizeof(cached)) || std::memcmp(&packed,&cached,sizeof(cached)))return 5;
    if(full_commands!=unsigned(((n+15)/16)*((k+3)/4)) || reuse_commands!=full_commands)return 6;
    ++cases;
  }
  uint32_t count=0;EmulatedTile backend(&count);
  if(RunComplete(x,w,0,4,4,packed,work,backend,complete.data)||RunComplete(x,w,17,4,4,packed,work,backend,complete.data)||
     RunComplete(x,w,1,65,4,packed,work,backend,complete.data)||RunComplete(x,w,1,4,65,packed,work,backend,complete.data)||
     RunComplete(nullptr,w,1,4,4,packed,work,backend,complete.data)||PrepareWeights(nullptr,4,4,packed)||count)return 7;
  OptimizationCounts invalid{};
  if(RunOptimizedPrepared(nullptr,1,4,4,cached,opt_work,&count,invalid,opt_reuse.data)||
     RunOptimizedPrepared(x,1,4,4,cached,opt_work,nullptr,invalid,opt_reuse.data)||
     RunOptimizedComplete(x,nullptr,1,4,4,optimized,opt_work,&count,invalid,opt_complete.data)||
     PackOptimizedInput(x,17,4,opt_work)||PrepareOptimizedWeights(w,65,4,optimized)||count)return 13;
#ifdef LV_EXHAUSTIVE
  std::printf("[LV_OPT_EXHAUSTIVE_HOST_PASS] cases=%u hardware=NOT_RUN\n",cases);
  return cases==65536?0:8;
#else
  std::printf("[LV_OPT_PACK_HOST_PASS] cases=%u hardware=NOT_RUN\n",cases);
  return cases==980?0:8;
#endif
}
