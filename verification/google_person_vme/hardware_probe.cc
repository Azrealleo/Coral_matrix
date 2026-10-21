// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Short actual VME arithmetic test; NOT a model inference or timing benchmark.
#include "pointwise_core.h"
#ifndef PD_PROBE_EMULATE
#include "vme_tile.h"
#else
#include <cstdio>
#endif
extern "C" {
volatile uint32_t pd_probe_status, pd_probe_cases, pd_probe_checked, pd_probe_mismatches;
uint32_t pd_probe_commands;
volatile uint32_t pd_probe_first_expected, pd_probe_first_actual, pd_probe_first_case;
volatile uint32_t pd_probe_signature;
}
namespace {
person_vme::Workspace workspace;
int8_t input[17*256], weights[17*256], output[17*17+2];
int32_t bias[17];
int seen[17];
uint32_t random_state=137;
uint32_t Random() {
  random_state ^= random_state << 13; random_state ^= random_state >> 17;
  random_state ^= random_state << 5; return random_state;
}
}
int main() {
  pd_probe_status=1;
  // positions, output channels, depth, input zero point.
  const int shapes[][4]={{1,1,1,-128},{13,15,3,-1},{16,16,4,0},
      {17,17,17,127},{3,17,256,-128},{1,2,256,-1},{1,1,7,0},{3,15,64,127}};
  uint32_t signature=2166136261u;
#ifdef PD_PROBE_EMULATE
  person_vme::EmulatedTile backend;
#else
  person_vme::HardwareTile backend(&pd_probe_commands);
#endif
  for (int c=0;c<8;++c) {
    const int positions=shapes[c][0], channels=shapes[c][1], depth=shapes[c][2], zp=shapes[c][3];
    for(int i=0;i<positions*depth;++i) input[i]=static_cast<int8_t>(static_cast<int>(Random()&255)-128);
    for(int i=0;i<channels*depth;++i) weights[i]=static_cast<int8_t>(static_cast<int>(Random()&255)-128);
    input[0]=-128; weights[0]=-128;
    for(int o=0;o<channels;++o) { bias[o]=static_cast<int>(Random()%10001)-5000; seen[o]=0; }
    output[0]=37; output[positions*channels+1]=53;
    auto quantize=[=](int32_t actual,int channel)->int8_t {
      const int p=seen[channel]++;
      int32_t expected=bias[channel];
      for(int k=0;k<depth;++k)
        expected+=static_cast<int>(weights[channel*depth+k])*(static_cast<int>(input[p*depth+k])-zp);
      if(actual!=expected) {
        if(!pd_probe_mismatches) {
          pd_probe_first_expected=static_cast<uint32_t>(expected);
          pd_probe_first_actual=static_cast<uint32_t>(actual); pd_probe_first_case=c;
        }
        ++pd_probe_mismatches;
      }
      ++pd_probe_checked;
      return static_cast<int8_t>(actual < -128 ? -128 : actual > 127 ? 127 : actual);
    };
    if(!person_vme::Pointwise(input,weights,bias,output+1,positions,depth,channels,zp,
                              workspace,backend,quantize)) { pd_probe_status=101; return 1; }
    if(output[0]!=37 || output[positions*channels+1]!=53) {pd_probe_status=102;return 1;}
    for(int o=0;o<channels;++o) if(seen[o]!=positions) {pd_probe_status=103;return 1;}
    for(int i=0;i<positions*channels;++i) signature=(signature^static_cast<uint8_t>(output[i+1]))*16777619u;
    ++pd_probe_cases;
  }
  pd_probe_signature=signature;
  if(pd_probe_mismatches || pd_probe_cases!=8 || pd_probe_checked!=840) {pd_probe_status=104;return 1;}
#ifndef PD_PROBE_EMULATE
  if(pd_probe_commands!=233) {pd_probe_status=105;return 1;}
#else
  std::printf("[PERSON_VME_PROBE_HOST_PASS] cases=%u checked=%u signature=%u hardware=NOT_RUN\n",
      static_cast<unsigned>(pd_probe_cases),static_cast<unsigned>(pd_probe_checked),signature);
#endif
  pd_probe_status=3;
  return 0;
}
