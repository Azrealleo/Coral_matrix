// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Same resident matrices, raw INT32 outputs. NOT an LLM inference benchmark.
#include <cstddef>
#include <cstdint>
#ifdef LLM_HOST
#include <cstdio>
#endif
extern "C" {
void rvv_gemv_int8(const int8_t*, const int8_t*, int32_t*, size_t, size_t);
void rvv_matmul_int8(const int8_t*, const int8_t*, int32_t*, size_t, size_t, size_t);
volatile uint32_t llm_case = 0xfffffffeu; // Host selection survives CRT BSS init.
volatile uint32_t llm_status, llm_checked, llm_mismatches, llm_signature;
volatile uint32_t llm_m, llm_k, llm_n, llm_rvv_calls, llm_guard_ok;
volatile uint32_t llm_scalar_cycles[4], llm_rvv_cycles[4], llm_empty_cycles;
alignas(16) int8_t llm_x[16*64], llm_w[64*64];
struct alignas(16) Guarded {
  uint32_t before[4];
  int32_t data[16*64];
  uint32_t after[4];
};
Guarded llm_scalar_out, llm_rvv_out;
}
namespace {
constexpr uint32_t kGuard = 0x55aa7711u;
constexpr int kShapes[][3]={{1,32,32},{16,32,32},{1,64,64},{16,64,64}};
uint32_t random_state;
uint32_t Random() {
  random_state^=random_state<<13;random_state^=random_state>>17;
  random_state^=random_state<<5;return random_state;
}
uint32_t Cycle() {
#ifdef LLM_HOST
  return 0;
#else
  uint32_t value;
  asm volatile("fence rw,rw\ncsrr %0,mcycle":"=r"(value)::"memory");
  return value;
#endif
}
__attribute__((noinline)) void Scalar(int m,int k,int n) {
  for(int r=0;r<m;++r)for(int c=0;c<n;++c) {
    int32_t sum=0;
    for(int d=0;d<k;++d)sum+=int32_t(llm_x[r*k+d])*llm_w[d*n+c];
    llm_scalar_out.data[r*n+c]=sum;
  }
}
void Reset(Guarded& g) {
  for(int i=0;i<4;++i)g.before[i]=g.after[i]=kGuard;
  for(int i=0;i<16*64;++i)g.data[i]=static_cast<int32_t>(kGuard);
}
bool Guard(const Guarded& g,int used) {
  for(int i=0;i<4;++i)if(g.before[i]!=kGuard || g.after[i]!=kGuard)return false;
  for(int i=used;i<16*64;++i)if(g.data[i]!=static_cast<int32_t>(kGuard))return false;
  return true;
}
uint32_t Hash(uint32_t hash,int32_t value) {
  const uint32_t bits=static_cast<uint32_t>(value);
  for(int b=0;b<4;++b)hash=(hash^((bits>>(8*b))&255u))*16777619u;
  return hash;
}
int Run(unsigned index) {
  llm_status=1;llm_checked=llm_mismatches=llm_rvv_calls=llm_guard_ok=0;
  const int m=kShapes[index][0],k=kShapes[index][1],n=kShapes[index][2];
  llm_m=m;llm_k=k;llm_n=n;random_state=137+index;
  for(int i=0;i<m*k;++i)llm_x[i]=static_cast<int8_t>(int(Random()&255u)-128);
  for(int i=0;i<k*n;++i)llm_w[i]=static_cast<int8_t>(int(Random()%255u)-127);
  llm_x[0]=-128;llm_w[0]=-127;llm_x[m*k-1]=127;llm_w[k*n-1]=127;
  const uint32_t empty=Cycle();llm_empty_cycles=Cycle()-empty;
  uint32_t signature=2166136261u;
  llm_status=2;
  for(unsigned sample=0;sample<4;++sample) {
    Reset(llm_scalar_out);Reset(llm_rvv_out);
    for(unsigned turn=0;turn<2;++turn) {
      const bool optimized=((turn+sample)%2)!=0;
#ifdef LLM_HOST
      if(optimized)continue; // Host only qualifies vectors/reference, never RVV.
#endif
      const uint32_t start=Cycle();
      if(!optimized)Scalar(m,k,n);
#ifndef LLM_HOST
      else if(m==1)rvv_gemv_int8(llm_x,llm_w,llm_rvv_out.data,k,n);
      else rvv_matmul_int8(llm_x,llm_w,llm_rvv_out.data,m,k,n);
#endif
      const uint32_t cycles=Cycle()-start;
      if(optimized) {llm_rvv_cycles[sample]=cycles;++llm_rvv_calls;}
      else llm_scalar_cycles[sample]=cycles;
    }
    // Checks and signatures are OUTSIDE both measured calls.
    for(int i=0;i<m*n;++i) {
      const int32_t expected=llm_scalar_out.data[i];
#ifndef LLM_HOST
      if(expected!=llm_rvv_out.data[i])++llm_mismatches;
#endif
      ++llm_checked;signature=Hash(signature,expected);
    }
    if(!Guard(llm_scalar_out,m*n) || !Guard(llm_rvv_out,m*n)) {
      llm_status=101;return 1;
    }
  }
  llm_signature=signature;llm_guard_ok=1;
  if(llm_mismatches || llm_checked!=4u*m*n) {llm_status=102;return 1;}
#ifndef LLM_HOST
  if(llm_rvv_calls!=4) {llm_status=103;return 1;}
  for(unsigned i=0;i<4;++i)if(!llm_scalar_cycles[i] || !llm_rvv_cycles[i]) {
    llm_status=104;return 1;
  }
#else
  std::printf("[LLM_LINEAR_HOST_REFERENCE] case=%u checked=%u signature=%u RVV=NOT_RUN\n",
      index,unsigned(llm_checked),signature);
#endif
  llm_status=3;return 0;
}
}
int main() {
#ifdef LLM_HOST
  for(unsigned i=0;i<4;++i)if(Run(i))return 1;
  return 0;
#else
  const unsigned index=llm_case;
  if(index>=4) {llm_status=105;return 1;}
  return Run(index);
#endif
}
