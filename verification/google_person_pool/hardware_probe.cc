// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Short RVV AveragePool arithmetic probe, not pretrained-model inference.
#include "pool_core.h"
#ifdef PD_POOL_PROBE_EMULATE
#include <cstdio>
#else
#include "pool_rvv.h"
#endif
extern "C" {
volatile uint32_t pd_probe_status, pd_probe_cases, pd_probe_checked, pd_probe_mismatches;
volatile uint32_t pd_probe_first_expected, pd_probe_first_actual, pd_probe_first_case;
volatile uint32_t pd_probe_signature;
uint32_t pd_probe_commands; // Vector-loop blocks, NOT retired instruction count.
}
namespace {
int8_t input[3*3*256], output[3*3*33+2];
uint32_t seed=137;
uint32_t Random() {seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;}
int8_t Expected(const person_pool::Geometry& g,int b,int oy,int ox,int c) {
  int sum=0,count=0;
  for(int fy=0;fy<g.filter_height;++fy) for(int fx=0;fx<g.filter_width;++fx) {
    const int y=oy*g.stride_height-g.pad_height+fy;
    const int x=ox*g.stride_width-g.pad_width+fx;
    if(y>=0 && y<g.height && x>=0 && x<g.width) {
      sum+=input[((b*g.height+y)*g.width+x)*g.channels+c];++count;
    }
  }
  const int mean=(sum>0 ? sum+count/2 : sum-count/2)/count;
  return static_cast<int8_t>(mean<g.activation_min ? g.activation_min :
                            mean>g.activation_max ? g.activation_max : mean);
}
}
int main() {
  pd_probe_status=1;
  using person_pool::Geometry;
  // First: actual model shape. Remaining: tails, padding, signed ties/clamps.
  const Geometry shapes[]={
    {1,3,3,256,1,1,3,3,2,2,0,0,-128,127},
    {1,3,3,17,3,3,3,3,1,1,1,1,-128,127},
    {1,3,3,33,2,2,2,2,2,2,0,0,-128,127},
    {2,2,2,15,1,1,2,2,1,1,0,0,-128,127},
    {1,1,2,31,1,1,1,2,1,1,0,0,-128,127},
    {1,1,2,16,1,1,1,2,1,1,0,0,-128,127},
    {1,3,3,1,3,3,3,3,1,1,1,1,-7,9},
    {1,3,3,32,1,1,3,3,2,2,0,0,0,6}};
#ifdef PD_POOL_PROBE_EMULATE
  person_pool::ScalarWindow backend;
#else
  person_pool::RvvWindow backend;
#endif
  uint32_t signature=2166136261u;
  for(int c=0;c<8;++c) {
    const Geometry& g=shapes[c];
    const int n=g.batches*g.height*g.width*g.channels;
    const int out=g.batches*g.out_height*g.out_width*g.channels;
    for(int i=0;i<n;++i) input[i]=static_cast<int8_t>(static_cast<int>(Random()&255)-128);
    if(c==3 || c==7) for(int i=0;i<n;++i) input[i]=(i&1)?127:-128;
    // Exact +/-0.5 cases test division truncation and signed half handling.
    if(c==4 || c==5) for(int i=0;i<g.channels;++i) {
      input[i]=(c==4 ? -1 : 1);input[g.channels+i]=0;
    }
    output[0]=37;output[out+1]=53;
    if(!person_pool::AveragePool(g,input,output+1,backend)) {pd_probe_status=101;return 1;}
    if(output[0]!=37 || output[out+1]!=53) {pd_probe_status=102;return 1;}
    int i=0;
    for(int b=0;b<g.batches;++b) for(int y=0;y<g.out_height;++y)
      for(int x=0;x<g.out_width;++x) for(int k=0;k<g.channels;++k,++i) {
        const int8_t expected=Expected(g,b,y,x,k),actual=output[i+1];
        if(actual!=expected) {
          if(!pd_probe_mismatches) {
            pd_probe_first_expected=static_cast<uint32_t>(expected);
            pd_probe_first_actual=static_cast<uint32_t>(actual);pd_probe_first_case=c;
          }
          ++pd_probe_mismatches;
        }
        ++pd_probe_checked;signature=(signature^static_cast<uint8_t>(actual))*16777619u;
      }
    ++pd_probe_cases;
  }
  pd_probe_commands=backend.blocks;pd_probe_signature=signature;
  if(pd_probe_mismatches || pd_probe_cases!=8 || pd_probe_checked!=659 || backend.blocks!=62 ||
     signature!=642806987u) {
    pd_probe_status=103;return 1;
  }
#ifdef PD_POOL_PROBE_EMULATE
  std::printf("[PERSON_POOL_PROBE_HOST_PASS] cases=%u checked=%u blocks=%u signature=%u RVV=NOT_RUN\n",
      static_cast<unsigned>(pd_probe_cases),static_cast<unsigned>(pd_probe_checked),backend.blocks,signature);
#endif
  pd_probe_status=3;return 0;
}
