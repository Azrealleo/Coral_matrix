# 三算子链 RTL 验收结果

2026-10-25，单 NPU，官方 `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，
ITCM 256 KiB / DTCM 512 KiB，复用原有 Verilator 模型。

## 已完成的范围

合成数据驻留 TCM，依次执行 `RMSNorm → tanh-GELU×Up → Residual`。
三条路径在同一 ELF 中使用相同输入，测首次及三次稳态并轮换执行顺序。
记录总链 mcycle，包含调用、阶段切换及中间张量存储，未扣 3 周期空边界。

候选组合采用未修改的官方 RVV RMSNorm / Residual，以及先前验收的 MLAS
高阶 tanh RVV GELU 项目移植。项目 RVV 对照中的 tanh 仍调用标量 libm。
没有跨算子融合，也不能将旧单算子周期拼入本次比值。

## 真实 RTL 周期

| 形状（行×列） | 标量 | 原项目 RVV | 组合候选 | 项目 RVV / 候选 | 严格精度 |
|---|---:|---:|---:|---:|---|
| 1×32 | 12655 | 11698 | 746 | 15.6810× | PASS |
| 1×37 | 14579 | 13577 | 938 | 14.4744× | PASS |
| 4×64 | 99535 | 91960 | 4154 | 22.1377× | PASS |

每一列在四次采样中的周期均相同。该加速比针对本次项目基线与合成算子链，
不是任意 RVV 库或完整模型的加速比。

## 正确性

三个用例的归一化、激活和最终输出全部通过独立数学参考：
`atol=2e-5, rtol=2e-4`，门限未修改。参考在每阶段末取 FP32，模拟真实张量存储；
归一化采用官方 Gemma 的 `1+gamma` 约定，GELU 是 tanh 形式而非 erf 形式。

| 形状 | 归一化最大绝对误差 | 激活最大绝对误差 | 最终输出最大绝对误差 |
|---|---:|---:|---:|
| 1×32 | 1.19209e-7 | 2.38419e-7 | 2.38419e-7 |
| 1×37 | 1.19209e-7 | 1.19209e-7 | 2.38419e-7 |
| 4×64 | 2.38419e-7 | 4.76837e-7 | 4.76837e-7 |

启动安全探针 1×1 零输入也通过，不计入性能用例。
全部用例自然停止、无 fault、输入读回一致、外围与阶段间保护区逐位一致。
每次调用检查全部中间和最终输出；诊断中的 checked_elements 也计入两个保护区。
低地址栈保护只覆盖 64 字节，不是完整栈高水位证明。

本地五项检查和虚拟机两项 native host 测试通过。覆盖独立阶段参考、输入行间共享、
冻结官方/GELU 源码、真实 RV32 链接及活跃向量入口、严格精度失败拒绝、
保护区一个低位损坏也必须拒绝等。主机镜像不作为 RVV 执行证据。

## 资源与实际耗时

ELF 占用范围：ITCM 14864 字节，DTCM 静态 33472 字节，剩余 heap 474432 字节；
另保留 16 KiB 栈。三个用例命令耗时分别约 64.00、69.05、272.15 秒，
包含 Bazel 开销；执行阶段分别约 55.93、60.81、263.16 秒。
这些是本虚拟机本次实测，不能当作 NPU 推理时间。

## 证据位置与身份

虚拟机作业：`/home/lqq/coral_tcm_capacity_8e4_v1/transformer_chain_v2.33mKyq`。

- `prepared/runs/probe.s1sxdqk1`
- `prepared/runs/case0.67skppwj`
- `prepared/runs/case1.3k592no5`
- `prepared/runs/case2.gdiwxck6`
- `prepared/summary.t_3bkqn8/summary.json` 和 `summary.md`
- `accepted-evidence.tar.gz`：原始日志、退出状态、验收证明、参数和汇总归档。

| 对象 | SHA256 |
|---|---|
| ELF | `69cc3f8316715fce915af0a57ad56ec7d588d9ca74cac881b57e8856c827e955` |
| RTL | `477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2` |
| 完整 summary.json | `0bfd4713f7ad8b9b95014456d63a6f37306160fecac757fc7b1473984a2c23c7` |
| accepted-evidence.tar.gz | `5fe9e24349e4bbfb917589be612de6c9510ff2e0526900a1413e408c03a274e7` |
| 固件导出包 | `0ed2267a1229b322bde002389ee20a3aa4e1e2b7e7b934b35d421496541b0cde` |

源码/工具包为 v2；固件包信封 schema 与文件名仍为 v1：
`prepared/firmware/coral_transformer_chain_i256_d512_v1.tar.gz`，不包含 RTL。
本地已校验的证据副本：`handoff_output/transformer_chain_v2_33mKyq/`。
失败的 v1 准备目录 `transformer_chain.IDSXaA` 保留，未执行 RTL；v2 修正的是
日志检查标记，未改变候选算术或门限。旧实验和原始记录未改写。

## 实际限制与下一步

本实验没有 Attention、Linear/FFN 矩阵投影、模型权重、token 生成或 DRAM 搬运，
不是完整 Transformer Block。输入规模也不代表真实 LLM 的隐藏维度。
下一步可加入小尺寸 Linear 投影，验证具有真实数据依赖的 FFN 子模块；
需要重新建立独立参考并测量整体周期，不能直接外推本次加速比。
