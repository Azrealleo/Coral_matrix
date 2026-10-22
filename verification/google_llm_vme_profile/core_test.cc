// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Native packing/scheduling arithmetic only, no RVV/VME hardware execution.
#include "linear_core.h"
#include "profile_core.h"
#include <cstdio>
#include <cstring>
using namespace llm_vme;
namespace {
int8_t x[kMaxM*kMaxK],w[kMaxK*kMaxN];
PackedWeights packed,cached,saved;Workspace work;
GuardedOutput complete,reuse,profile;
}
int main() {
  const int ms[]={1,2,7,15,16},ks[]={1,3,4,17,32,63,64},ns[]={1,15,16,17,32,63,64};
  unsigned cases=0;
  for(int m:ms)for(int k:ks)for(int n:ns)for(int pattern=0;pattern<3;++pattern) {
    for(int i=0;i<m*k;++i)x[i]=static_cast<int8_t>(pattern==0?-128:pattern==1?127:(i*73+31)%256-128);
    for(int i=0;i<k*n;++i)w[i]=static_cast<int8_t>(pattern==0?(i%2?-127:127):pattern==1?-127:(i*29+17)%255-127);
    Reset(packed);Reset(cached);Reset(work);Reset(complete);Reset(reuse);Reset(profile);
    uint32_t full_commands=0,reuse_commands=0;EmulatedTile full(&full_commands),warm(&reuse_commands);
    if(!PrepareWeights(w,k,n,cached))return 1;
    saved=cached;
    if(!RunComplete(x,w,m,k,n,packed,work,full,complete.data)||!RunPrepared(x,m,k,n,cached,work,warm,reuse.data))return 2;
    uint32_t profile_commands=0;ProfileStats stats{};
    if(!RunProfiled(x,m,k,n,cached,work,stats,&profile_commands,profile.data))return 9;
    for(int phase=0;phase<kPhases;++phase)
      if(stats.counts[phase]!=(phase==kInputPack?1u:unsigned((n+15)/16)))return 10;
    for(int r=0;r<m;++r)for(int c=0;c<n;++c) {
      int64_t gold=0;for(int d=0;d<k;++d)gold+=int(x[r*k+d])*int(w[d*n+c]);
      if(complete.data[r*n+c]!=gold || reuse.data[r*n+c]!=gold || profile.data[r*n+c]!=gold) {
        std::printf("FAIL shape=%d,%d,%d pattern=%d\n",m,k,n,pattern);return 3;
      }
    }
    if(!OutputGuard(complete,m*n)||!OutputGuard(reuse,m*n)||!OutputGuard(profile,m*n)||!PackedGuard(packed,k,n)||!PackedGuard(cached,k,n)||!WorkGuard(work,k))return 4;
    if(std::memcmp(&cached,&saved,sizeof(cached)) || std::memcmp(&packed,&cached,sizeof(cached)))return 5;
    if(full_commands!=unsigned(((n+15)/16)*((k+3)/4)) || reuse_commands!=full_commands || profile_commands!=full_commands)return 6;
    ++cases;
  }
  uint32_t count=0;EmulatedTile backend(&count);
  if(RunComplete(x,w,0,4,4,packed,work,backend,complete.data)||RunComplete(x,w,17,4,4,packed,work,backend,complete.data)||
     RunComplete(x,w,1,65,4,packed,work,backend,complete.data)||RunComplete(x,w,1,4,65,packed,work,backend,complete.data)||
     RunComplete(nullptr,w,1,4,4,packed,work,backend,complete.data)||PrepareWeights(nullptr,4,4,packed)||count)return 7;
  std::printf("[LV_PACK_HOST_PASS] cases=%u hardware=NOT_RUN\n",cases);
  return cases==735?0:8;
}
