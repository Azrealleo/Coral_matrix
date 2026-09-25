/*
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/*
 * Directed test to verify fault-only-first load instructions:
 * vle8ff.v, vle16ff.v, vle32ff.v across SEW, LMUL, mask, tail, vstart, and RAW hazards.
 */

.section .data
.align 16

# 1. Baseline vle16ff.v
.global v12_init
v12_init:
    .word 0x4ed50000, 0x58526ee4, 0x520cc0dc, 0x30c52616

.global src_data16
src_data16:
    .word 0x11112222, 0x33334444, 0x55556666, 0x77778888

.global v12_result
v12_result:
    .space 16

# 2. Baseline vle8ff.v
.global v8_init
v8_init:
    .word 0xaaaaaaaa, 0xbbbbbbbb, 0xcccccccc, 0xdddddddd

.global src_data8
src_data8:
    .word 0x01020304, 0x05060708, 0x090a0b0c, 0x0d0e0f10

.global v8_result
v8_result:
    .space 16

# 3. Baseline vle32ff.v
.global v4_init
v4_init:
    .word 0x12345678, 0x23456789, 0x3456789a, 0x456789ab

.global src_data32
src_data32:
    .word 0xdeadbeef, 0xcafebabe, 0x01234567, 0x89abcdef

.global v4_result
v4_result:
    .space 16

# 4. Masked vle16ff.v with tu, mu, vl = 5
.global v14_init
v14_init:
    .word 0xbbbbaaaa, 0xddddcccc, 0xffffeeee, 0x56781234

.global mask_data16
mask_data16:
    .word 0x00000015, 0x00000000, 0x00000000, 0x00000000

.global src_data16_masked
src_data16_masked:
    .word 0x02020101, 0x04040303, 0x06060505, 0x08080707

.global v14_result
v14_result:
    .space 16

# 5. Multi-register grouping m2: vle16ff.v (vl = 16, 32 bytes)
.global v16_init
v16_init:
    .word 0xdeaddead, 0xdeaddead, 0xdeaddead, 0xdeaddead
    .word 0xdeaddead, 0xdeaddead, 0xdeaddead, 0xdeaddead

.global src_data16_m2
src_data16_m2:
    .word 0x00020001, 0x00040003, 0x00060005, 0x00080007
    .word 0x000a0009, 0x000c000b, 0x000e000d, 0x0010000f

.global v16_result
v16_result:
    .space 32

# 6. Multi-register grouping m4: vle32ff.v (vl = 16, 64 bytes)
.global v20_init
v20_init:
    .rept 16
    .word 0xbeefbeef
    .endr

.global src_data32_m4
src_data32_m4:
    .word 0x10000001, 0x10000002, 0x10000003, 0x10000004
    .word 0x10000005, 0x10000006, 0x10000007, 0x10000008
    .word 0x10000009, 0x1000000a, 0x1000000b, 0x1000000c
    .word 0x1000000d, 0x1000000e, 0x1000000f, 0x10000010

.global v20_result
v20_result:
    .space 64

# 7. Fractional LMUL mf4: vle8ff.v (vl = 4, 4 bytes)
.global v24_init
v24_init:
    .word 0xabababab, 0xcdcdcdcd, 0xefefefef, 0x01010101

.global src_data8_mf4
src_data8_mf4:
    .word 0x44332211

.global v24_result
v24_result:
    .space 16

# 8. Fractional LMUL mf2: vle16ff.v (vl = 4, 8 bytes)
.global v25_init
v25_init:
    .word 0xfafafafa, 0xfbfbfbfb, 0xfcfcfcfc, 0xfdfdfdfd

.global src_data16_mf2
src_data16_mf2:
    .word 0x22221111, 0x44443333

.global v25_result
v25_result:
    .space 16

# 9. Non-zero vstart: vle16ff.v with vstart = 2, vl = 8
.global v26_init
v26_init:
    .word 0x00020001, 0x00040003, 0x00060005, 0x00080007

.global src_data16_vstart
src_data16_vstart:
    .word 0x00200010, 0x00400030, 0x00600050, 0x00800070

.global v26_result
v26_result:
    .space 16

.global vstart_result
vstart_result:
    .word 0xffffffff

# 10. RAW Hazard: vle16ff.v immediately consumed by vadd.vv
.global src_data16_raw
src_data16_raw:
    .word 0x00020001, 0x00040003, 0x00060005, 0x00080007

.global v29_data
v29_data:
    .word 0x00640064, 0x00640064, 0x00640064, 0x00640064

.global v30_result
v30_result:
    .space 16

# 11. Unaligned vle16ff.v: base + 2, vl = 5, tu (ff_tail_index = 10)
.global v1_init
v1_init:
    .word 0xeeeeeeee, 0xeeeeeeee, 0xeeeeeeee, 0xeeeeeeee

.global src_data16_unaligned
src_data16_unaligned:
    .byte 0x00, 0x00
    .word 0x02020101, 0x04040303, 0x06060505, 0x08080707
    .word 0x0a0a0909

.global v1_result
v1_result:
    .space 16

# 12. Unaligned vle8ff.v: base + 3, vl = 7, tu (ff_tail_index = 7)
.global v2_init
v2_init:
    .word 0xaaaaaaaa, 0xaaaaaaaa, 0xaaaaaaaa, 0xaaaaaaaa

.global src_data8_unaligned
src_data8_unaligned:
    .byte 0x00, 0x00, 0x00
    .byte 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88
    .byte 0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0x00

.global v2_result
v2_result:
    .space 16

# 13. Unaligned vle32ff.v: base + 4, vl = 3, tu (ff_tail_index = 12)
.global v3_init
v3_init:
    .word 0xcccccccc, 0xcccccccc, 0xcccccccc, 0xcccccccc

