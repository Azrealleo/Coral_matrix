// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Explicit RVV, not compiler auto-vectorization. No full-output INT32 scratch.
#pragma once
#include <cstdint>
#include <riscv_vector.h>
namespace person_pool {
struct RvvWindow {
  uint32_t blocks=0;
  void Run(const int8_t* input,int row_stride,int channels,int rows,int columns,
           int low,int high,int8_t* output) {
    const int count=rows*columns;
    for(int c=0;c<channels;) {
      const size_t vl=__riscv_vsetvl_e8m1(channels-c);
      vint32m4_t sum=__riscv_vmv_v_x_i32m4(0,vl);
      for(int y=0;y<rows;++y) for(int x=0;x<columns;++x) {
        const vint8m1_t value=__riscv_vle8_v_i8m1(input+y*row_stride+x*channels+c,vl);
        sum=__riscv_vadd_vv_i32m4(sum,__riscv_vsext_vf4_i32m4(value,vl),vl);
      }
      const vbool8_t positive=__riscv_vmsgt_vx_i32m4_b8(sum,0,vl);
      const vint32m4_t plus=__riscv_vadd_vx_i32m4(sum,count/2,vl);
      const vint32m4_t minus=__riscv_vsub_vx_i32m4(sum,count/2,vl);
      sum=__riscv_vmerge_vvm_i32m4(minus,plus,positive,vl);
      // Signed integer division, exact TFLM rounding including negative ties.
      sum=__riscv_vdiv_vx_i32m4(sum,count,vl);
      sum=__riscv_vmax_vx_i32m4(sum,low,vl);
      sum=__riscv_vmin_vx_i32m4(sum,high,vl);
      const vint16m2_t narrow=__riscv_vncvt_x_x_w_i16m2(sum,vl);
      __riscv_vse8_v_i8m1(output+c,__riscv_vncvt_x_x_w_i8m1(narrow,vl),vl);
      c+=static_cast<int>(vl); ++blocks;
    }
  }
};
}  // namespace person_pool
