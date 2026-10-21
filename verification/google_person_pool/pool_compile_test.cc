// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Compile-only real RVV probe, NOT hardware execution.
#include "pool_core.h"
#include "pool_rvv.h"
extern "C" bool PersonPoolCompileProbe(const int8_t* input,int8_t* output){
  const person_pool::Geometry g={1,3,3,256,1,1,3,3,2,2,0,0,-128,127};
  person_pool::RvvWindow backend;
  return person_pool::AveragePool(g,input,output,backend);
}
