# 单层 Transformer：跨函数调用 KV 与连续多步 decode

2026-10-26，官方 Coral 固定为 `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，
单 NPU，ITCM256 KiB / DTCM512 KiB，复用原 Verilator 模型。
独立 v2 的三个性能用例及安全探针均完成真实 RTL 验收。

## 新增能力和边界

调用方持有 `session::State`，通过以下接口保留 K/V、当前长度和位置：

1. `session_init` 创建状态；再次调用即显式清空并重置。
2. `session_prefill` 处理 P 行，返回后状态长度为 P。
3. 连续调用 `session_decode`，每次只传入一个新 token 的 H 维输入及预期绝对位置，
   在已有 KV 后追加一行，完成 Attention → 残差 → GEGLU FFN → 残差后返回。

本次验证的是**同一次固件执行内，跨独立 C++ 函数调用保留 KV**，不是 NPU 复位、
重新加载固件或跨主机启动后的恢复。State 和输出工作区必须由调用方保持存活、正确配对；
权重、预加载 RoPE 表和状态配置保持不变。没有多层、多头/GQA、并发访问同一状态、
预训练权重、embedding/tokenizer、采样、文字生成或 DRAM 搬运测量。
每个新 token 的输入是已知的合成向量，不是从模型生成的 token。

算子沿用已验收的单层实现：两条 RVV 路径都使用同样的官方 FP32 Linear；candidate
使用官方 RMSNorm/Residual 和高精度 MLAS 方案 RVV GELU，project 使用原项目实现。
RoPE/Attention 沿用项目内核，Attention exp 和 project GELU tanh 仍为标量 libm。
无新增算子算术优化、跨算子融合或逐阶段瓶颈归因，未修改 RTL/ISA、Depthwise 或旧实验。

## 同一 ELF 的整个会话周期

P 为 prefill token 数，T 为后续单 token decode 调用次数，H 为单头隐藏维度，
F 为 FFN 中间宽度。四次采样轮换三路径；本次每路径首次及三次稳态数值均相同。

| P/H/F/T/base | 实际 KV 长度 | scalar | project RVV | candidate RVV | project/candidate |
|---|---|---:|---:|---:|---:|
| 1/4/8/2/3 | 1→2→3 | 45861 | 38572 | 29491 | 1.3079× |
| 2/6/13/3/7 | 2→3→4→5 | 94495 | 66687 | 45087 | 1.4791× |
| 3/8/8/3/11 | 3→4→5→6 | 110240 | 68551 | 51921 | 1.3203× |

原始 mcycle 未扣空边界；整段包含状态初始化、全部 API、缓存/输出快照、
前缀与边界检查及分步计时探针。输出数值验收、阶段保护槽检查、生命周期/隔离控制
在这些性能窗口外，输入加载、前门读回和主机 RoPE 表生成也不计入。
这些是带诊断的驻留数据会话成本，不是生产内核时延或完整 LLM 加速比。
不与上一轮单步实验拼周期：尺寸、步数和状态诊断成本都不同。

## 各次 API 的嵌套周期

下面是三次稳态均值，四次原始样本均相同。每次调用后的 KV 长度由固件实际记录，
各步周期之和必须不超过对应整段样本；状态初始化等窗口外开销不在下表中。

| 用例 | API | 返回后 KV 长度 | project RVV | candidate RVV | project/candidate |
|---|---|---:|---:|---:|---:|
| 1/4/8/2 | prefill | 1 | 10257 | 7153 | 1.4339× |
| 1/4/8/2 | decode1 | 2 | 10859 | 7903 | 1.3740× |
| 1/4/8/2 | decode2 | 3 | 11752 | 8736 | 1.3452× |
| 2/6/13/3 | prefill | 2 | 17859 | 9851 | 1.8129× |
| 2/6/13/3 | decode1 | 3 | 13561 | 8951 | 1.5150× |
| 2/6/13/3 | decode2 | 4 | 14535 | 10069 | 1.4435× |
| 2/6/13/3 | decode3 | 5 | 15682 | 11171 | 1.4038× |
| 3/8/8/3 | prefill | 3 | 20461 | 12927 | 1.5828× |
| 3/8/8/3 | decode1 | 4 | 13128 | 10163 | 1.2917× |
| 3/8/8/3 | decode2 | 5 | 14611 | 11561 | 1.2638× |
| 3/8/8/3 | decode3 | 6 | 15967 | 12891 | 1.2386× |

这些 API 周期包含状态检查、复制、当前 token 的 Attention 和 FFN。
本组 decode 周期随可见历史增加而增长，但新 token 输入也不同，不能将增量都
归因于 Attention 或拟合成真实模型/任意长度的延迟规律。

## 数学、状态和生命周期验收

19 个中间张量全部满足原门限 `atol=2e-5, rtol=2e-4`。参考为独立整序列因果
FP64 计算，在各存储边界取 FP32，并把 Attention 残差接入 FFN。
RMSNorm 采用 `1+gamma`，GELU 采用 tanh 形式，不是 erf 形式。

| P/H/F/T | 全部阶段最大绝对误差 | 层最终输出最大绝对误差 |
|---|---:|---:|
| 1/4/8/2 | 1.19209e-7 | 5.96046e-8 |
| 2/6/13/3 | 2.38419e-7 | 2.98023e-8 |
| 3/8/8/3 | 2.38419e-7 | 5.96046e-8 |

每次 API 返回前检查全部旧 KV 前缀逐位保留、新追加行逐位等于本次 K/V；
prefill 的未来槽带毒值。最终全量前门读回、19 阶段分隔槽、输出/状态保护区均通过。
另有未计时的真实 RTL 整序列 causal bulk 对照，必须同时匹配独立参考及流式输出。

每例还交错执行两个不同状态，分别输入 x 与 -x；两份完整结果分别通过独立参考，
重置后的第一份状态重新执行后也必须正确。生命周期掩码均为 63，要求以下行为：

- 未 prefill 时 decode、重复 prefill、错误绝对位置、状态保护字损坏、缓存已满后的
  decode 均拒绝，并逐字节确认状态和输出不变。
- 显式 `session_init` 后长度为零、KV 恢复毒值，再 prefill/decode 重放成功。

不能仅凭掩码或两实现彼此相同判定正确：原始数值、两份独立参考和边界检查也必须通过。
全部四次流式样本由固件检查，末次结果由主机读回复核；隔离/生命周期控制单独运行一次。
无 fault、自然停止、输入读回一致；低地址栈检查仅 64 字节，不是完整栈高水位证明。

每路径四次调用的软件 Attention 计数为 `[q,4q,2q,q,q,q]`，q=4×(1+T)，分别对应
norm/Linear/RoPE/Attention/append/Residual。FFN prefill/decode 计数为 `[4,4T]`。
它们在未计时控制前快照，不是退休指令数。

六项本地检查通过，覆盖独立因果/接线参考、冻结来源和后端入口、真实 RV32 链接与
活跃 RVV 指令、完整字段验收、原生多步/隔离/生命周期，以及清空旧 KV、错误位置
被接受、错误 RoPE 偏移、取消因果屏蔽和拒绝调用仍改写输出等故障拒绝。
修复后又验证精度比较字段必须为布尔 True。VM native 四例通过；主机镜像和静态桩
均不算硬件执行证据。

## 资源、耗时和范围

ELF 占用范围：ITCM 24000 字节，DTCM 静态 66032 字节，heap 剩余 441872 字节，
另留 16 KiB 栈。State 的 K/V 数据各固定 64 个 float，API/诊断工作区有额外上限；
第三例 F=H 是为控制诊断缓冲区大小，不是实际模型 FFN 扩展比或 NPU 能力上限。
这些小测试不能证明完整模型或长上下文能放入 512 KiB DTCM。

| P/H/F/T | 命令墙钟（含 Bazel，秒） | 执行阶段（秒） |
|---|---:|---:|
| 1/4/8/2 | 214.00 | 207.17 |
| 2/6/13/3 | 305.21 | 298.78 |
| 3/8/8/3 | 346.16 | 339.68 |

v2 三个性能命令合计约 14 分 25 秒，安全探针另约 180.60 秒，构建另计。
这些是虚拟机运行所有对照和检查的墙钟，不是 NPU 推理时间。

## 不可变证据

作业：`/home/lqq/coral_tcm_capacity_8e4_v1/transformer_session_v2.OsybZy`。

- `prepared/runs/probe.0c173uix`
- `prepared/runs/case0.5hqtf9td`
- `prepared/runs/case1.p914uf_x`
- `prepared/runs/case2.k6aanpj6`
- `prepared/summary.p765p834/summary.json`、`summary.md`
- `accepted-evidence.tar.gz`：工具、实际 ELF/封装源码、原始日志/XML/退出状态、证明和汇总。

| 对象 | SHA256 |
|---|---|
| ELF | `980ba63df5d68ae70a6139617cc7caa1775bb060db6338879e150ecee7afbf96` |
| RTL | `477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2` |
| Verilator 可执行模型 | `827680a52a5d3107cfaa3d123af533b9e9d208acf1b44d23a880833bbb09de6c` |
| 完整 summary.json | `74d3d6a5258878826dabdc22862858ccf29861a3de4ae9f2bf8d76838f8cc5d7` |
| accepted-evidence.tar.gz | `2f5c95a09fece548a80377b9c46218d6ec868c63daed268fd505884e80941f19` |
| 固件包 | `d05934bd3aa27728e7a457db88c3e979464ae66d8764afe9331b9324003d8df5` |

目标包为 `tests/cocotb/transformer_session_v2`；固件容器沿用协议命名
`coral_session_i256_d512_v1.tar.gz`。容器准备状态仍为 NOT_RUN，PASS 证明独立保存。
继承的 official_* 观测槽代表 candidate；并非整条路径都是未修改的官方实现。

v1 作业 `transformer_session.6IvSN5` 保留探针及首例原始记录：原始数学观测通过，
但汇总函数误用同名变量，将精度布尔标志输出为整数。v2 分开变量并增加布尔回归检查；
算术、状态源码和输入参考保持相同，但按新的固件/来源身份独立完成以上全部仿真。
未改写 v1 日志、回填哈希或拼用其周期。

本地 `handoff_output/transformer_session_v2_OsybZy/` 已备份并验证下载哈希、实际 ELF、
封装源码和全部四项原始日志/XML/状态。虚拟机完整证明重新验收，本地下载证据重新验收，
均未重跑仿真。本次仅新增候选结果，未更新全局进度及交接文档。
