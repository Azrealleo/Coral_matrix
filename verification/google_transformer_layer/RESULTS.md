# 单层 Transformer：Attention → GEGLU FFN RTL 验收

2026-10-25 完成仿真，2026-10-26 复核并归档。官方 Coral 固定为
`8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，单 NPU，ITCM256 KiB / DTCM512 KiB，
复用原 Verilator 模型。三个性能用例及安全探针全部通过真实 RTL 测试。

## 本次完成的数据流

每个用例先处理 P 个 prefill token，再处理一个 decode token：

1. RMSNorm → Q/K/V Linear → Q/K RoPE → 因果 Attention → O Linear → 残差。
2. 用上述**实际残差输出**执行 RMSNorm → Gate/Up Linear → GELU×Up → Down Linear → 残差。
3. prefill 的 FFN 完成后才进入 decode，decode 复用并追加旧 KV，然后执行自己的 FFN。

H 同时为隐藏宽度和单头 head_dim，F 为 FFN 中间宽度，总 token 数为 P+1。
KV 只在一次调用内部跨两个阶段保留，尚未验证跨独立调用、多步生成或多层缓存。
输入及权重为确定性合成 FP32 数据，驻留 TCM；没有预训练模型、tokenizer、VME、
DRAM 时序或外存搬运测量，也没有修改 RTL/ISA、Depthwise 或旧候选。

同一份 ELF 内比较三条路径：scalar 为原项目标量对照；project RVV 为原项目
RMSNorm/GELU/Residual 和已使用官方 FP32 Linear 的路径；candidate 改用官方
RMSNorm/Residual、同样的官方 Linear，以及已验收的 MLAS 高阶方案 RVV GELU。
RoPE/Attention 仍复用项目实现，exp 为标量 libm，project GELU 的 tanh 也为标量 libm。
没有实现跨算子融合或新增 Attention 核心优化，未做逐阶段性能归因。

## 同一 ELF 的原始周期

下表每行都包含完整的 prefill 和一次 decode，decode 用例名不表示单独测量 decode。

| P/H/F/RoPE 起始位置 | scalar | project RVV | candidate RVV | project/candidate |
|---|---:|---:|---:|---:|
| 1/4/8/3 | 19220 | 14605 | 8648 | 1.6888× |
| 3/6/13/7（尾部尺寸） | 53600 | 32509 | 16703 | 1.9463× |
| 4/8/16/11 | 91580 | 46316 | 22107 | 2.0951× |

三路径各测首次和三次稳态，轮换执行顺序；本次每条路径四次周期均相同。
使用原始 mcycle，未扣 3 周期空边界。计时包含两阶段的算子调用、中间存储、
KV 初始化/搬运/快照、软件计数和缓存保护检查。输入加载和主机读回验收在计时外；
RoPE cos/sin 表由主机生成，生成成本不计入。不能将旧单算子周期拼入这些比值，
也不能从三个 H/F 同时变化的小尺寸推导完整 LLM 加速或 token 数的通用规律。

## 正确性

19 个张量全部满足原门限 `atol=2e-5, rtol=2e-4`，没有放宽精度。
独立 FP64 参考在各阶段存储边界取 FP32，FFN 参考读取 Attention 参考的残差输出。
RMSNorm 使用 Gemma 的 `1+gamma`；GELU 是 tanh 形式，不是 erf 形式。

| P/H/F | 全部阶段最大绝对误差 | 层最终输出最大绝对误差 |
|---|---:|---:|
| 1/4/8 | 1.19209e-7 | 5.96046e-8 |
| 3/6/13 | 2.38419e-7 | 5.96046e-8 |
| 4/8/16 | 2.38419e-7 | 5.96046e-8 |

检查范围：Attention 的 13 个张量和 FFN 的 norm/gate/up/activation/down/output。
每个阶段分隔区和外围保护区逐位完整；旧 KV 前缀逐位保留，新尾部逐位匹配新 K/V；
prefill 的未来 KV 行带毒值，不能泄漏到可见输出。decode 使用预加载的绝对位置系数。
全部四次流式样本由固件检查，末次全部输出再经 AXI 前门读回独立验收。
无 fault，自然停止，输入读回一致；低地址栈检查仅 64 字节，不是完整栈高水位证明。

每例另运行一次未计入性能比值的 candidate 整序列因果计算；19 个张量同时匹配
独立参考和流式输出。它在真实 RTL 上执行，不能仅因 bulk/streaming 相同就判定正确。
三路径各四次流式调用的软件 Attention 计数均为 `[8,32,16,8,8,8]`，分别对应
norm/Linear/RoPE/Attention/append/Residual；FFN prefill/decode 计数均为 `[4,4]`。
计数在 bulk 前快照，是软件诊断，不是硬件退休指令数。

六项本地检查通过，覆盖独立接线/因果参考、冻结来源与构建头文件约束、原生
stream/bulk 组合、实际 RV32 链接与向量入口审计、完整验收字段检查。
误将原始 x 接入 FFN、破坏 KV、取消因果屏蔽、漏掉 decode RoPE 偏移、写坏阶段
保护区或删除真实 Gemv 向量算术都必须被拒绝。VM native host 测试四例通过。
这些主机镜像和静态链接桩不作为 RTL 执行证据。

## 资源与耗时

ELF 占用范围：ITCM 20960 字节、DTCM 静态 46608 字节；heap 剩余 461296 字节，
另留 16 KiB 栈。这些是本小尺寸合成测试的资源，不是完整模型的内存需求。

| P/H/F | 命令耗时（含 Bazel，秒） | 执行阶段（秒） |
|---|---:|---:|
| 1/4/8 | 106.12 | 97.40 |
| 3/6/13 | 203.38 | 194.07 |
| 4/8/16 | 298.80 | 290.21 |

三个性能命令合计约 10 分 8 秒，不含构建与安全探针；探针命令约 83.64 秒。
这些墙钟是本虚拟机运行所有对照及检查的耗时，不是 NPU 推理时延。

## 原始证据和版本

VM 作业：`/home/lqq/coral_tcm_capacity_8e4_v1/transformer_layer_v2.wSv2AF`。

- `prepared/runs/probe.rhtvy279`
- `prepared/runs/case0.kt3_vtaf`
- `prepared/runs/case1.9omsljp7`
- `prepared/runs/case2.1fqgll4g`
- `prepared/summary.q72ja4n3/summary.json`、`summary.md`
- `accepted-evidence.tar.gz`：冻结工具、实际固件/源码、原始日志、XML、状态、证明及汇总。

| 对象 | SHA256 |
|---|---|
| ELF | `2731a93f99677b2a3ec907c7d413143ee8ed67e58a1c0986060cf9ab99aa60ca` |
| RTL | `477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2` |
| Verilator 可执行模型 | `827680a52a5d3107cfaa3d123af533b9e9d208acf1b44d23a880833bbb09de6c` |
| 完整 summary.json | `5b2643d60a33315c42e720b583a6d934ac39831be334b919e73a779157d1aab8` |
| accepted-evidence.tar.gz | `42a577af01fe03b53e72807c53d6eb9472501f4b7d2198ac18875b21dea924e5` |
| 固件包 | `be7da9c6e74ef2e7ae3c8264fa2b3fda3dfaeeedbb654d7cb54445f90874ae56` |

生成目标为 `tests/cocotb/transformer_layer_v2`。固件包保留继承的协议命名
`coral_layer_i256_d512_v1.tar.gz`，其准备状态仍为 NOT_RUN，实际 PASS 证据独立保存。
observation 中继承的 official_* 槽位代表 candidate，不代表整条路径都为未修改的官方库。

首次 v1 准备作业 `transformer_layer.gH4esB` 的 native 测试通过，但 Bazel 的 hdrs
规则拒绝 `.inc` 后缀，尚未运行 RTL。v2 独立生成 `.h` 片段并完成以上测试；
失败 v1 的源码、工具包和日志原样保留，未回写哈希或替换旧包。

本地备份：`handoff_output/transformer_layer_v2_wSv2AF/`，已检查下载哈希及全部四项
原始日志/XML/退出状态、固件/封装源码。虚拟机重新核验完整模型/ELF/来源证明，
本地核验下载证据；核验均未重跑仿真。本次只新增实验结果，未更新全局进度和交接文档。
