// Copyright 2026. SPDX-License-Identifier: Apache-2.0
#pragma once
#include "attention_layout.h"
#include "ffn_layout.h"
namespace session {
struct Layout {
  int size[19],offset[19],guard[18],total;
  Layout(int p,int h,int f,int t,int):total(0) {
    const attention::Layout a(p+t-1,h,0);const ffn::Layout b(p+t,h,f);
    for(int i=0;i<19;++i) {
      size[i]=i<13?a.size[i]:b.size[i-13];offset[i]=total;total+=size[i];
      if(i<18){guard[i]=total;total+=4;}
    }
  }
};
}
