// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// No new arithmetic kernel: compose the frozen controls and qualified entries.
#include "kernels.h"
#include "ffn_layout.h"
extern "C" {
void RmsNormF(size_t,size_t,float,const float*,const float*,float*);
void rvv_gemv_1d_f32(const float*,const float*,float*,int,int);
void rvv_tiled_matmul_2d_f32(const float*,const float*,float*,int,int,int);
void rvv_residual_add_f32(const float*,const float*,float*,size_t);
void candidate_gelu_f32(const float*,const float*,float*,size_t);
}
namespace {
Case Stage(int kind,int a,int b=0,int c=0) {
  return {"ffn_stage",kind,a,b,c,0,0,0,0,0,0,nullptr,nullptr,nullptr,nullptr};
}
template <bool vector> void Control(int m,int h,int f,const float* x,const float* w,float* y) {
  const ffn::Layout l(m,h,f);
  const float* wg=w+h;const float* wu=wg+h*f;const float* wd=wu+h*f;
  const auto rms=Stage(RMS,m,h),project=Stage(MATMUL,m,h,f),
             gelu=Stage(GEGLU,m*f),down=Stage(MATMUL,m,f,h),res=Stage(RESIDUAL,m*h);
  if(vector) {
    Vector(rms,x,w,nullptr,y+l.offset[0]);
    Vector(project,y+l.offset[0],wg,nullptr,y+l.offset[1]);
    Vector(project,y+l.offset[0],wu,nullptr,y+l.offset[2]);
    Vector(gelu,y+l.offset[1],y+l.offset[2],nullptr,y+l.offset[3]);
    Vector(down,y+l.offset[3],wd,nullptr,y+l.offset[4]);
    Vector(res,y+l.offset[4],x,nullptr,y+l.offset[5]);
  } else {
    Scalar(rms,x,w,nullptr,y+l.offset[0]);
    Scalar(project,y+l.offset[0],wg,nullptr,y+l.offset[1]);
    Scalar(project,y+l.offset[0],wu,nullptr,y+l.offset[2]);
    Scalar(gelu,y+l.offset[1],y+l.offset[2],nullptr,y+l.offset[3]);
    Scalar(down,y+l.offset[3],wd,nullptr,y+l.offset[4]);
    Scalar(res,y+l.offset[4],x,nullptr,y+l.offset[5]);
  }
}
void Linear(int m,int k,int n,const float* a,const float* b,float* out) {
  if(m==1)rvv_gemv_1d_f32(a,b,out,k,n);
  else rvv_tiled_matmul_2d_f32(a,b,out,m,k,n);
}
}
extern "C" {
__attribute__((noinline)) void ffn_scalar(int m,int h,int f,const float* x,const float* w,float* y) {
  Control<false>(m,h,f,x,w,y);
}
__attribute__((noinline)) void ffn_project(int m,int h,int f,const float* x,const float* w,float* y) {
  Control<true>(m,h,f,x,w,y);
}
__attribute__((noinline)) void ffn_candidate(int m,int h,int f,const float* x,const float* w,float* y) {
  const ffn::Layout l(m,h,f);
  const float* wg=w+h;const float* wu=wg+h*f;const float* wd=wu+h*f;
  RmsNormF(m,h,1e-5f,x,w,y+l.offset[0]);
  Linear(m,h,f,y+l.offset[0],wg,y+l.offset[1]);
  Linear(m,h,f,y+l.offset[0],wu,y+l.offset[2]);
  candidate_gelu_f32(y+l.offset[1],y+l.offset[2],y+l.offset[3],m*f);
  Linear(m,f,h,y+l.offset[3],wd,y+l.offset[4]);
  rvv_residual_add_f32(y+l.offset[4],x,y+l.offset[5],m*h);
}
}
