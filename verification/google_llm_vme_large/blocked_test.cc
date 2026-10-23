// Native blocking/boundary math only. Does not execute any RVV/VME instructions.
#include "blocked_core.h"
#include <cstdio>
#include <cstring>
#include <initializer_list>
using namespace llm_vme;
namespace {
int8_t x[kLogicalM*kMaxK],w[kMaxK*kMaxN];
PackedWeights old_full,old_cache,new_full,new_cache,saved;
Workspace old_work,new_work;
GuardedOutput a,b,c,d;
}
int main() {
  unsigned cases=0;
  for(int m:{1,2,15,16,17,31,32})for(int k:{1,3,17,64,127,128,255,256})
  for(int n:{1,17,63,64,127,128})for(int pattern:{0,1,2}) {
    for(int i=0;i<m*k;++i)x[i]=static_cast<int8_t>(pattern==0?-128:pattern==1?127:(i*73+31)%256-128);
    for(int i=0;i<k*n;++i)w[i]=static_cast<int8_t>(pattern==0?127:pattern==1?-128:(i*29+17)%255-127);
    Reset(old_full);Reset(old_cache);Reset(new_full);Reset(new_cache);Reset(old_work);Reset(new_work);
    Reset(a);Reset(b);Reset(c);Reset(d);
    uint32_t old_commands=0,new_commands=0;OptimizationCounts counts{};EmulatedTile backend(&old_commands);
    if(!PrepareWeights(w,k,n,old_cache)||!PrepareOptimizedWeights(w,k,n,new_cache))return 1;
    saved=new_cache;
    if(!RunBlockedLegacyComplete(x,w,m,k,n,old_full,old_work,backend,a.data)||
       !RunBlockedLegacyPrepared(x,m,k,n,old_cache,old_work,backend,b.data)||
       !RunBlockedOptimizedComplete(x,w,m,k,n,new_full,new_work,&new_commands,counts,c.data)||
       !RunBlockedOptimizedPrepared(x,m,k,n,new_cache,new_work,&new_commands,counts,d.data))return 2;
    for(int r=0;r<m;++r)for(int col=0;col<n;++col) {
      int64_t gold=0;for(int depth=0;depth<k;++depth)gold+=int(x[r*k+depth])*int(w[depth*n+col]);
      const int at=r*n+col;
      if(a.data[at]!=gold||b.data[at]!=gold||c.data[at]!=gold||d.data[at]!=gold)return 3;
    }
    const unsigned tiles=((m+15)/16)*((n+15)/16),commands=2*tiles*((k+3)/4);
    if(old_commands!=commands||new_commands!=commands||counts.fast_tiles!=2*tiles||counts.fallback_tiles)return 4;
    if(std::memcmp(&old_cache,&new_cache,sizeof(saved))||std::memcmp(&saved,&new_cache,sizeof(saved))||
       std::memcmp(&old_full,&new_full,sizeof(saved)))return 5;
    if(!OutputGuard(a,m*n)||!OutputGuard(b,m*n)||!OutputGuard(c,m*n)||!OutputGuard(d,m*n)||
       !PackedGuard(old_full,k,n)||!PackedGuard(old_cache,k,n)||!PackedGuard(new_full,k,n)||
       !PackedGuard(new_cache,k,n)||!WorkGuard(old_work,k)||!WorkGuard(new_work,k))return 6;
    for(int i=0;i<256;++i)if(static_cast<uint32_t>(new_work.accum[i])!=kGuard)return 7;
    ++cases;
  }
  uint32_t commands=0;OptimizationCounts counts{};EmulatedTile backend(&commands);
  for(auto shape:{0,33})if(RunBlockedOptimizedPrepared(x,shape,64,64,new_cache,new_work,&commands,counts,c.data))return 8;
  if(RunBlockedOptimizedComplete(nullptr,w,32,64,64,new_full,new_work,&commands,counts,c.data)||
     RunBlockedOptimizedComplete(x,nullptr,32,64,64,new_full,new_work,&commands,counts,c.data)||
     RunBlockedOptimizedComplete(x,w,32,257,64,new_full,new_work,&commands,counts,c.data)||
     RunBlockedOptimizedComplete(x,w,32,64,129,new_full,new_work,&commands,counts,c.data)||
     RunBlockedLegacyComplete(x,w,33,64,64,old_full,old_work,backend,a.data)||commands||counts.fast_tiles)return 9;
  std::printf("[LV_LARGE_BLOCK_HOST_PASS] cases=%u hardware=NOT_RUN\n",cases);
  return cases==1008?0:10;
}
