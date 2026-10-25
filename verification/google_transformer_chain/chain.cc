// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Composition only. Official functions and the qualified GELU remain unchanged.
#include "kernels.h"
extern "C" {
void RmsNormF(size_t,size_t,float,const float*,const float*,float*);
void rvv_residual_add_f32(const float*,const float*,float*,size_t);
void candidate_gelu_f32(const float*,const float*,float*,size_t);
}
namespace {
Case Stage(int kind,int a,int b=0) {
  return {"chain_stage",kind,a,b,0,0,0,0,0,0,0,nullptr,nullptr,nullptr,nullptr};
}
// Output: norm[n], guard[4], activation[n], guard[4], residual_result[n].
// W: gamma[cols], up[n], residual[n]. Output guards are initialized by the bench.
template <bool vector> void Control(int rows,int cols,const float* x,const float* w,float* y) {
  const int n=rows*cols;
  float* activation=y+n+4;float* output=activation+n+4;
  const auto rms=Stage(RMS,rows,cols),gelu=Stage(GEGLU,n),res=Stage(RESIDUAL,n);
  if(vector) {
    Vector(rms,x,w,nullptr,y);
    Vector(gelu,y,w+cols,nullptr,activation);
    Vector(res,activation,w+cols+n,nullptr,output);
  } else {
    Scalar(rms,x,w,nullptr,y);
    Scalar(gelu,y,w+cols,nullptr,activation);
    Scalar(res,activation,w+cols+n,nullptr,output);
  }
}
}
extern "C" {
__attribute__((noinline)) void chain_scalar(int rows,int cols,const float* x,const float* w,float* y) {
  Control<false>(rows,cols,x,w,y);
}
__attribute__((noinline)) void chain_project(int rows,int cols,const float* x,const float* w,float* y) {
  Control<true>(rows,cols,x,w,y);
}
__attribute__((noinline)) void chain_candidate(int rows,int cols,const float* x,const float* w,float* y) {
  const int n=rows*cols;
  float* activation=y+n+4;float* output=activation+n+4;
  RmsNormF(rows,cols,1e-5f,x,w,y);
  candidate_gelu_f32(y,w+cols,activation,n);
  rvv_residual_add_f32(activation,w+cols+n,output,n);
}
}
