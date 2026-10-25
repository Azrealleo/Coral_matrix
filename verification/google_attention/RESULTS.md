# 单头 Attention：prefill→decode RTL 验收

2026-10-25，官方 Coral `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，
单 NPU，ITCM256 KiB / DTCM512 KiB，Verilator。三例性能测试和安全探针均通过。

## 完成的功能

`RMSNorm → Q/K/V Linear → Q/K RoPE → 因果 Attention → O Linear → Residual`。
同一 NPU 调用中先执行 P 个 prefill token，再计算一个 decode token，并复用旧 KV。
H 为单头的 head_dim/隐藏宽度，总 token 数 S=P+1。
确定性合成 FP32 输入和权重驻留 TCM，不是预训练模型，也没有多头、GQA、FFN、
长序列 token 生成、VME 或 DRAM 搬运。

候选采用官方 RMSNorm/FP32 Linear/Residual，RoPE 和 Attention 则复用既有项目 RVV。
project 对照已经使用相同的官方 Linear 及项目 RVV RoPE/Attention；exp 仍为标量 libm。
因此本轮不是新增 Attention 核心优化，周期差还包含包装调度与归一化/残差的差异。
未做逐阶段性能归因。

## 同一 ELF 的周期

| P/H/绝对起始位置 | 标量 | project RVV | candidate | project/candidate |
|---|---:|---:|---:|---:|
| 1/4/3 | 9466 | 7384 | 6557 | 1.1261× |
| 3/6/7（奇数行/尾部） | 22898 | 13690 | 12867 | 1.0640× |
| 4/8/11 | 38918 | 18258 | 17453 | 1.0461× |

三个路径各测首次及三次稳态并轮换顺序，本次每路径四次周期均相同。
原始 mcycle 未扣 3 周期空边界，包含 prefill/decode、缓存初始化/搬运、快照、
软件调用计数和缓存保护检查，是可观察诊断集成路径的周期。
输入加载及读回检查在计时外；RoPE cos/sin 表在主机生成并随输入提供，生成成本未计入。
这些结果不能替代去除诊断后的生产内核、真实 LLM 或实际大 head_dim 的性能。

## 正确性与缓存证据

13 个张量全部满足原门限 `atol=2e-5, rtol=2e-4`。独立 FP64 参考在各张量边界取 FP32。

| P/H | 所有阶段最大绝对误差 | 最终输出最大绝对误差 |
|---|---:|---:|
| 1/4 | 1.19209e-7 | 5.96046e-8 |
| 3/6 | 2.38419e-7 | 5.96046e-8 |
| 4/8 | 1.19209e-7 | 2.98023e-8 |

检查内容包括 norm、Q/K/V、旋转后的 Q/K、prefill KV 快照、最终 KV、context、
O 投影和残差输出。prefill 时未来一行 K/V 被置为 71.25/-43.5，不能泄漏到可见输出。
decode 的系数对应绝对位置 base+P，因果索引对应缓存 0..P。
旧 KV 前缀逐位保留，新一行逐位等于本次 K/V，缓存临时区与输出阶段分隔区全部完整。
无 fault，正常自然停止，输入读回一致；低地址栈检查仅 64 字节，不是完整栈高水位证明。

每例还执行一次未计入性能比值的 candidate 整段计算，13 个张量同时匹配独立参考
及流式结果。bulk 与 streaming 都在真实 RTL 上运行，不能仅依赖两者相同就判定正确。
所有四次流式样本由固件逐项检查，末次再由主机经前门独立读回验收。

软件计数按 norm/Linear/RoPE/Attention/append/Residual 排列：每个路径四次总计
`[8,32,16,8,8,8]`，三路径均相同。计数在 bulk 前快照，不与 bulk 控制混合，
也不代表硬件退休指令计数。checked_elements 包括输出保护槽，bulk_checked 单独记录。

六项本地检查通过：闭式因果参考、绝对 RoPE 表、冻结来源、原生 stream/bulk 接线、
破坏 KV/漏掉 decode RoPE 偏移/取消因果屏蔽均必须失败、实际 RV32 静态链接及损坏
向量入口拒绝。VM native host 测试覆盖四例通过；主机镜像与静态数学桩都不是 RTL 证据。

## 资源和实测墙钟

ELF 占用范围：ITCM 18272 字节、DTCM 静态 37264 字节，heap 剩余 470640 字节，
另留 16 KiB 栈。该尺寸不是完整模型的内存需求。

| P/H | 命令耗时（含 Bazel，秒） | 执行阶段（秒） |
|---|---:|---:|
| 1/4 | 64.26 | 56.86 |
| 3/6 | 101.68 | 94.58 |
| 4/8 | 143.92 | 136.90 |

三个性能命令合计约 5 分 10 秒，不含首次构建与安全探针；墙钟含所有对照和检查，
不能当作 NPU 推理时延或速度比。

## 不可变证据

VM 作业：`/home/lqq/coral_tcm_capacity_8e4_v1/attention.iMVr0T`。

- `prepared/runs/probe.z29k_brm`
- `prepared/runs/case0.6m84kfjn`
- `prepared/runs/case1.dhhqoj9q`
- `prepared/runs/case2.zwpqiuuy`
- `prepared/summary.5ubqfxla/summary.json`、`summary.md`
- `accepted-evidence.tar.gz`：原始日志、XML、退出状态、证明、资源参数及实际 ELF。

| 对象 | SHA256 |
|---|---|
| ELF | `4bca2e8f0229e5830d6cff0b64fd0ba9d73b296a294c6c32c9a40706f516526b` |
| RTL | `477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2` |
| 完整 summary.json | `c11580935e3f85daa315543856c650b1f655f6016a0d81069fe3345368364918` |
| accepted-evidence.tar.gz | `f7948424c8007d1d76401d2d0b59a5cff02aa69811f90bb5c061c842254e6590` |
| 固件包 | `e8704de105aca92ce31531968d33d3b3de3ebe382391dbfcbbedff99423659e7` |

固件包 `prepared/firmware/coral_attention_i256_d512_v1.tar.gz` 不含 RTL。
准备包保持 NOT_RUN；仿真 PASS 证据独立保存，未回写准备包。
本地 `handoff_output/attention_iMVr0T/` 已保存固件和证据并校验下载哈希。
工具冻结身份在仿真后复核不变，完整汇总重新验收三例原始证据。

继承的 observation 中 official_* 槽位代表 candidate，kind=GEGLU 是未用于本包调度的
旧 Case 枚举标签；实际路径由 attention_* 入口调度，没有执行 GELU。
公开 comparison 的 scope、stage 字段和本包源码明确为 Attention。

下一步可把已验收的 Attention 与 FFN 接成一层小型 Transformer，重新验证完整
数据依赖及缓存状态。真实模型权重、更大维度、长序列和外存需要单独建立实验。
