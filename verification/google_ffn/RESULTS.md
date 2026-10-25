# 小型 GEGLU FFN：RTL 验收结果

2026-10-25，官方 Coral `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，
单 NPU，ITCM 256 KiB / DTCM 512 KiB，Verilator。
本实验的三个性能用例及安全探针全部完成真实 RTL 仿真。

## 数据流与测量范围

`x → RMSNorm → 两路 Linear(Gate/Up) → GELU×Up → Linear(Down) → 加 x`。
这是带真实数据依赖、无 bias 的 pre-norm GEGLU FFN 子模块。
确定性合成 FP32 输入和权重已驻留 TCM；没有加载预训练模型。
没有 Attention、token 生成、DRAM 搬运或 VME。

三个对照在同一 ELF 中使用相同输入：

- scalar：原项目标量实现。
- project RVV：原项目 RMSNorm/GELU/Residual；三次 Linear 为官方 Gemma FP32 RVV。
- candidate：官方 RMSNorm/Residual、同样的三次官方 RVV Linear、已验收的高精度
  MLAS 方案 RVV GELU 项目移植。project 路径的 tanh 仍调用标量 libm。

整条 FFN 原始 mcycle 包含三次矩阵投影、算子调用、阶段切换和中间存储。
输入加载、读回校验在计时外；未扣 3 周期空边界。
每条路径测首次及三次稳态，轮换顺序；本次四次周期均相同。
未实现跨算子融合，未将旧单算子周期拼入这些比值。

## 周期结果

M 为行/token 数，H 为隐藏维度，F 为 FFN 中间维度。

| 用例 | M/H/F | 标量 | project RVV | candidate | project/candidate | 严格精度 |
|---|---|---:|---:|---:|---:|---|
| decode | 1/8/16 | 10724 | 5807 | 1151 | 5.0452× | PASS |
| 奇数尾部 | 3/7/13 | 23978 | 13554 | 2578 | 5.2576× | PASS |
| prefill | 4/8/32 | 79347 | 40132 | 4592 | 8.7395× | PASS |

每次调用分别包含 384、819、3072 次有用矩阵 MAC，不含逐元素运算。
它们是小尺寸合成子模块，不代表实际 LLM 隐藏维度。
这些数值不能外推为完整模型加速比或任意 RVV 库的性能。
真实模型 Linear 比重随维度变化，整体收益可能明显不同；也不能只从这三点
推导 token 数的通用性能规律，因为 H/F 同时不同。

## 六阶段正确性

独立 Python FP64 参考在每阶段末取 FP32，保留张量存储边界。
RMSNorm 采用官方 Gemma 的 `1+gamma` 约定；GELU 使用 tanh 形式，不是 erf 形式。
严格门限保持 `atol=2e-5, rtol=2e-4`。

| 用例 | norm 误差 | gate 误差 | up 误差 | activation 误差 | down 误差 | output 误差 |
|---|---:|---:|---:|---:|---:|---:|
| decode | 2.38419e-7 | 5.96046e-8 | 5.96046e-8 | 1.21072e-8 | 2.79397e-9 | 7.45058e-9 |
| 奇数尾部 | 1.19209e-7 | 4.47035e-8 | 5.96046e-8 | 1.49012e-8 | 3.72529e-9 | 3.72529e-9 |
| prefill | 1.19209e-7 | 5.96046e-8 | 1.19209e-7 | 2.98023e-8 | 9.31323e-9 | 5.96046e-8 |

表中为每阶段最大绝对误差，六阶段均 PASS。全部四次调用的输出都由固件检查，
末次全部中间张量再经前门读回独立验收。
五个阶段分隔区和外围保护区逐位一致；无 fault，自然停止，输入读回一致。
诊断的 checked_elements 包括保护区。低地址栈保护只检查 64 字节，不是完整栈高水位。
零输入 M1/H1/F1 探针通过，但不作为性能用例或充分精度覆盖。

本地五项检查及 VM 两项 native host 测试通过，包括独立数学参考、三个不同投影的
接线、交换 Gate/Up 必须失败、保护区低位损坏必须失败、六阶段和布尔标志严格验收、
实际 RV32 gc-sections 链接与五个活跃向量入口审计。删除真实候选向量除法必须被拒绝。
主机镜像和只链接的数学桩不作为硬件执行证据。

## 资源和墙钟耗时

ELF：ITCM 占用范围 16064 字节，DTCM 静态范围 33536 字节；heap 剩余 474368 字节，
另保留 16 KiB 栈。没有使用这些小测试证明完整模型的内存需求。

| 用例 | 命令耗时（含 Bazel，秒） | 执行阶段（秒） |
|---|---:|---:|
| decode | 54.21 | 47.12 |
| 奇数尾部 | 74.91 | 67.79 |
| prefill | 161.71 | 154.56 |

三个性能命令合计约 4 分 51 秒，不含初次构建与安全探针。
墙钟是本次 VM 实测，不能作为 NPU 推理时延或 NPU 加速比。

## 原始证据

VM 独立目录：`/home/lqq/coral_tcm_capacity_8e4_v1/ffn.DkKE4z`。

- `prepared/runs/probe.j3t1x57d`
- `prepared/runs/case0.haqj125h`
- `prepared/runs/case1.d7bjm2n1`
- `prepared/runs/case2.3ume305b`
- `prepared/summary.3sbrr2wx/summary.json`、`summary.md`
- `accepted-evidence.tar.gz`：日志、XML、退出状态、证明、参数和汇总归档。

| 对象 | SHA256 |
|---|---|
| ELF | `bf4040b8888d5250f294377caa9e0886e455e1e88899ac93c79c6f08b8a9501b` |
| RTL | `477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2` |
| 完整 summary.json | `031e44643a522cb9a64a428100828378884b4a7687b4156c9962847504b1be83` |
| accepted-evidence.tar.gz | `66d2cc2229b1c9b42c6e58c0b09fc8b603a2977fbb47a8c8d4c12037ce139246` |
| 固件包 | `d8c2526d1aa8f92edf62bb3d0582f631f541dc639366ebd6b943b95449e5498d` |

固件包 `prepared/firmware/coral_ffn_i256_d512_v1.tar.gz` 不含 RTL，准备包封存为
NOT_RUN，实际仿真证明单独保存。兼容原始 observation 的 official_* 槽位代表 candidate。
最终验收确认冻结工具文件未改；完整汇总从原始日志/XML/状态重新校验三例。
本地证据副本位于 `handoff_output/ffn_DkKE4z/`，已核对下载哈希。
旧三算子链、官方源码、旧工具与旧日志未修改。

## 下一步

可补齐 QKV、RoPE、因果 Attention 与 KV cache 的小尺寸数据依赖，逐步组成
Transformer 层；应复用已有算子验证，重新检查中间结果及整体周期。
外存、真实模型权重和更大隐藏维度必须分别评估，不能由本次结果直接替代。
