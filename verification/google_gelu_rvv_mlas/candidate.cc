// Tanh coefficients and Horner scheme adapted from ONNX Runtime MLAS v1.20.1:
// https://github.com/microsoft/onnxruntime/blob/5c1b7ccbff7e5141c1da7a9d963d660e5741c319/onnxruntime/core/mlas/lib/tanh.cpp
// Copyright (c) Microsoft Corporation. All rights reserved. MIT license;
// see LICENSE-MLAS.txt. RVV port and fused GELU/up wrapping: project code.
// Finite, bounded FP32 validation only; not a general libm replacement.
#include <cstddef>
#ifdef TX_HOST
#include <cmath>
#else
#include <riscv_vector.h>
#endif

namespace {
constexpr float a13=-2.76076847742355e-16f, a11=2.00018790482477e-13f;
constexpr float a9=-8.60467152213735e-11f, a7=5.12229709037114e-08f;
constexpr float a5=1.48572235717979e-05f, a3=6.37261928875436e-04f;
constexpr float a1=4.89352455891786e-03f;
constexpr float b6=1.19825839466702e-06f, b4=1.18534705686654e-04f;
constexpr float b2=2.26843463243900e-03f, b0=4.89352518554385e-03f;
#ifndef TX_HOST
inline vfloat32m4_t Horner(vfloat32m4_t p,vfloat32m4_t square,float c,size_t vl) {
  return __riscv_vfmacc_vv_f32m4(__riscv_vfmv_v_f_f32m4(c,vl),p,square,vl);
}
#endif
}

extern "C" __attribute__((noinline))
void candidate_gelu_f32(const float* x,const float* up,float* out,size_t n) {
#ifdef TX_HOST
  // Scalar numerical mirror for host tests ONLY. Does not execute RVV.
  for(size_t i=0;i<n;++i) {
    const float square=x[i]*x[i];
    float z=x[i]*std::fma(0.035677408f,square,0.79788456f);
    z=z<-9.f?-9.f:z>9.f?9.f:z;
    const float zz=z*z;
    float p=std::fma(a13,zz,a11);
    p=std::fma(p,zz,a9);p=std::fma(p,zz,a7);p=std::fma(p,zz,a5);
    p=std::fma(p,zz,a3);p=std::fma(p,zz,a1);p*=z;
    float q=std::fma(b6,zz,b4);q=std::fma(q,zz,b2);q=std::fma(q,zz,b0);
    const float t=p/q,base=(x[i]*up[i])*0.5f;
    out[i]=std::fma(base,t,base);
  }
#else
  for(size_t i=0;i<n;) {
    const size_t vl=__riscv_vsetvl_e32m4(n-i);
    const auto vx=__riscv_vle32_v_f32m4(x+i,vl);
    const auto square=__riscv_vfmul_vv_f32m4(vx,vx,vl);
    auto z=__riscv_vfmacc_vf_f32m4(__riscv_vfmv_v_f_f32m4(0.79788456f,vl),
                                  0.035677408f,square,vl);
    z=__riscv_vfmul_vv_f32m4(vx,z,vl);
    z=__riscv_vfmax_vf_f32m4(z,-9.f,vl);z=__riscv_vfmin_vf_f32m4(z,9.f,vl);
    const auto zz=__riscv_vfmul_vv_f32m4(z,z,vl);
    auto p=Horner(__riscv_vfmv_v_f_f32m4(a13,vl),zz,a11,vl);
    p=Horner(p,zz,a9,vl);p=Horner(p,zz,a7,vl);p=Horner(p,zz,a5,vl);
    p=Horner(p,zz,a3,vl);p=Horner(p,zz,a1,vl);
    p=__riscv_vfmul_vv_f32m4(p,z,vl);
    auto q=Horner(__riscv_vfmv_v_f_f32m4(b6,vl),zz,b4,vl);
    q=Horner(q,zz,b2,vl);q=Horner(q,zz,b0,vl);
    const auto t=__riscv_vfdiv_vv_f32m4(p,q,vl);
    auto base=__riscv_vfmul_vv_f32m4(vx,__riscv_vle32_v_f32m4(up+i,vl),vl);
    base=__riscv_vfmul_vf_f32m4(base,0.5f,vl);
    __riscv_vse32_v_f32m4(out+i,__riscv_vfmacc_vv_f32m4(base,base,t,vl),vl);
    i+=vl;
  }
#endif
}
