# 实际参考源码与可移植性分析

审查日期2026-10-23。固定版本，不以浮动main作为可重复构建依赖。
未构建或执行官方新编译器；下面关于生成结构的结论来自其C++代码生成源码，
不是本机已经生成并运行了一个官方ELF。新候选是本项目独立实现，不复制Arm汇编。

## 1. Coral 官方矩阵代码生成

- 仓库：<https://github.com/google-coral/coralnpu-compiler>
- 提交：`e45e6bfae5f98985f317a26aa4083d49a8015e4b`
- 文件：[CoralNPUMatrixCodegen.cpp](https://github.com/google-coral/coralnpu-compiler/blob/e45e6bfae5f98985f317a26aa4083d49a8015e4b/compiler/Transforms/CoralNPUMatrixCodegen.cpp)
- `emitTileConfigAsm`约200～215行：配置mtype/vtype/TN，明确跨asm块普通vset可能破坏矩阵状态。
- `emitInlineFusedGEMM`约294～399行：初始化/配置位于K循环之前，
  K循环内部加载并累加，最后`emitTileRowsAsm`统一读回。
- 可使用多tile累加器及有限展开。当前试验只移植单tile configure-once，
  不把其多tile、不同布局、掩码加载、展开收益一起混入一次改动。
- 其INT8分支设置altfmt使第二操作数有符号；我们继续使用已验证的旧版
  signed-A/unsigned-B和X+128补偿，**不认为新编译器可直接配旧RTL运行**。
- 没有宣称其编译器已满足本项目固定容量、所有INT8边界或生产成熟度。

## 2. Arm KleidiAI INT8 SME

- 仓库：<https://github.com/ARM-software/kleidiai>
- 提交：`0ec849c4ee7eecc8e79e6808d20bcdd10e8d137f`
- 实际阅读：[INT8 SME MOPA微内核](https://github.com/ARM-software/kleidiai/blob/0ec849c4ee7eecc8e79e6808d20bcdd10e8d137f/kai/ukernels/matmul/matmul_clamp_qai8_qai8p_qsi8cxp/kai_matmul_clamp_qai8_qai8p2vlx4_qsi8cxp2vlx4sb_2vlx2vl_sme_mopa_asm.S)
- 约68～192行：M/N循环外层管理、K循环内smopa累加，ZA累加器不在每步落内存，
  主循环与K尾部独立；约193行起集中输出转换、scale、舍入、clamp和存储。
- 文件Apache-2.0。参考其配置/计算/输出分离的微内核结构，不移植Arm寄存器、
  SME状态、谓词、FP32量化舍入，也不声称量化输出与固定TFLM逐位等价。
- 后续多累加器或融合后处理是独立候选，需要自己的数值和RTL验收。

## 3. 本次实际选择

先保持packing、补偿、输出格式不变，单独测K-loop调度。
对照不是最初慢实现，而是`add3bc4396da4023a5cc716758e408bdb8c092b5`
派生的已验收全M直接写回实现，在同ELF中重新计时。
将“来源较成熟”和“本次Coral移植已经验证”明确区分；后者仍需新probe。
