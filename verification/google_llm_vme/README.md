# INT8线性层：官方RVV与VME完整调用/权重复用对比

2026-10-22准备阶段。沿用已通过的4种合成resident形状M1/16、K/N32/64、原输入种子/字节，raw INT32输出。**尚无本实验正式ELF或新RTL结果**，不能从旧Conv/probe或21例RVV结果推导VME速度。

独立包`tests/cocotb/llm_vme_linear_v1`，不覆盖旧LLM/FP32/Person/Pool/Conv候选、ELF或RTL。单核ITCM256KiB/DTCM512KiB、栈16KiB。服务器沿用原Pool编译模型和短probe证据，不需要Bazel或重编RTL。

## 三条路径与公平口径

1. `rvv`：原样官方8e4df09b的rvv_int8_matmul.cc，输入X[M,K]/W[K,N]，输出Y[M,N]，都为行主序。
2. `complete`：每次从相同row-major X/W重新打包权重、计算有符号补偿、打包/平移输入、设置矩阵、发射/读回并转换成相同row-major INT32结果。全部计入，不只测阵列。
3. `reuse`：预打包权重只准备一次且单独实测；每次仍包含输入打包/补偿转换、矩阵设置/发射/读回和结果布局。first/steady边际周期之外，必须同时报告首用加上prepack以及4次调用摊销加上prepack的结果。不能拿边际周期冒充冷启动完整收益。

三路径各首次+3次steady，同ELF，轮换先后顺序，fence+mcycle包围调用；计数器调用数更新/guard重置/独立INT64参考检查在窗外。原HardwareTile中的软件issued命令计数在其调用内，开销计入VME，不宣称架构最优或独立退休计数。无自动向量化、无LTO，不让RVV live values跨VME调用；原HardwareTile头按SHA原样复制。

这是一个新的同ELF调用边界，各路径有相应noinline wrapper及分发成本；不能要求本次RVV周期逐字等于旧21例不同ELF的263/4110/577/9134，也不能把两次不同边界拼成新加速比。RVV源码及输入一致，公平对比以新同ELF的三路径结果为准。

当前VME整数指令是signed A × unsigned B。把物理行当输出通道、物理列当输入token：A=W^T、B=X^T+128，每行累加器初始化-128*sum(W)，使最终结果精确等于signed X*W。这是已验证Person路径的同一转换/调用，不是把负数直接当uint8。权重沿用RVV原域[-127,127]、X[-128,127]。M1可能利用率低，VME不一定比RVV快；较慢但正确也应通过。

各路径4次调用，VME每调用软件矩阵命令数为ceil(N/16)*ceil(M/16)*ceil(K/4)，当前两种K/N分别16或64条。四次complete和四次reuse分别累计64或256条；两VME路径总和128或512条。不是硬件退休数。每次有独立INT64结果核验，最终host前门再核对X/W、三份完整输出、权重打包/补偿、工作区、未使用尾区/guard和栈底64字节canary。

## 1. VM只构建、审计并导出小包

预计缓存正常为数分钟级构建，不是仿真；实际依赖机器/缓存。本命令不会启动RTL或编译大模型：

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_llm_vme/build_export.sh
)
```

先native四例签名和735组打包/符号/边界模拟，再实际链接一个新ELF、审计256/512KiB内存和诊断符号、核对与服务器已验证RTL字节一致，导出不含RTL的小包。固定源manifest拒绝覆盖未知修改；正式链接可能暴露本地对象编译未能发现的问题，必须以实际输出为准。

回传`LLM_VME_ELF_AUDIT`与`LLM_VME_PACKET_ARCHIVE/SHA256/BYTES`，再给实际传输/服务器命令，不编造归档哈希。请保留完整job，含host/build日志和ELF/资源/源快照。

## 2. 服务器先pilot，不直接全跑或完整LLM

首例case0，粗估5～15分钟、不含VM构建，首次VME路径尚无实测，完成即停；5400秒和1000万周期是上限非ETA。新包必须独立解压，不覆盖旧包。激活coral-verilator，CC/CXX使用Conda，unset WAVES/GUI/COCOTB_ENABLE_PROFILING。

从新包运行（下面仅列接口，实际路径以导出/传输结果为准）：

```bash
tcm_rtl=/data/home2/lqq/Desktop/coral_person_packages/pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1
tcm_probe="${tcm_rtl}_verilator_runtime/runs/probe.46bl5uqr"
python -u -B server.py --packet "$PWD" --rtl-package "$tcm_rtl" check --probe-run "$tcm_probe"
python -u -B server.py --packet "$PWD" --rtl-package "$tcm_rtl" run --probe-run "$tcm_probe" --case 0
```

持原模型锁，只读核验原producer构建/环境/配方/二进制和probe.46bl5uqr原始证据；不改current_build，不允许工具/模型身份不符后自行重编冒充同一模型。新结果写`<小包>_runtime/runs/case0.*`，保留_test.log、XML、退出状态及结果/源身份。

只有`LLM_VME_CYCLE_COMPARISON`和`LLM_VME_RTL_PASS`才有真实新周期结论。`first/steady_rvv_over_vme_complete>1`表示该完整调用VME更快；reuse必须看含prepack的首用/四次摊销和边际值，不混写成同一比值。后续case1/2/3逐例执行、失败即停，耗时先按pilot修正，不自动启动其他形状。

每个case独立从入口开始；外部中断只重跑选定未完成case并保留旧目录，不是CPU checkpoint。本版是单例驱动，无自动ALL_PASS或隐式恢复。首次pilot通过后再决定是否批跑其余三例。

## 当前不做

- 不增加128/256等更大形状，不把当前4例当真实LLM所有维度。
- 不重新定量化/激活融合，不加载预训练模型/tokenizer，不报告tokens/s。
- 不跑外部AXI权重/大KV带宽，不更改RAM/RTL、不做SoC/多核/PPA/门仿。
- 不改Depthwise、Softmax或门控数学实现。

原21例RVV/标量实测及约52分钟子进程计时仍保留于[既有报告](https://github.com/Azrealleo/Coral_matrix/blob/main/verification/google_llm_ops/RESULTS-20261022.md)，不与本实验计时窗混用。
