// Copyright 2026. SPDX-License-Identifier: Apache-2.0
#pragma once
namespace attention {
constexpr int kStages=13,kMaxValues=64;
constexpr float kKeyPoison=71.25f,kValuePoison=-43.5f;
struct Layout {
  int size[kStages],offset[kStages],guard[kStages-1],total;
  Layout(int p,int h,int):total(0) {
    for(int i=0;i<kStages;++i) {
      size[i]=(p+1)*h;offset[i]=total;total+=size[i];
      if(i<kStages-1){guard[i]=total;total+=4;}
    }
  }
};
}
