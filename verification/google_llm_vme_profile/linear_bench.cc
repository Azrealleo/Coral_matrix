// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Same ELF: official RVV, complete VME call, and reusable-weight VME call.
#include "linear_core.h"
#include "profile_core.h"
#include <cstdint>
#include <cstddef>
#include <initializer_list>
#ifdef LV_HOST
#include <cstdio>
#else
#include "vme_tile.h"
extern "C" {
void rvv_gemv_int8(const int8_t*,const int8_t*,int32_t*,size_t,size_t);
void rvv_matmul_int8(const int8_t*,const int8_t*,int32_t*,size_t,size_t,size_t);
}
#endif
using namespace llm_vme;
extern "C" {
volatile uint32_t lv_case=0xfffffffeu;
volatile uint32_t lv_status,lv_checked,lv_mismatches,lv_signature,lv_guard_ok,lv_m,lv_k,lv_n;
volatile uint32_t lv_rvv_calls,lv_complete_calls,lv_reuse_calls,lv_prepack_calls;
volatile uint32_t lv_empty_cycles,lv_prepack_cycles;
volatile uint32_t lv_rvv_cycles[4],lv_complete_cycles[4],lv_reuse_cycles[4];
uint32_t lv_complete_commands,lv_reuse_commands;
uint32_t lv_profile_commands;
volatile uint32_t lv_profile_calls,lv_profile_cycles[4];
volatile uint32_t lv_profile_segment_cycles[20],lv_profile_segment_counts[20];
alignas(16) int8_t lv_x[16*64],lv_w[64*64];
GuardedOutput lv_rvv_out,lv_complete_out,lv_reuse_out;
GuardedOutput lv_profile_out;
PackedWeights lv_complete_weights,lv_reuse_weights;
Workspace lv_workspace;
}
namespace {
constexpr int kShapes[][3]={{1,32,32},{16,32,32},{1,64,64},{16,64,64}};
uint32_t state;
uint32_t Random() {state^=state<<13;state^=state>>17;state^=state<<5;return state;}
uint32_t Cycle() {
#ifdef LV_HOST
  return 0;
#else
  uint32_t value;asm volatile("fence rw,rw\ncsrr %0,mcycle":"=r"(value)::"memory");return value;
#endif
}
uint32_t Hash(uint32_t h,int32_t value) {
  for(int i=0;i<4;++i)h=(h^((static_cast<uint32_t>(value)>>(8*i))&255u))*16777619u;
  return h;
}
__attribute__((noinline)) void Rvv(int m,int k,int n) {
#ifdef LV_HOST
  for(int r=0;r<m;++r)for(int c=0;c<n;++c) {
    int32_t value=0;for(int d=0;d<k;++d)value+=int(lv_x[r*k+d])*int(lv_w[d*n+c]);
    lv_rvv_out.data[r*n+c]=value;
  }
#else
  if(m==1)rvv_gemv_int8(lv_x,lv_w,lv_rvv_out.data,k,n);
  else rvv_matmul_int8(lv_x,lv_w,lv_rvv_out.data,m,k,n);
#endif
}
__attribute__((noinline)) bool Prepack(int k,int n) {return PrepareWeights(lv_w,k,n,lv_reuse_weights);}
__attribute__((noinline)) bool Complete(int m,int k,int n) {
#ifdef LV_HOST
  EmulatedTile backend(&lv_complete_commands);
#else
  person_vme::HardwareTile backend(&lv_complete_commands);
#endif
  return RunComplete(lv_x,lv_w,m,k,n,lv_complete_weights,lv_workspace,backend,lv_complete_out.data);
}
__attribute__((noinline)) bool Reuse(int m,int k,int n) {
#ifdef LV_HOST
  EmulatedTile backend(&lv_reuse_commands);
#else
  person_vme::HardwareTile backend(&lv_reuse_commands);
#endif
  return RunPrepared(lv_x,m,k,n,lv_reuse_weights,lv_workspace,backend,lv_reuse_out.data);
}
__attribute__((noinline)) bool Profile(int m,int k,int n,ProfileStats& stats) {
  return RunProfiled(lv_x,m,k,n,lv_reuse_weights,lv_workspace,stats,&lv_profile_commands,lv_profile_out.data);
}
int Run(unsigned index) {
  const int m=kShapes[index][0],k=kShapes[index][1],n=kShapes[index][2];
  lv_status=1;lv_m=m;lv_k=k;lv_n=n;
  lv_checked=lv_mismatches=lv_rvv_calls=lv_complete_calls=lv_reuse_calls=lv_prepack_calls=0;
  lv_complete_commands=lv_reuse_commands=0;lv_guard_ok=0;state=137+index;
  lv_profile_commands=lv_profile_calls=0;
  for(auto& value:lv_x)value=0x5a;
  for(auto& value:lv_w)value=0x5a;
  for(int i=0;i<m*k;++i)lv_x[i]=static_cast<int8_t>(int(Random()&255u)-128);
  for(int i=0;i<k*n;++i)lv_w[i]=static_cast<int8_t>(int(Random()%255u)-127);
  lv_x[0]=-128;lv_w[0]=-127;lv_x[m*k-1]=127;lv_w[k*n-1]=127;
  Reset(lv_reuse_weights);Reset(lv_complete_weights);Reset(lv_workspace);
  const uint32_t empty=Cycle();lv_empty_cycles=Cycle()-empty;
  // One REAL prepack per experiment, measured separately. Reuse first/steady
  // samples exclude it; the report MUST also charge it to first/amortized use.
  uint32_t begin=Cycle();const bool prepared=Prepack(k,n);lv_prepack_cycles=Cycle()-begin;
  ++lv_prepack_calls;if(!prepared){lv_status=11;return 1;}
  uint32_t signature=2166136261u;lv_status=2;
  for(unsigned sample=0;sample<4;++sample) {
    Reset(lv_rvv_out);Reset(lv_complete_out);Reset(lv_reuse_out);Reset(lv_profile_out);
    for(unsigned turn=0;turn<4;++turn) {
      ProfileStats stats{}; // Reset outside ALL measured call windows.
      const unsigned mode=(sample+turn)%4;bool ok=true;begin=Cycle();
      if(mode==0)Rvv(m,k,n);
      else if(mode==1)ok=Complete(m,k,n);
      else if(mode==2)ok=Reuse(m,k,n);
      else ok=Profile(m,k,n,stats);
      const uint32_t elapsed=Cycle()-begin;
      if(mode==0){lv_rvv_cycles[sample]=elapsed;++lv_rvv_calls;}
      else if(mode==1){lv_complete_cycles[sample]=elapsed;++lv_complete_calls;}
      else if(mode==2){lv_reuse_cycles[sample]=elapsed;++lv_reuse_calls;}
      else {
        lv_profile_cycles[sample]=elapsed;++lv_profile_calls;
        for(int phase=0;phase<kPhases;++phase) {
          lv_profile_segment_cycles[sample*kPhases+phase]=stats.cycles[phase];
          lv_profile_segment_counts[sample*kPhases+phase]=stats.counts[phase];
          if(stats.counts[phase]!=(phase==kInputPack?1u:unsigned((n+15)/16))) {
            lv_status=17;return 1;
          }
        }
      }
      if(!ok){lv_status=12;return 1;}
    }
    // Independent INT64 reference and all checks OUTSIDE measured windows.
    for(int r=0;r<m;++r)for(int c=0;c<n;++c) {
      int64_t expected=0;for(int d=0;d<k;++d)expected+=int(lv_x[r*k+d])*int(lv_w[d*n+c]);
      const int at=r*n+c;
      for(const auto* out:{&lv_rvv_out,&lv_complete_out,&lv_reuse_out,&lv_profile_out}) {
        if(out->data[at]!=expected)++lv_mismatches;
        ++lv_checked;signature=Hash(signature,out->data[at]);
      }
    }
    if(!OutputGuard(lv_rvv_out,m*n)||!OutputGuard(lv_complete_out,m*n)||!OutputGuard(lv_reuse_out,m*n)||
       !OutputGuard(lv_profile_out,m*n)||
       !PackedGuard(lv_complete_weights,k,n)||!PackedGuard(lv_reuse_weights,k,n)||!WorkGuard(lv_workspace,k)) {
      lv_status=13;return 1;
    }
  }
  lv_signature=signature;lv_guard_ok=1;
  const uint32_t expected_commands=4u*((n+15)/16)*((k+3)/4);
  if(lv_mismatches||lv_checked!=16u*m*n||lv_rvv_calls!=4||lv_complete_calls!=4||lv_reuse_calls!=4||lv_profile_calls!=4||
     lv_prepack_calls!=1||lv_complete_commands!=expected_commands||lv_reuse_commands!=expected_commands||lv_profile_commands!=expected_commands) {
    lv_status=14;return 1;
  }
#ifndef LV_HOST
  if(lv_prepack_cycles<=lv_empty_cycles){lv_status=15;return 1;}
  for(int i=0;i<4;++i)if(lv_rvv_cycles[i]<=lv_empty_cycles||lv_complete_cycles[i]<=lv_empty_cycles||
      lv_reuse_cycles[i]<=lv_empty_cycles||lv_profile_cycles[i]<=lv_empty_cycles){lv_status=16;return 1;}
#endif
  lv_status=3;return 0;
}
}  // namespace
int main() {
#ifdef LV_HOST
  for(unsigned i=0;i<4;++i) {
    if(Run(i)){std::printf("FAIL id=%u status=%u\n",i,unsigned(lv_status));return 1;}
    std::printf("[LV_HOST_REFERENCE] id=%u checked=%u signature=%u commands_each=%u VME_RVV=NOT_RUN\n",
        i,unsigned(lv_checked),unsigned(lv_signature),unsigned(lv_complete_commands));
  }
  return 0;
#else
  const unsigned selected=lv_case;
  if(selected>=4){lv_status=99;return 1;}
  // Official CRT uses mpause for main()==0, and ebreak (fault) on failure.
  // Do not issue ebreak here: successful arithmetic must halt without fault.
  return Run(selected);
#endif
}
