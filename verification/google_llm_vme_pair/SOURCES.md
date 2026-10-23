# 多累加器参考与当前硬件证据

这是configure-once候选之后的第二个独立调度实验；不宣称已经在Coral上提速。

1. 官方编译器`e45e6bfae5f98985f317a26aa4083d49a8015e4b`的
   [CoralNPUMatrixCodegen.cpp](https://github.com/google-coral/coralnpu-compiler/blob/e45e6bfae5f98985f317a26aa4083d49a8015e4b/compiler/Transforms/CoralNPUMatrixCodegen.cpp)：
   `emitInlineFusedGEMM`为多个输出tile保持累加器，复用已加载的操作数，
   目的tile按4分组。这里仍不是实际运行了官方编译器，也没有移植其新ISA/altfmt。
2. KleidiAI `0ec849c4ee7eecc8e79e6808d20bcdd10e8d137f`的
   [INT8 SME MOPA内核](https://github.com/ARM-software/kleidiai/blob/0ec849c4ee7eecc8e79e6808d20bcdd10e8d137f/kai/ukernels/matmul/matmul_clamp_qai8_qai8p_qsi8cxp/kai_matmul_clamp_qai8_qai8p2vlx4_qsi8cxp2vlx4sb_2vlx2vl_sme_mopa_asm.S)：
   使用多个ZA累加块进行多组外积；只借鉴调度方式，不复制Arm汇编/量化语义。
3. **固定旧RTL自身核对**（8e4df09b，而非浮动新版）：
   - `tests/cocotb/vme_test/vme_test_utils.h`：整型矩阵rd=(tile<<1)|signed_A。
   - `vme_matmul_test_program.cc`：TSS=(tile<<27)|row，并有mt4算术/读写测试入口。
   - `rvv_backend_decode_unit_ari.sv`：TSS取rs1[30:27]；EEW32目的对齐要求vd[2:1]=0。
   - `Zvt/zvt_ctrl.sv`：INT32组跨4个tile bank；选择mt0、mt4不能用mt1。
   因此第二指令同时改变vs2为v24和tile为4，字为0xf38804f7；
   tile4行读写的标量TSS高位为0x20000000，不改原有move指令字。
4. 对照代码来自个人提交`6ee7fd65f44288a8a6271493acfd98397ff2c67e`，
   仅命名空间/入口名调整，保留configure-once算法与机器指令。

新双tile实现/布局/计数器必须通过自己的RTL probe；父版本已通过不能代替本版验证。
