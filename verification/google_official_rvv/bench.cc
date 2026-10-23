// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Only benchmark/wrapping logic; official optimization sources are unmodified.
#include "kernels.h"
#include <cmath>
#include <cstring>
#ifdef TX_HOST
#include <cstdio>
#endif
extern const float* const kAlgorithm[];
extern "C" {
void RmsNormF(size_t,size_t,float,const float*,const float*,float*);
void rvv_residual_add_f32(const float*,const float*,float*,size_t);
void rvv_tanh_gelu_mul_f32(const float*,const float*,float*,size_t);
volatile unsigned lv_case=0xfffffffeu;
volatile unsigned lv_status,lv_checked,lv_mismatches,lv_quality_mismatches,lv_guard_ok,lv_empty_cycles;
volatile unsigned lv_scalar_calls,lv_project_calls,lv_official_calls,lv_probe_signature;
volatile unsigned lv_scalar_cycles[4],lv_project_cycles[4],lv_official_cycles[4];
alignas(16) float lv_x[1024],lv_w[1024];
struct alignas(16) Guarded {unsigned before[4];float data[1024];unsigned after[4];};
Guarded lv_scalar_out,lv_project_out,lv_official_out;
}
namespace {
constexpr unsigned guard=0x55aa7711u;
unsigned Cycle() {
#ifdef TX_HOST
  return 0;
#else
  unsigned value;asm volatile("fence rw,rw\ncsrr %0,mcycle":"=r"(value)::"memory");return value;
#endif
}
void Reset(Guarded& o) {
  for(int j=0;j<4;++j)o.before[j]=o.after[j]=guard;
  for(int j=0;j<1024;++j)std::memcpy(o.data+j,&guard,4);
}
bool Guard(const Guarded& o,unsigned n) {
  for(int j=0;j<4;++j)if(o.before[j]!=guard||o.after[j]!=guard)return false;
  for(unsigned j=n;j<1024;++j){unsigned u;std::memcpy(&u,o.data+j,4);if(u!=guard)return false;}
  return true;
}
bool Close(float a,float b){return std::isfinite(a)&&std::fabs(a-b)<=kAtol+kRtol*std::fabs(b);}
__attribute__((noinline)) void Official(const Case& t,float* y) {
  if(t.kind==RESIDUAL)rvv_residual_add_f32(lv_x,lv_w,y,t.a);
  else if(t.kind==RMS)RmsNormF(t.a,t.b,1e-5f,lv_x,lv_w,y);
  else if(t.kind==GEGLU)rvv_tanh_gelu_mul_f32(lv_x,lv_w,y,t.a);
}
int Run(unsigned index) {
  const Case& t=kCases[index];lv_status=1;
  lv_checked=lv_mismatches=lv_quality_mismatches=lv_guard_ok=0;
  lv_scalar_calls=lv_project_calls=lv_official_calls=0;
  for(int j=0;j<1024;++j){lv_x[j]=0;lv_w[j]=0;}
  if(t.nx>1024||t.nw>1024||t.ny>1024)return 1;
  for(unsigned j=0;j<t.nx;++j)lv_x[j]=t.x[j];
  for(unsigned j=0;j<t.nw;++j)lv_w[j]=t.w[j];
  unsigned begin=Cycle();lv_empty_cycles=Cycle()-begin;lv_status=2;
  for(unsigned sample=0;sample<4;++sample) {
    Reset(lv_scalar_out);Reset(lv_project_out);Reset(lv_official_out);
    for(unsigned turn=0;turn<3;++turn) {
      const unsigned path=(turn+sample)%3;const unsigned before=Cycle();
      if(path==0)Scalar(t,lv_x,lv_w,nullptr,lv_scalar_out.data);
      else if(path==1)Vector(t,lv_x,lv_w,nullptr,lv_project_out.data);
      else Official(t,lv_official_out.data);
      const unsigned elapsed=Cycle()-before;
      if(path==0){lv_scalar_cycles[sample]=elapsed;++lv_scalar_calls;}
      else if(path==1){lv_project_cycles[sample]=elapsed;++lv_project_calls;}
      else {lv_official_cycles[sample]=elapsed;++lv_official_calls;}
    }
    for(unsigned j=0;j<t.ny;++j) {
      lv_mismatches+=!Close(lv_scalar_out.data[j],t.gold[j]);
      lv_mismatches+=!Close(lv_project_out.data[j],t.gold[j]);
      lv_mismatches+=!Close(lv_official_out.data[j],kAlgorithm[index][j]);
      lv_quality_mismatches+=!Close(lv_official_out.data[j],t.gold[j]);lv_checked+=3;
    }
    if(!Guard(lv_scalar_out,t.ny)||!Guard(lv_project_out,t.ny)||!Guard(lv_official_out,t.ny))return 1;
  }
  lv_probe_signature=2166136261u;
  for(unsigned j=0;j<t.ny;++j){unsigned u;std::memcpy(&u,lv_official_out.data+j,4);
    for(unsigned b=0;b<4;++b)lv_probe_signature=(lv_probe_signature^((u>>(8*b))&255))*16777619u;}
  lv_guard_ok=1;
  if(lv_mismatches||lv_checked!=12*t.ny||lv_scalar_calls!=4||lv_project_calls!=4||lv_official_calls!=4)return 1;
  if(t.kind!=GEGLU&&lv_quality_mismatches)return 1;
  lv_status=3;
#ifdef TX_HOST
  std::printf("[OFFICIAL_HOST] id=%u checked=%u algorithms_ok=1 hardware=NOT_RUN\n",index,unsigned(lv_checked));
#endif
  return 0;
}
}
int main() {
#ifdef TX_HOST
  for(unsigned j=0;j<kCaseCount;++j)if(Run(j))return 1;
  return 0;
#else
  if(lv_case>=kCaseCount){lv_status=99;return 1;}return Run(lv_case);
#endif
}
