// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// NHWC INT8 pooling with the pinned TFLM signed rounding rule, no rescaling.
#pragma once
#include <cstdint>
#include <climits>
#include <cstddef>
#include <initializer_list>

namespace person_pool {
struct Geometry {
  int batches, height, width, channels, out_height, out_width;
  int filter_height, filter_width, stride_height, stride_width, pad_height, pad_width;
  int activation_min, activation_max;
};
struct Window { int y, x, height, width; };
inline Window GetWindow(const Geometry& g, int y, int x) {
  const int64_t origin_y=static_cast<int64_t>(y)*g.stride_height-g.pad_height;
  const int64_t origin_x=static_cast<int64_t>(x)*g.stride_width-g.pad_width;
  const int64_t y0=origin_y<0?0:origin_y, x0=origin_x<0?0:origin_x;
  const int64_t end_y=origin_y+g.filter_height, end_x=origin_x+g.filter_width;
  const int64_t y1=end_y>g.height?g.height:end_y, x1=end_x>g.width?g.width:end_x;
  if(y0>=y1 || x0>=x1) return Window{0,0,0,0};
  return Window{static_cast<int>(y0),static_cast<int>(x0),static_cast<int>(y1-y0),static_cast<int>(x1-x0)};
}
inline bool Valid(const Geometry& g) {
  if(g.batches<1 || g.height<1 || g.width<1 || g.channels<1 || g.out_height<1 || g.out_width<1 ||
     g.filter_height<1 || g.filter_width<1 || g.stride_height<1 || g.stride_width<1 ||
     g.pad_height<0 || g.pad_width<0 || g.activation_min < -128 || g.activation_max>127 ||
     g.activation_min>g.activation_max || static_cast<int64_t>(g.filter_height)*g.filter_width>65536)
    return false;
  // Check incrementally so even deliberately malformed INT_MAX dimensions
  // cannot overflow a signed 64-bit product during validation.
  int64_t input=g.batches,output=g.batches;
  for(int d:{g.height,g.width,g.channels}) { input*=d; if(input>INT_MAX)return false; }
  for(int d:{g.out_height,g.out_width,g.channels}) { output*=d; if(output>INT_MAX)return false; }
  for(int y=0;y<g.out_height;++y) for(int x=0;x<g.out_width;++x) {
    const Window w=GetWindow(g,y,x);
    if(!w.height || !w.width) return false;
  }
  return true;
}
inline int8_t RoundedMean(int32_t sum,int count,int low,int high) {
  sum=(sum>0 ? sum+count/2 : sum-count/2)/count; // C++ truncates toward zero.
  if(sum<low)sum=low;
  if(sum>high)sum=high;
  return static_cast<int8_t>(sum);
}
struct ScalarWindow {
  uint32_t blocks=0;
  void Run(const int8_t* input,int row_stride,int channels,int rows,int columns,
           int low,int high,int8_t* output) {
    for(int c=0;c<channels;c+=16) {
      const int n=channels-c<16?channels-c:16;
      int32_t sums[16]={};
      for(int y=0;y<rows;++y) for(int x=0;x<columns;++x)
        for(int l=0;l<n;++l) sums[l]+=input[y*row_stride+x*channels+c+l];
      for(int l=0;l<n;++l) output[c+l]=RoundedMean(sums[l],rows*columns,low,high);
      ++blocks;
    }
  }
};
template<typename Backend>
bool AveragePool(const Geometry& g,const int8_t* input,int8_t* output,Backend& backend) {
  if(!input || !output || input==output || !Valid(g))return false;
  for(int b=0;b<g.batches;++b) for(int y=0;y<g.out_height;++y) for(int x=0;x<g.out_width;++x) {
    const Window w=GetWindow(g,y,x);
    const size_t in=((static_cast<size_t>(b)*g.height+w.y)*g.width+w.x)*g.channels;
    const size_t out=((static_cast<size_t>(b)*g.out_height+y)*g.out_width+x)*g.channels;
    backend.Run(input+in,g.width*g.channels,g.channels,w.height,w.width,
                g.activation_min,g.activation_max,output+out);
  }
  return true;
}
}  // namespace person_pool