.global src_data32_unaligned
src_data32_unaligned:
    .word 0x00000000
    .word 0x11111111, 0x22222222, 0x33333333, 0x44444444

.global v3_result
v3_result:
    .space 16

.section .text
.global main
.option norelax

main:
    # 1. Test vle16ff.v (baseline)
    la a0, v12_init
    la a1, src_data16
    la a2, v12_result

    vsetivli x0, 8, e16, m1, ta, ma
    vle16.v v12, (a0)
    vle16ff.v v12, (a1)
    vse16.v v12, (a2)

    # 2. Test vle8ff.v (baseline)
    la a3, v8_init
    la a4, src_data8
    la a5, v8_result

    vsetivli x0, 16, e8, m1, ta, ma
    vle8.v v8, (a3)
    vle8ff.v v8, (a4)
    vse8.v v8, (a5)

    # 3. Test vle32ff.v (baseline)
    la a6, v4_init
    la a7, src_data32
    la t0, v4_result

    vsetivli x0, 4, e32, m1, ta, ma
    vle32.v v4, (a6)
    vle32ff.v v4, (a7)
    vse32.v v4, (t0)

    # 4. Test vle16ff.v masked with tu, mu, vl = 5
    la a0, v14_init
    la a1, src_data16_masked
    la a2, mask_data16
    la a3, v14_result

    vsetivli x0, 8, e16, m1, tu, mu
    vle16.v v14, (a0)
    vlm.v v0, (a2)
    vsetivli x0, 5, e16, m1, tu, mu
    vle16ff.v v14, (a1), v0.t
    vsetivli x0, 8, e16, m1, tu, mu
    vse16.v v14, (a3)

    # 5. Test multi-register grouping m2: vle16ff.v (vl = 16)
    la a0, v16_init
    la a1, src_data16_m2
    la a2, v16_result

    vsetivli x0, 16, e16, m2, ta, ma
    vle16.v v16, (a0)
    vle16ff.v v16, (a1)
    vse16.v v16, (a2)

    # 6. Test multi-register grouping m4: vle32ff.v (vl = 16)
    la a0, v20_init
    la a1, src_data32_m4
    la a2, v20_result

    vsetivli x0, 16, e32, m4, ta, ma
    vle32.v v20, (a0)
    vle32ff.v v20, (a1)
    vse32.v v20, (a2)

    # 7. Test fractional LMUL mf4: vle8ff.v (vl = 4)
    la a0, v24_init
    la a1, src_data8_mf4
    la a2, v24_result

    vsetivli x0, 16, e8, m1, ta, ma
    vle8.v v24, (a0)
    li t1, 4
    vsetvli x0, t1, e8, mf4, ta, ma
    vle8ff.v v24, (a1)
    vse8.v v24, (a2)

    # 8. Test fractional LMUL mf2: vle16ff.v (vl = 4)
    la a0, v25_init
    la a1, src_data16_mf2
    la a2, v25_result

    vsetivli x0, 8, e16, m1, ta, ma
    vle16.v v25, (a0)
    li t1, 4
    vsetvli x0, t1, e16, mf2, ta, ma
    vle16ff.v v25, (a1)
    vse16.v v25, (a2)

    # 9. Test non-zero vstart: vle16ff.v with vstart = 2, vl = 8
    la a0, v26_init
    la a1, src_data16_vstart
    la a2, v26_result
    la a3, vstart_result

    vsetivli x0, 8, e16, m1, tu, mu
    vle16.v v26, (a0)
    li t1, 2
    csrw vstart, t1
    vle16ff.v v26, (a1)
    csrr t2, vstart
    sw t2, 0(a3)
    vsetivli x0, 8, e16, m1, tu, mu
    vse16.v v26, (a2)

    # 10. Test RAW Hazard: vle16ff.v immediately consumed by vadd.vv
    la a0, src_data16_raw
    la a1, v29_data
    la a2, v30_result

    vsetivli x0, 8, e16, m1, ta, ma
    vle16.v v29, (a1)
    vle16ff.v v28, (a0)
    vadd.vv v30, v28, v29
    vse16.v v30, (a2)

    # 11. Test unaligned vle16ff.v: base + 2, vl = 5, tu (ff_tail_index = 10)
    la a0, v1_init
    la a1, src_data16_unaligned
    addi a1, a1, 2
    la a2, v1_result

    vsetivli x0, 8, e16, m1, tu, mu
    vle16.v v1, (a0)
    vsetivli x0, 5, e16, m1, tu, mu
    vle16ff.v v1, (a1)
    vsetivli x0, 8, e16, m1, tu, mu
    vse16.v v1, (a2)

    # 12. Test unaligned vle8ff.v: base + 3, vl = 7, tu (ff_tail_index = 7)
    la a0, v2_init
    la a1, src_data8_unaligned
    addi a1, a1, 3
    la a2, v2_result

    vsetivli x0, 16, e8, m1, tu, mu
    vle8.v v2, (a0)
    vsetivli x0, 7, e8, m1, tu, mu
    vle8ff.v v2, (a1)
    vsetivli x0, 16, e8, m1, tu, mu
    vse8.v v2, (a2)

    # 13. Test unaligned vle32ff.v: base + 4, vl = 3, tu (ff_tail_index = 12)
    la a0, v3_init
    la a1, src_data32_unaligned
    addi a1, a1, 4
    la a2, v3_result

    vsetivli x0, 4, e32, m1, tu, mu
    vle32.v v3, (a0)
    vsetivli x0, 3, e32, m1, tu, mu
    vle32ff.v v3, (a1)
    vsetivli x0, 4, e32, m1, tu, mu
    vse32.v v3, (a2)

    .rept 50
    nop
    .endr

    li t5, 0x800
    csrs mie, t5
    wfi
    ret
