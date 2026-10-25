// Copyright 2026. SPDX-License-Identifier: Apache-2.0
#pragma once
namespace ffn {
struct Layout {
  int size[6],offset[6],guard[5],total;
  Layout(int m,int h,int f):size{m*h,m*f,m*f,m*f,m*h,m*h},total(0) {
    for(int i=0;i<6;++i) {
      offset[i]=total;total+=size[i];
      if(i<5){guard[i]=total;total+=4;}
    }
  }
};
}
