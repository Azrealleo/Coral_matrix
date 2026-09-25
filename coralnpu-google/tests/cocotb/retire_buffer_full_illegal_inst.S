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

.section .data
.align 16

.global trap_info
trap_info:
    .word 0   // mcause
    .word 0   // mepc
    .word 0   // mtval
    .word 0   // trap count

.section .text
.global main
.global coralnpu_exception_handler
.option norelax

coralnpu_exception_handler:
    la t6, trap_info
    csrr a1, mcause
    csrr a2, mepc
    csrr a3, mtval
    sw a1, 0(t6)
    sw a2, 4(t6)
    sw a3, 8(t6)
    lw a4, 12(t6)
    addi a4, a4, 1
    sw a4, 12(t6)
    la a2, test_done
    csrw mepc, a2
    mret

main:
    li t2, 0x20000000   // External AXI memory base address

    // Issue external AXI load (delayed in testbench by 50 cycles)
    lw t1, 0(t2)

    // Fill the remaining 15 slots of the 16-entry RetirementBuffer
    addi t0, zero, 1
    addi t0, t0, 1
    addi t0, t0, 1
    addi t0, t0, 1
    addi t0, t0, 1
    addi t0, t0, 1
    addi t0, t0, 1
    addi t0, t0, 1
    addi t0, t0, 1
    addi t0, t0, 1
    addi t0, t0, 1
    addi t0, t0, 1
    addi t0, t0, 1
    addi t0, t0, 1
    addi t0, t0, 1

    // RetirementBuffer is now completely full (16 entries in flight).
    // The next instruction is an illegal instruction.
.global illegal_inst
illegal_inst:
    .word 0x00000000

    addi t0, t0, 1

test_done:
    wfi
