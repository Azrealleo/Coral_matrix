// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Row-major signed X[M,K] * W[K,N] -> Y[M,N], raw INT32, no quantization.
#pragma once
#include <cstdint>

namespace llm_vme {
constexpr int kMaxM=16,kMaxK=64,kMaxN=64,kCapacity=kMaxM*kMaxN;
constexpr uint32_t kGuard=0x55aa7711u;
struct alignas(16) PackedWeights {
  uint32_t before[4];
  int8_t data[kMaxK*kMaxN];
  int32_t initial[kMaxN];
  uint32_t after[4];
};
struct alignas(16) Workspace {
  uint32_t before[4];
  uint8_t input[kMaxK*16];
  int32_t accum[16*16];
  uint32_t after[4];
};
struct alignas(16) GuardedOutput {
  uint32_t before[4];int32_t data[kCapacity];uint32_t after[4];
};
static_assert(sizeof(PackedWeights)==4384 && sizeof(Workspace)==2080 && sizeof(GuardedOutput)==4128,"RV32 layout contract");
inline bool Shape(int m,int k,int n) {
  return m>=1 && m<=kMaxM && k>=1 && k<=kMaxK && n>=1 && n<=kMaxN;
}
inline void Reset(PackedWeights& w) {
  for(int i=0;i<4;++i)w.before[i]=w.after[i]=kGuard;
  for(auto& v:w.data)v=0x5a;
  for(auto& v:w.initial)v=static_cast<int32_t>(kGuard);
}
inline void Reset(Workspace& w) {
  for(int i=0;i<4;++i)w.before[i]=w.after[i]=kGuard;
  for(auto& v:w.input)v=0x5a;
  for(auto& v:w.accum)v=static_cast<int32_t>(kGuard);
}
inline void Reset(GuardedOutput& w) {
  for(int i=0;i<4;++i)w.before[i]=w.after[i]=kGuard;
  for(auto& v:w.data)v=static_cast<int32_t>(kGuard);
}
template<class T> bool Edges(const T& t) {
  for(int i=0;i<4;++i)if(t.before[i]!=kGuard || t.after[i]!=kGuard)return false;
  return true;
}
inline bool OutputGuard(const GuardedOutput& t,int used) {
  if(!Edges(t))return false;
  for(int i=used;i<kCapacity;++i)if(static_cast<uint32_t>(t.data[i])!=kGuard)return false;
  return true;
}
inline bool PackedGuard(const PackedWeights& t,int k,int n) {
  if(!Edges(t))return false;
  const int kp=(k+3)&~3,np=(n+15)&~15;
  for(int i=kp*np;i<kMaxK*kMaxN;++i)if(t.data[i]!=0x5a)return false;
  for(int i=np;i<kMaxN;++i)if(static_cast<uint32_t>(t.initial[i])!=kGuard)return false;
  return true;
}
inline bool WorkGuard(const Workspace& t,int k) {
  if(!Edges(t))return false;
  for(int i=((k+3)&~3)*16;i<kMaxK*16;++i)if(t.input[i]!=0x5a)return false;
  return true;
}

// HW multiplies signed A by UNSIGNED B. Orient its rows as output channels
// and columns as input tokens: A=W^T, B=X^T+128. Initialize each output with
// -128*sum_k(W[k,c]), so HW result is exactly sum_k(X[r,k]*W[k,c]).
// Limits here keep all intermediate accumulators within INT32.
inline bool PrepareWeights(const int8_t* w,int k,int n,PackedWeights& packed) {
  if(!w || !Shape(1,k,n))return false;
  const int kp=(k+3)&~3;
  for(int first=0;first<n;first+=16)for(int r=0;r<16;++r) {
    int sum=0;
    for(int d=0;d<kp;++d) {
      const int8_t value=first+r<n && d<k?w[d*n+first+r]:0;
      packed.data[first*kp+d*16+r]=value;sum+=value;
    }
    packed.initial[first+r]=-128*sum;
  }
  return true;
}
template<class Backend>
bool RunPrepared(const int8_t* x,int m,int k,int n,const PackedWeights& weights,
                 Workspace& work,Backend& backend,int32_t* y) {
  if(!x || !y || !Shape(m,k,n))return false;
  const int kp=(k+3)&~3;
  for(int d=0;d<kp;++d)for(int lane=0;lane<16;++lane)
    work.input[d*16+lane]=d<k && lane<m?static_cast<uint8_t>(int(x[lane*k+d])+128):0;
  for(int first=0;first<n;first+=16) {
    const int channels=n-first<16?n-first:16;
    backend.Run(weights.data+first*kp,work.input,weights.initial+first,channels,m,kp,work.accum);
    for(int r=0;r<m;++r)for(int c=0;c<channels;++c)y[r*n+first+c]=work.accum[c*16+r];
  }
  return true;
}
template<class Backend>
bool RunComplete(const int8_t* x,const int8_t* w,int m,int k,int n,PackedWeights& packed,
                 Workspace& work,Backend& backend,int32_t* y) {
  return Shape(m,k,n) && PrepareWeights(w,k,n,packed) && RunPrepared(x,m,k,n,packed,work,backend,y);
}

// Native arithmetic oracle for packing/scheduling only, NEVER hardware timing.
struct EmulatedTile {
  uint32_t* commands;
  explicit EmulatedTile(uint32_t* c):commands(c){}
  void Run(const int8_t* a,const uint8_t* b,const int32_t* bias,int m,int n,int k,int32_t* out) {
    for(int r=0;r<16;++r)for(int c=0;c<16;++c) {
      int64_t value=r<m && c<n?bias[r]:0;
      if(r<m && c<n)for(int d=0;d<k;++d)value+=int(a[d*16+r])*int(b[d*16+c]);
      out[r*16+c]=static_cast<int32_t>(value);
    }
    *commands+=k/4;
  }
};
}  // namespace llm_vme
