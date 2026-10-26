// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Per-phase FFN consumes the actual Attention residual, never the original X.
#include "kernels.h"
#include "layer_layout.h"
extern "C" {
void RmsNormF(size_t,size_t,float,const float*,const float*,float*);
void rvv_gemv_1d_f32(const float*,const float*,float*,int,int);
void rvv_tiled_matmul_2d_f32(const float*,const float*,float*,int,int,int);
void rvv_residual_add_f32(const float*,const float*,float*,size_t);
void candidate_gelu_f32(const float*,const float*,float*,size_t);
volatile unsigned lv_ffn_phase_counts[6];
}
namespace layer_ffn {
Case Stage(int kind,int a,int b=0,int c=0) {
  return {"layer_ffn",kind,a,b,c,0,0,0,0,0,0,nullptr,nullptr,nullptr,nullptr};
}
void Invoke(int path,const Case& t,const float* x,const float* w,float* y) {
  if(path==0)Scalar(t,x,w,nullptr,y);else Vector(t,x,w,nullptr,y);
}
void Linear(int path,int m,int k,int n,const float* a,const float* b,float* y) {
  if(path==2) {
    if(m==1)rvv_gemv_1d_f32(a,b,y,k,n);else rvv_tiled_matmul_2d_f32(a,b,y,m,k,n);
  }else Invoke(path,Stage(MATMUL,m,k,n),a,b,y);
}
}
extern "C" void layer_ffn_phase(int path,int s,int m,int h,int f,int row,
                                const float* x,const float* w,float* y) {
  using namespace layer_ffn;
  const ffn::Layout l(s,h,f);
  float *norm=y+l.offset[0]+row*h,*gate=y+l.offset[1]+row*f,
        *up=y+l.offset[2]+row*f,*activation=y+l.offset[3]+row*f,
        *down=y+l.offset[4]+row*h,*out=y+l.offset[5]+row*h;
  const float *wg=w+h,*wu=wg+h*f,*wd=wu+h*f;
  if(path==2)RmsNormF(m,h,1e-5f,x+row*h,w,norm);
  else Invoke(path,Stage(RMS,m,h),x+row*h,w,norm);
  Linear(path,m,h,f,norm,wg,gate);Linear(path,m,h,f,norm,wu,up);
  if(path==2)candidate_gelu_f32(gate,up,activation,m*f);
  else Invoke(path,Stage(GEGLU,m*f),gate,up,activation);
  Linear(path,m,f,h,activation,wd,down);
  if(path==2)rvv_residual_add_f32(down,x+row*h,out,m*h);
  else Invoke(path,Stage(RESIDUAL,m*h),down,x+row*h,out);
  ++lv_ffn_phase_counts[2*path+(row!=0)];
}
// Frozen Attention source plus two explicit phase hooks, generated with exact checks.
#include "attention_core.h"
namespace {
int Layer(int path,int p,int h,int f,const float* x,const float* w,float* y) {
  const attention::Layout a(p,h,0);
  const float* fw=w+h+4*h*h+(p+1)*h;
  return attention_layer_stream(path,p,h,f,x,w,y,fw,y+a.total+4);
}
}
extern "C" {
__attribute__((noinline)) int layer_scalar(int p,int h,int f,const float* x,const float* w,float* y){return Layer(0,p,h,f,x,w,y);}
__attribute__((noinline)) int layer_project(int p,int h,int f,const float* x,const float* w,float* y){return Layer(1,p,h,f,x,w,y);}
__attribute__((noinline)) int layer_candidate(int p,int h,int f,const float* x,const float* w,float* y){return Layer(2,p,h,f,x,w,y);}
__attribute__((noinline)) int layer_bulk(int p,int h,int f,const float* x,const float* w,float* y) {
  const attention::Layout a(p,h,0);
  const int ok=attention_bulk(p,h,0,x,w,y);
  layer_ffn_phase(2,p+1,p+1,h,f,0,y+a.offset[12],w+h+4*h*h+(p+1)*h,y+a.total+4);
  return ok;
}
}
