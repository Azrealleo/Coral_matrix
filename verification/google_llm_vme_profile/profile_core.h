#pragma once
#include "linear_core.h"
#include "profile_timing.h"
#ifdef LV_HOST
namespace llm_vme {
// Arithmetic and segment-count oracle only; no native hardware timing claim.
struct ProfileTile {
  uint32_t* commands;ProfileStats& stats;
  ProfileTile(uint32_t* count,ProfileStats& measured):commands(count),stats(measured){}
  void Run(const int8_t* a,const uint8_t* b,const int32_t* bias,int m,int n,int k,int32_t* out) {
    stats.Add(kAccumulatorInit,0);
    EmulatedTile backend(commands);backend.Run(a,b,bias,m,n,k,out);
    stats.Add(kLoadIssue,0);stats.Add(kReadback,0);
  }
};
}
#else
#include "profile_tile.h"
#endif
namespace llm_vme {
inline bool RunProfiled(const int8_t* x,int m,int k,int n,const PackedWeights& weights,
                       Workspace& work,ProfileStats& stats,uint32_t* commands,int32_t* y) {
  if(!x || !y || !Shape(m,k,n))return false;
  const int kp=(k+3)&~3;
  uint32_t begin=ProfileCycle();
  for(int d=0;d<kp;++d)for(int lane=0;lane<16;++lane)
    work.input[d*16+lane]=d<k && lane<m?static_cast<uint8_t>(int(x[lane*k+d])+128):0;
  stats.Add(kInputPack,ProfileCycle()-begin);
  ProfileTile backend(commands,stats);
  for(int first=0;first<n;first+=16) {
    const int channels=n-first<16?n-first:16;
    backend.Run(weights.data+first*kp,work.input,weights.initial+first,channels,m,kp,work.accum);
    begin=ProfileCycle();
    for(int r=0;r<m;++r)for(int c=0;c<channels;++c)y[r*n+first+c]=work.accum[c*16+r];
    stats.Add(kOutputLayout,ProfileCycle()-begin);
  }
  return true;
}
}  // namespace llm_vme
