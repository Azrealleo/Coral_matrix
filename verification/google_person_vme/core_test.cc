// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Native arithmetic test, NOT hardware VME or quantization validation.
#include "pointwise_core.h"
#include <cstdio>
#include <cstdlib>
#include <vector>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while (0)
static uint32_t rng = 137;
static uint32_t Random() { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }
int main() {
  person_vme::Workspace workspace;
  person_vme::EmulatedTile backend;
  int cases = 0;
  const int depths[] = {1,2,3,4,7,15,16,17,31,64,127,128,255,256};
  const int shapes[][2] = {{1,1},{15,17},{16,16},{17,31},{31,2},{3,256}};
  for (int depth : depths) for (const auto& shape : shapes) for (int zp : {-128,-1,0,127}) {
    const int positions = shape[0], outputs = shape[1];
    std::vector<int8_t> x(positions*depth), w(outputs*depth), y(positions*outputs+2, 37);
    std::vector<int32_t> bias(outputs), expected(positions*outputs);
    std::vector<int> seen(outputs);
    for (auto& v : x) v = static_cast<int8_t>(static_cast<int>(Random() & 255)-128);
    for (auto& v : w) v = static_cast<int8_t>(static_cast<int>(Random() & 255)-128);
    // Explicit extreme pairs in addition to randomized signed activations/B.
    x[0] = -128; w[0] = -128;
    for (auto& v : bias) v = static_cast<int>(Random() % 10001)-5000;
    const bool use_bias = cases % 2 == 0;
    for (int p=0;p<positions;++p) for(int o=0;o<outputs;++o) {
      int64_t sum = use_bias ? bias[o] : 0;
      for(int k=0;k<depth;++k) sum += static_cast<int64_t>(w[o*depth+k]) * (static_cast<int>(x[p*depth+k])-zp);
      CHECK(sum>=INT32_MIN && sum<=INT32_MAX);
      expected[p*outputs+o] = static_cast<int32_t>(sum);
    }
    bool equal = true;
    auto quantize = [&](int32_t value,int channel) -> int8_t {
      const int p = seen[channel]++;
      if(p>=positions || value!=expected[p*outputs+channel]) equal=false;
      return static_cast<int8_t>(value < -128 ? -128 : value > 127 ? 127 : value);
    };
    CHECK(person_vme::Pointwise(x.data(),w.data(),use_bias?bias.data():nullptr,y.data()+1,
          positions,depth,outputs,zp,workspace,backend,quantize));
    CHECK(equal && y.front()==37 && y.back()==37);
    for(int count:seen) CHECK(count==positions);
    ++cases;
  }
  int8_t x=127,w=127,y=37;
  int32_t bias=INT32_MAX;
  auto quantize=[](int32_t,int)->int8_t{return 0;};
  CHECK(!person_vme::Pointwise(&x,&w,&bias,&y,1,1,1,-128,workspace,backend,quantize));
  CHECK(!person_vme::Pointwise(&x,&w,nullptr,&y,1,257,1,0,workspace,backend,quantize));
  CHECK(!person_vme::Pointwise(&x,&w,nullptr,&y,1,1,1,-129,workspace,backend,quantize));
  CHECK(!person_vme::Pointwise(nullptr,&w,nullptr,&y,1,1,1,0,workspace,backend,quantize));
  CHECK(y==37);
  std::printf("[PERSON_VME_CORE_HOST_PASS] cases=%d raw_accumulators=EXACT hardware=NOT_RUN quantization=NOT_TESTED\n",cases);
  return 0;
}
