// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Host arithmetic only; enable PD_POOL_TFLM_REFERENCE for the pinned reference.
#include "pool_core.h"
#include <cstdio>
#include <vector>
#ifdef PD_POOL_TFLM_REFERENCE
#include "tensorflow/lite/kernels/internal/reference/integer_ops/pooling.h"
#endif
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);return 1;}}while(0)
static uint32_t rng=137;
static int8_t Random(){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return static_cast<int8_t>(static_cast<int>(rng&255)-128);}
static bool Reference(const person_pool::Geometry& g,const int8_t* x,int8_t* y) {
#ifdef PD_POOL_TFLM_REFERENCE
  tflite::PoolParams p;
  p.stride_height=g.stride_height;p.stride_width=g.stride_width;p.filter_height=g.filter_height;p.filter_width=g.filter_width;
  p.padding_values.height=g.pad_height;p.padding_values.width=g.pad_width;
  p.quantized_activation_min=g.activation_min;p.quantized_activation_max=g.activation_max;
  const int32_t in[4]={g.batches,g.height,g.width,g.channels},out[4]={g.batches,g.out_height,g.out_width,g.channels};
  return tflite::reference_integer_ops::AveragePool(p,tflite::RuntimeShape(4,in),x,tflite::RuntimeShape(4,out),y);
#else
  for(int b=0;b<g.batches;++b)for(int oy=0;oy<g.out_height;++oy)for(int ox=0;ox<g.out_width;++ox)
    for(int c=0;c<g.channels;++c){
      int sum=0,count=0;
      for(int ky=0;ky<g.filter_height;++ky)for(int kx=0;kx<g.filter_width;++kx){
        const int iy=oy*g.stride_height-g.pad_height+ky,ix=ox*g.stride_width-g.pad_width+kx;
        if(iy>=0&&iy<g.height&&ix>=0&&ix<g.width){sum+=x[((b*g.height+iy)*g.width+ix)*g.channels+c];++count;}
      }
      if(!count)return false;
      int value=sum>0?(sum+count/2)/count:(sum-count/2)/count;
      value=value<g.activation_min?g.activation_min:value>g.activation_max?g.activation_max:value;
      y[((b*g.out_height+oy)*g.out_width+ox)*g.channels+c]=static_cast<int8_t>(value);
    }
  return true;
#endif
}
int main(){
  int cases=0;uint64_t checked=0;
  for(int batches:{1,2})for(int h:{1,3,5})for(int w:{1,3,7})for(int filter:{1,2,3,4})
  for(int stride:{1,2})for(int channels:{1,3,15,16,17,31,32,33,127,256})for(bool same:{false,true}){
    const int oh=same?(h+stride-1)/stride:(h-filter)/stride+1;
    const int ow=same?(w+stride-1)/stride:(w-filter)/stride+1;
    if(!same&&(h<filter||w<filter))continue;
    const int ph=same?((oh-1)*stride+filter-h>0?((oh-1)*stride+filter-h)/2:0):0;
    const int pw=same?((ow-1)*stride+filter-w>0?((ow-1)*stride+filter-w)/2:0):0;
    const int low=cases%3==0?-128:cases%3==1?-12:0,high=cases%3==0?127:cases%3==1?15:67;
    person_pool::Geometry g={batches,h,w,channels,oh,ow,filter,filter,stride,stride,ph,pw,low,high};
    std::vector<int8_t> input(batches*h*w*channels),output(batches*oh*ow*channels+2,37),expected(output.size()-2);
    for(auto& v:input) { v=Random(); }
    input.front()=-128;input.back()=127;
    person_pool::ScalarWindow backend;
    CHECK(Reference(g,input.data(),expected.data()));
    CHECK(person_pool::AveragePool(g,input.data(),output.data()+1,backend));
    CHECK(output.front()==37&&output.back()==37&&backend.blocks>0);
    for(size_t i=0;i<expected.size();++i)CHECK(output[i+1]==expected[i]);
    checked+=expected.size();++cases;
  }
  // All possible signed sums for window counts 1..49, including negative ties.
  for(int count=1;count<=49;++count)for(int sum=-128*count;sum<=127*count;++sum){
    int value=(sum<0?-1:1)*((sum<0?-sum:sum)+count/2)/count;
    value=value<-128?-128:value>127?127:value;
    CHECK(person_pool::RoundedMean(sum,count,-128,127)==value);
  }
  person_pool::Geometry invalid={1,3,3,256,1,1,3,3,2,2,0,0,-128,127};
  int8_t input=0,output=37;person_pool::ScalarWindow backend;
  invalid.channels=INT_MAX;CHECK(!person_pool::AveragePool(invalid,&input,&output,backend));
  invalid.channels=1;invalid.pad_height=100;CHECK(!person_pool::AveragePool(invalid,&input,&output,backend));
  CHECK(output==37);
  std::printf("[PERSON_POOL_CORE_HOST_PASS] cases=%d checked=%llu rounding_counts=49 RVV=NOT_RUN\n",cases,
      static_cast<unsigned long long>(checked));return 0;
}
