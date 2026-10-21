// Copyright 2026. SPDX-License-Identifier: Apache-2.0
#include "kernels.h"
#include <cmath>
#include <cstring>
#ifdef TX_HOST
#include <cstdio>
#endif
extern "C" {
volatile unsigned tx_case=0xfffffffeu;
volatile unsigned tx_status,tx_kind,tx_checked,tx_mismatches,tx_calls,tx_guard_ok;
volatile unsigned tx_first_bad,tx_empty,tx_scalar_cycles[4],tx_rvv_cycles[4];
alignas(16) float tx_x[kCapacity],tx_w[kCapacity],tx_v[kCapacity];
struct alignas(16) Guarded {unsigned before[4];float data[kCapacity];unsigned after[4];};
Guarded tx_scalar_out,tx_rvv_out;
}
namespace {
constexpr unsigned guard=0x55aa7711;
unsigned Cycle() {
#ifdef TX_HOST
  return 0;
#else
  unsigned result;asm volatile("fence rw,rw\ncsrr %0,mcycle":"=r"(result)::"memory");return result;
#endif
}
void Reset(Guarded& out,const Case& t) {
  for(int i=0;i<4;++i)out.before[i]=out.after[i]=guard;
  for(unsigned i=0;i<kCapacity;++i)std::memcpy(out.data+i,&guard,4);
  if(t.kind==KVAPPEND) {
    const int old=t.a*t.c,total=(t.a+t.b)*t.c;
    for(int i=0;i<old;++i) {out.data[i]=tx_x[i];out.data[total+i]=tx_x[old+i];}
  }
}
bool Guard(const Guarded& out,unsigned used) {
  for(int i=0;i<4;++i)if(out.before[i]!=guard || out.after[i]!=guard)return false;
  for(unsigned i=used;i<kCapacity;++i) {unsigned bits;std::memcpy(&bits,out.data+i,4);if(bits!=guard)return false;}
  return true;
}
bool Close(float actual,float expected) {
  return std::isfinite(actual) && std::fabs(actual-expected)<=kAtol+kRtol*std::fabs(expected);
}
int Run(unsigned index) {
  const Case& t=kCases[index];tx_status=1;tx_kind=t.kind;
  tx_checked=tx_mismatches=tx_calls=tx_guard_ok=0;tx_first_bad=0xffffffffu;
  if(t.nx>kCapacity || t.nw>kCapacity || t.nv>kCapacity || t.ny>kCapacity)return 1;
  for(unsigned i=0;i<t.nx;++i)tx_x[i]=t.x[i];
  for(unsigned i=0;i<t.nw;++i)tx_w[i]=t.w[i];
  for(unsigned i=0;i<t.nv;++i)tx_v[i]=t.v[i];
  const unsigned start=Cycle();tx_empty=Cycle()-start;tx_status=2;
  for(unsigned sample=0;sample<kSamples;++sample) {
    Reset(tx_scalar_out,t);Reset(tx_rvv_out,t);
    for(unsigned turn=0;turn<2;++turn) {
      const bool rvv=(turn+sample)%2;
      const unsigned before=Cycle();
      if(rvv)Vector(t,tx_x,tx_w,tx_v,tx_rvv_out.data);
      else Scalar(t,tx_x,tx_w,tx_v,tx_scalar_out.data);
      const unsigned elapsed=Cycle()-before;
      if(rvv) {tx_rvv_cycles[sample]=elapsed;++tx_calls;}else tx_scalar_cycles[sample]=elapsed;
    }
    // Both pathways compared to independent Python-generated gold AFTER timing.
    for(unsigned i=0;i<t.ny;++i) {
      if(!Close(tx_scalar_out.data[i],t.gold[i]) || !Close(tx_rvv_out.data[i],t.gold[i])) {
        if(!tx_mismatches)tx_first_bad=i;
        ++tx_mismatches;
      }
      ++tx_checked;
    }
    if(!Guard(tx_scalar_out,t.ny) || !Guard(tx_rvv_out,t.ny)) {tx_status=101;return 1;}
  }
  tx_guard_ok=1;
  if(tx_mismatches || tx_checked!=kSamples*t.ny || tx_calls!=kSamples) {tx_status=102;return 1;}
#ifndef TX_HOST
  for(unsigned i=0;i<kSamples;++i)if(!tx_scalar_cycles[i] || !tx_rvv_cycles[i]) {tx_status=103;return 1;}
#else
  std::printf("[TX_HOST_REFERENCE] id=%u name=%s checked=%u errors=%u RVV=NOT_RUN\n",
      index,t.name,unsigned(tx_checked),unsigned(tx_mismatches));
#endif
  tx_status=3;return 0;
}
}
int main() {
#ifdef TX_HOST
  for(unsigned i=0;i<kCaseCount;++i)if(Run(i))return 1;
  return 0;
#else
  const unsigned index=tx_case;if(index>=kCaseCount) {tx_status=104;return 1;}return Run(index);
#endif
}
