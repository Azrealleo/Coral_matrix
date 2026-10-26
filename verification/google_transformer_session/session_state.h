// Copyright 2026. SPDX-License-Identifier: Apache-2.0
#pragma once
namespace session {
constexpr int kMaxValues=64;
struct alignas(16) State {
  unsigned before[4];
  unsigned magic,path,h,f,capacity,base,length;
  float key[kMaxValues],value[kMaxValues];
  unsigned after[4];
};
}
extern "C" {
int session_init(session::State*,int path,int h,int f,int capacity,int base);
int session_prefill(session::State*,int rows,const float* x,const float* w,float* y);
int session_decode(session::State*,int absolute_position,const float* token,const float* w,float* y);
}
