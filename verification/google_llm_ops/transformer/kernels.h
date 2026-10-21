// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Project FP32 operator baseline. Not a pretrained model or official kernel.
#pragma once
#include <cstddef>
enum Kind { MATMUL, RMS, SOFTMAX, ROPE, SWIGLU, GEGLU, RESIDUAL, KVAPPEND, ATTENTION };
struct Case {
  const char* name;
  int kind, a, b, c, d, p;
  unsigned nx, nw, nv, ny;
  const float *x, *w, *v, *gold;
};
extern const Case kCases[];
extern const unsigned kCaseCount;
constexpr unsigned kCapacity=1024, kSamples=4;
constexpr float kAtol=0.00002f, kRtol=0.0002f;
void Scalar(const Case&,const float*,const float*,const float*,float*);
void Vector(const Case&,const float*,const float*,const float*,float*);
