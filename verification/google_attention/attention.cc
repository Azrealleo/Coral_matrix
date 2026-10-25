// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Stateful prefill+decode glue; frozen project RoPE/Attention and official Linear.
#include "kernels.h"
#include "attention_layout.h"
#include <cstring>
#ifndef TX_HOST
#include <riscv_vector.h>
#endif
extern "C" {
void RmsNormF(size_t,size_t,float,const float*,const float*,float*);
void rvv_gemv_1d_f32(const float*,const float*,float*,int,int);
void rvv_tiled_matmul_2d_f32(const float*,const float*,float*,int,int,int);
void rvv_residual_add_f32(const float*,const float*,float*,size_t);
volatile unsigned lv_stage_counts[18];
}
namespace {
constexpr unsigned kGuard=0x55aa7711u;
enum { Norm,Q,K,V,QR,KR,PreK,PreV,FinalK,FinalV,Context,Projected,Output };
struct alignas(16) Cache {unsigned before[4];float data[2*attention::kMaxValues];unsigned after[4];};
Case Stage(int kind,int a,int b=0,int c=0,int d=0,int pos=0) {
  return {"attention_stage",kind,a,b,c,d,pos,0,0,0,0,nullptr,nullptr,nullptr,nullptr};
}
void Count(int path,int op){++lv_stage_counts[path*6+op];}
void Invoke(int path,const Case& t,const float* x,const float* w,const float* v,float* y) {
  if(path==0)Scalar(t,x,w,v,y);else Vector(t,x,w,v,y);
}
void Copy(int path,const float* x,int n,float* y) {
#ifndef TX_HOST
  if(path) {
    for(int i=0;i<n;) {
      const auto vl=__riscv_vsetvl_e32m4(n-i);
      __riscv_vse32_v_f32m4(y+i,__riscv_vle32_v_f32m4(x+i,vl),vl);i+=vl;
    }
    return;
  }
#else
  (void)path;
#endif
  for(int i=0;i<n;++i)y[i]=x[i];
}
void Linear(int path,int m,int h,const float* a,const float* b,float* y) {
  if(path==2) {
    if(m==1)rvv_gemv_1d_f32(a,b,y,h,h);
    else rvv_tiled_matmul_2d_f32(a,b,y,m,h,h);
  } else Invoke(path,Stage(MATMUL,m,h,h),a,b,nullptr,y);
}
void Project(int path,int m,int h,int row,const float* x,const float* w,const attention::Layout& l,float* y) {
  const int at=row*h;float* norm=y+l.offset[Norm]+at;
  if(path==2)RmsNormF(m,h,1e-5f,x+at,w,norm);
  else Invoke(path,Stage(RMS,m,h),x+at,w,nullptr,norm);
  Count(path,0);
  for(int k=0;k<3;++k) {
    Linear(path,m,h,norm,w+h+k*h*h,y+l.offset[Q+k]+at);Count(path,1);
  }
  const float* coeff=w+h+4*h*h+at;
  Invoke(path,Stage(ROPE,m,h),y+l.offset[Q]+at,coeff,nullptr,y+l.offset[QR]+at);Count(path,2);
  Invoke(path,Stage(ROPE,m,h),y+l.offset[K]+at,coeff,nullptr,y+l.offset[KR]+at);Count(path,2);
}
void Finish(int path,int m,int h,int row,const float* x,const float* w,const attention::Layout& l,float* y) {
  const int at=row*h;
  Linear(path,m,h,y+l.offset[Context]+at,w+h+3*h*h,y+l.offset[Projected]+at);Count(path,1);
  if(path==2)rvv_residual_add_f32(y+l.offset[Projected]+at,x+at,y+l.offset[Output]+at,m*h);
  else Invoke(path,Stage(RESIDUAL,m*h),y+l.offset[Projected]+at,x+at,nullptr,y+l.offset[Output]+at);
  Count(path,5);
}
void Init(Cache& c,int n) {
  for(int i=0;i<4;++i)c.before[i]=c.after[i]=kGuard;
  for(auto& v:c.data)std::memcpy(&v,&kGuard,4);
  for(int i=0;i<n;++i){c.data[i]=attention::kKeyPoison;c.data[n+i]=attention::kValuePoison;}
}
bool CacheGuard(const Cache& c,int n) {
  for(int i=0;i<4;++i)if(c.before[i]!=kGuard||c.after[i]!=kGuard)return false;
  for(int i=2*n;i<2*attention::kMaxValues;++i){unsigned v;std::memcpy(&v,c.data+i,4);if(v!=kGuard)return false;}
  return true;
}
int Stream(int path,int p,int h,int base,const float* x,const float* w,float* y) {
  const attention::Layout l(p,h,base);const int s=p+1,n=s*h;Cache cache;Init(cache,n);
  Project(path,p,h,0,x,w,l,y);
  Copy(path,y+l.offset[KR],p*h,cache.data);Copy(path,y+l.offset[V],p*h,cache.data+n);Count(path,4);
  Copy(path,cache.data,n,y+l.offset[PreK]);Copy(path,cache.data+n,n,y+l.offset[PreV]);
  Invoke(path,Stage(ATTENTION,1,p,s,h,0),y+l.offset[QR],cache.data,cache.data+n,y+l.offset[Context]);Count(path,3);
  Finish(path,p,h,0,x,w,l,y);
  Project(path,1,h,p,x,w,l,y);
  Copy(path,y+l.offset[KR]+p*h,h,cache.data+p*h);Copy(path,y+l.offset[V]+p*h,h,cache.data+n+p*h);Count(path,4);
  Invoke(path,Stage(ATTENTION,1,1,s,h,p),y+l.offset[QR]+p*h,cache.data,cache.data+n,y+l.offset[Context]+p*h);Count(path,3);
  Finish(path,1,h,p,x,w,l,y);
  Copy(path,cache.data,n,y+l.offset[FinalK]);Copy(path,cache.data+n,n,y+l.offset[FinalV]);
  const bool prefix=std::memcmp(y+l.offset[PreK],cache.data,p*h*4)==0&&std::memcmp(y+l.offset[PreV],cache.data+n,p*h*4)==0;
  const bool tail=std::memcmp(y+l.offset[KR]+p*h,cache.data+p*h,h*4)==0&&std::memcmp(y+l.offset[V]+p*h,cache.data+n+p*h,h*4)==0;
  return prefix&&tail&&CacheGuard(cache,n)?1:0;
}
}
extern "C" {
__attribute__((noinline)) int attention_scalar(int p,int h,int b,const float* x,const float* w,float* y){return Stream(0,p,h,b,x,w,y);}
__attribute__((noinline)) int attention_project(int p,int h,int b,const float* x,const float* w,float* y){return Stream(1,p,h,b,x,w,y);}
__attribute__((noinline)) int attention_candidate(int p,int h,int b,const float* x,const float* w,float* y){return Stream(2,p,h,b,x,w,y);}
__attribute__((noinline)) int attention_bulk(int p,int h,int base,const float* x,const float* w,float* y) {
  const attention::Layout l(p,h,base);const int s=p+1,n=s*h;
  // Counters are checked/saved by the bench before this untimed control.
  Project(2,s,h,0,x,w,l,y);
  Copy(2,y+l.offset[KR],n,y+l.offset[FinalK]);Copy(2,y+l.offset[V],n,y+l.offset[FinalV]);
  Copy(2,y+l.offset[KR],n,y+l.offset[PreK]);Copy(2,y+l.offset[V],n,y+l.offset[PreV]);
  for(int j=p*h;j<n;++j){y[l.offset[PreK]+j]=attention::kKeyPoison;y[l.offset[PreV]+j]=attention::kValuePoison;}
  Invoke(2,Stage(ATTENTION,1,s,s,h,0),y+l.offset[QR],y+l.offset[FinalK],y+l.offset[FinalV],y+l.offset[Context]);
  Finish(2,s,h,0,x,w,l,y);return 1;
}
}
