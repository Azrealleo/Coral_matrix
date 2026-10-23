// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Scalar mirrors ONLY for native wiring checks. These do NOT execute RVV.
#include <cmath>
#include <cstddef>
extern "C" {
void rvv_residual_add_f32(const float* x,const float* w,float* y,size_t n) {
  for(size_t i=0;i<n;++i)y[i]=x[i]+w[i];
}
void RmsNormF(size_t rows,size_t n,float e,const float* x,const float* w,float* y) {
  for(size_t r=0;r<rows;++r){float sum=0;for(size_t j=0;j<n;++j)sum+=x[r*n+j]*x[r*n+j];
    const float scale=1.f/std::sqrt(sum/n+e);
    for(size_t j=0;j<n;++j)y[r*n+j]=x[r*n+j]*scale*(1.f+w[j]);}
}
void rvv_tanh_gelu_mul_f32(const float* x,const float* w,float* y,size_t n) {
  for(size_t j=0;j<n;++j){float z=x[j]*std::fma(0.035677408f,x[j]*x[j],0.79788456f);
    float t=z<-3.f?-3.f:z>3.f?3.f:z;
    float approx=t*(t*t+27.f)/(9.f*t*t+27.f),base=x[j]*w[j]*0.5f;
    y[j]=std::fma(base,approx,base);}
}
}
