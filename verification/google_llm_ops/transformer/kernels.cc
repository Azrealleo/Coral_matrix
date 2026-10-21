// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// New project FP32 baselines. Exp/tanh remain scalar libm, explicitly not a
// fully vectorized transcendental implementation. No approximate math/fast-math.
#include "kernels.h"
#include <cmath>
#include <algorithm>
#ifndef TX_HOST
#include <riscv_vector.h>
extern "C" {
void rvv_gemv_1d_f32(const float*,const float*,float*,int,int);
void rvv_tiled_matmul_2d_f32(const float*,const float*,float*,int,int,int);
}
#endif
namespace {
float SumSquares(const float* x,int n) {
  float result=0;
  for(int i=0;i<n;++i)result+=x[i]*x[i];
  return result;
}
float Dot(const float* x,const float* w,int n) {
  float result=0;
  for(int i=0;i<n;++i)result+=x[i]*w[i];
  return result;
}
void Softmax(const float* x,int n,float* y) {
  float maximum=x[0];
  for(int i=1;i<n;++i)maximum=std::max(maximum,x[i]);
  float sum=0;
  for(int i=0;i<n;++i) {y[i]=std::exp(x[i]-maximum);sum+=y[i];}
  for(int i=0;i<n;++i)y[i]/=sum;
}
#ifndef TX_HOST
float Reduce(const float* x,const float* w,int n) {
  float result=0;
  for(int i=0;i<n;) {
    const size_t vl=__riscv_vsetvl_e32m4(n-i);
    const auto vx=__riscv_vle32_v_f32m4(x+i,vl);
    const auto vw=__riscv_vle32_v_f32m4(w+i,vl);
    const auto product=__riscv_vfmul_vv_f32m4(vx,vw,vl);
    const auto zero=__riscv_vfmv_v_f_f32m1(0,1);
    const auto sum=__riscv_vfredusum_vs_f32m4_f32m1(product,zero,vl);
    result+=__riscv_vfmv_f_s_f32m1_f32(sum);
    i+=vl;
  }
  return result;
}
void Copy(const float* x,int n,float* y) {
  for(int i=0;i<n;) {
    const size_t vl=__riscv_vsetvl_e32m4(n-i);
    __riscv_vse32_v_f32m4(y+i,__riscv_vle32_v_f32m4(x+i,vl),vl);
    i+=vl;
  }
}
void VectorSoftmax(const float* x,int n,float* y) {
  float maximum=x[0],sum=0;
  for(int i=0;i<n;) {
    const size_t vl=__riscv_vsetvl_e32m4(n-i);
    const auto vx=__riscv_vle32_v_f32m4(x+i,vl);
    const auto init=__riscv_vfmv_v_f_f32m1(maximum,1);
    maximum=__riscv_vfmv_f_s_f32m1_f32(__riscv_vfredmax_vs_f32m4_f32m1(vx,init,vl));
    i+=vl;
  }
  // This is scalar exp, not an RVV exp approximation. Included in timing.
  for(int i=0;i<n;++i)y[i]=std::exp(x[i]-maximum);
  for(int i=0;i<n;) {
    const size_t vl=__riscv_vsetvl_e32m4(n-i);
    const auto vy=__riscv_vle32_v_f32m4(y+i,vl);
    const auto zero=__riscv_vfmv_v_f_f32m1(0,1);
    sum+=__riscv_vfmv_f_s_f32m1_f32(__riscv_vfredusum_vs_f32m4_f32m1(vy,zero,vl));
    i+=vl;
  }
  for(int i=0;i<n;) {
    const size_t vl=__riscv_vsetvl_e32m4(n-i);
    const auto vy=__riscv_vle32_v_f32m4(y+i,vl);
    __riscv_vse32_v_f32m4(y+i,__riscv_vfdiv_vf_f32m4(vy,sum,vl),vl);
    i+=vl;
  }
}
#endif
float Gate(float x,bool gelu) {
  if(!gelu)return x/(1.0f+std::exp(-x));
  return 0.5f*x*(1.0f+std::tanh(0.7978845608028654f*(x+0.044715f*x*x*x)));
}
}
__attribute__((noinline))
void Scalar(const Case& t,const float* x,const float* w,const float* v,float* y) {
  switch(t.kind) {
    case MATMUL:
      for(int r=0;r<t.a;++r)for(int c=0;c<t.c;++c) {
        float sum=0;for(int k=0;k<t.b;++k)sum+=x[r*t.b+k]*w[k*t.c+c];
        y[r*t.c+c]=sum;
      } break;
    case RMS:
      for(int r=0;r<t.a;++r) {
        const float scale=1.0f/std::sqrt(SumSquares(x+r*t.b,t.b)/t.b+1.0e-5f);
        for(int c=0;c<t.b;++c)y[r*t.b+c]=x[r*t.b+c]*scale*(1.0f+w[c]);
      } break;
    case SOFTMAX:
      for(int r=0;r<t.a;++r)Softmax(x+r*t.b,t.b,y+r*t.b);
      break;
    case ROPE:
      for(int r=0;r<t.a;++r)for(int i=0;i<t.b/2;++i) {
        const int at=r*t.b+i;const float cosine=w[at],sine=w[at+t.b/2];
        y[at]=x[at]*cosine-x[at+t.b/2]*sine;
        y[at+t.b/2]=x[at+t.b/2]*cosine+x[at]*sine;
      } break;
    case SWIGLU:case GEGLU:
      for(int i=0;i<t.a;++i)y[i]=Gate(x[i],t.kind==GEGLU)*w[i];
      break;
    case RESIDUAL:
      for(int i=0;i<t.a;++i)y[i]=x[i]+w[i];
      break;
    case KVAPPEND: {
      const int old=t.a*t.c,added=t.b*t.c,total=old+added;
      // Old cache content is copied OUTSIDE the measured call, by the bench.
      for(int i=0;i<added;++i) {y[old+i]=w[i];y[total+old+i]=w[added+i];}
      break;
    }
    case ATTENTION:
      for(int h=0;h<t.a;++h)for(int q=0;q<t.b;++q) {
        float scores[32];
        const int visible=std::min(t.c,t.p+q+1); // absolute query position
        for(int k=0;k<visible;++k)scores[k]=Dot(x+(h*t.b+q)*t.d,w+k*t.d,t.d)/std::sqrt(float(t.d));
        Softmax(scores,visible,scores);
        for(int d=0;d<t.d;++d) {
          float sum=0;for(int k=0;k<visible;++k)sum+=scores[k]*v[k*t.d+d];
          y[(h*t.b+q)*t.d+d]=sum;
        }
      } break;
  }
}
__attribute__((noinline))
void Vector(const Case& t,const float* x,const float* w,const float* v,float* y) {
#ifdef TX_HOST
  // Host checks data/reference wiring only. Never claim this executes RVV.
  Scalar(t,x,w,v,y);
#else
  switch(t.kind) {
    case MATMUL:
      if(t.a==1)rvv_gemv_1d_f32(x,w,y,t.b,t.c);
      else rvv_tiled_matmul_2d_f32(x,w,y,t.a,t.b,t.c);
      break;
    case RMS:
      for(int r=0;r<t.a;++r) {
        const float scale=1.0f/std::sqrt(Reduce(x+r*t.b,x+r*t.b,t.b)/t.b+1.0e-5f);
        for(int i=0;i<t.b;) {
          const size_t vl=__riscv_vsetvl_e32m4(t.b-i);
          auto vx=__riscv_vle32_v_f32m4(x+r*t.b+i,vl);
          auto vw=__riscv_vle32_v_f32m4(w+i,vl);
          vx=__riscv_vfmul_vf_f32m4(vx,scale,vl);
          vw=__riscv_vfadd_vf_f32m4(vw,1.0f,vl);
          __riscv_vse32_v_f32m4(y+r*t.b+i,__riscv_vfmul_vv_f32m4(vx,vw,vl),vl);
          i+=vl;
        }
      } break;
    case SOFTMAX:
      for(int r=0;r<t.a;++r)VectorSoftmax(x+r*t.b,t.b,y+r*t.b);
      break;
    case ROPE:
      for(int r=0;r<t.a;++r)for(int i=0;i<t.b/2;) {
        const int at=r*t.b+i;const size_t vl=__riscv_vsetvl_e32m4(t.b/2-i);
        const auto lo=__riscv_vle32_v_f32m4(x+at,vl);
        const auto hi=__riscv_vle32_v_f32m4(x+at+t.b/2,vl);
        const auto co=__riscv_vle32_v_f32m4(w+at,vl);
        const auto si=__riscv_vle32_v_f32m4(w+at+t.b/2,vl);
        const auto out0=__riscv_vfsub_vv_f32m4(__riscv_vfmul_vv_f32m4(lo,co,vl),__riscv_vfmul_vv_f32m4(hi,si,vl),vl);
        const auto out1=__riscv_vfadd_vv_f32m4(__riscv_vfmul_vv_f32m4(hi,co,vl),__riscv_vfmul_vv_f32m4(lo,si,vl),vl);
        __riscv_vse32_v_f32m4(y+at,out0,vl);__riscv_vse32_v_f32m4(y+at+t.b/2,out1,vl);
        i+=vl;
      } break;
    case SWIGLU:case GEGLU:
      // The transcendental Gate is deliberately scalar; multiplication uses RVV.
      for(int i=0;i<t.a;++i)y[i]=Gate(x[i],t.kind==GEGLU);
      for(int i=0;i<t.a;) {
        const size_t vl=__riscv_vsetvl_e32m4(t.a-i);
        const auto gate=__riscv_vle32_v_f32m4(y+i,vl),vw=__riscv_vle32_v_f32m4(w+i,vl);
        __riscv_vse32_v_f32m4(y+i,__riscv_vfmul_vv_f32m4(gate,vw,vl),vl);i+=vl;
      } break;
    case RESIDUAL:
      for(int i=0;i<t.a;) {
        const size_t vl=__riscv_vsetvl_e32m4(t.a-i);
        const auto vx=__riscv_vle32_v_f32m4(x+i,vl),vw=__riscv_vle32_v_f32m4(w+i,vl);
        __riscv_vse32_v_f32m4(y+i,__riscv_vfadd_vv_f32m4(vx,vw,vl),vl);i+=vl;
      } break;
    case KVAPPEND: {
      const int old=t.a*t.c,added=t.b*t.c,total=old+added;
      Copy(w,added,y+old);Copy(w+added,added,y+total+old);break;
    }
    case ATTENTION:
      for(int h=0;h<t.a;++h)for(int q=0;q<t.b;++q) {
        float scores[32];const int visible=std::min(t.c,t.p+q+1);
        for(int k=0;k<visible;++k)scores[k]=Reduce(x+(h*t.b+q)*t.d,w+k*t.d,t.d)/std::sqrt(float(t.d));
        VectorSoftmax(scores,visible,scores);
        for(int d=0;d<t.d;) {
          const size_t vl=__riscv_vsetvl_e32m4(t.d-d);
          auto acc=__riscv_vfmv_v_f_f32m4(0,vl);
          for(int k=0;k<visible;++k)acc=__riscv_vfmacc_vf_f32m4(acc,scores[k],__riscv_vle32_v_f32m4(v+k*t.d+d,vl),vl);
          __riscv_vse32_v_f32m4(y+(h*t.b+q)*t.d+d,acc,vl);d+=vl;
        }
      } break;
  }
#endif
}
