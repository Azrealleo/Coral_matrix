# CoralNPU进度快照：单NPU Transformer/LLM算子

更新日期：2026-10-22（香港时间）。依据用户回传日志和已核对的本地工具；没有直接登录Linux核查实时进程或完整日志。本文是当前状态，历史过程见[全程记录](WORKLOG-and-handover.md)，接手操作见[当前交接](HANDOFF-current.md)。

## 1. 当前任务与范围

- 团队已确定使用官方CoralNPU，Yangg152比较暂停并保留历史。
- 当前只测一个NPU的Transformer/LLM算子，固定ITCM256KiB、DTCM512KiB。不是完整语言模型/文本生成。
- VM只进行Bazel/Chisel生成、主机参考和交叉链接/导出；RTL仿真转EDA152服务器Verilator。
- 本机未登录服务器启动或实时监控任务。已提供21例前台串行命令，**尚未收到整套启动目录或完成结果，不能写为“正在跑”或“全部通过”**。
- 完整MobileNet优化版、Conv RVV新实现、TCM扩容及ITCM扫描均不自动继续；Depthwise遵守用户要求不改动。

## 2. 本轮完成/待验证表

| 项目 | 已有证据 | 当前结论 |
|---|---|---|
| VM INT8 decode_tiny，M1/K32/N32 | `llm_linear_c0.brMbDF`，流水PASS | 标量10563、RVV263周期/调用，40.163498倍 |
| VM INT8 prefill_tiny，M16/K32/N32 | `llm_linear_c1.Ye75FC`，流水PASS | 标量168618、RVV4110周期/调用，41.026277倍 |
| INT8 K64/N64 decode/prefill | 固件已链接，已纳入21例 | 尚无实际RTL结果回传 |
| 17例FP32主机参考 | 本地及导出时的native参考检查 | 不是RVV/NPU执行 |
| FP32 RISC-V完整链接/资源审计 | `llm_server_export.HJkCC5`，实际ELF审计输出 | 已完成，不再写“待完整链接” |
| 不含RTL的服务器小包 | 210545字节，SHA见第3节 | 已实际导出并在服务器单例使用 |
| 原Pool模型复用check | `LLM_SERVER_READY cases=21` | 已确认可复用；该标记自身不运行21例 |
| 服务器INT8 case0 | `LLM_SERVER_JOB_PASS cases=1` | 真实RTL通过，周期与旧VM结果一致 |
| 服务器21例完整套件 | 已给出`all`命令，未收到后续结果 | 待确认启动/执行/验收，不是21例PASS |
| FP32硬件数值与性能 | 只有准备和链接证据 | 尚未收到真实FP32 RTL结果 |
| 完整Transformer block/LLM、多token生成 | 无模型图/权重/tokenizer/生成流程验收 | 未完成，不能给tokens/s |

两种INT8微基准比较朴素标量与固定官方RVV实现，不是VME；速度比为原始内核mcycle之比，空边界3周期单列未扣除。不能将上述40倍外推为模型或架构峰值加速。

## 3. 实际固件和归档身份

VM job：`/home/lqq/coral_tcm_capacity_8e4_v1/llm_server_export.HJkCC5`。

| 固件 | ELF SHA256 | ITCM占用末端/字节 | DTCM静态范围/字节 | 堆剩余/字节 |
|---|---|---:|---:|---:|
| INT8 | `17b3e2b6a5c208f638db2d7b85f4ddc5f8f64c336290093a9a11ce06a3dd072d` | 2976 | 13536 | 494368 |
| FP32 | `ab1c95f0398f1e1ee43a0bc7b94677daebe21fdb4ff359046ce7eecf2c81f312` | 10992 | 59808 | 448096 |

这些是ELF静态审计，不是实际栈峰值/arena峰值；固定预留栈16KiB。两份新链接ELF身份已知，但旧VM两次运行未回传其旧ELF哈希，不能倒填为同一二进制的证明。

- 归档：`coral_llm_ops_i256_d512_v1.tar.gz`。
- 大小：210545字节。
- SHA256：`fab74b4ff7ff643474d10f6b5d6513100e11d66cc8b291c9aca5abe7d2805b25`。
- 服务器包目录：`/data/home2/lqq/Desktop/coral_person_packages/llm_fab74b4f/coral_llm_ops_i256_d512_v1`。
- 包中无新RTL、无模型权重。现有封存包不因仓库文档更新而重打包/覆盖。

## 4. 服务器单例的真实断点

原模型（只读复用）：

```text
/data/home2/lqq/Desktop/coral_person_packages/pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1_verilator_runtime/builds/7a54106b3148.z558xni8
```

本次单例job：

```text
/data/home2/lqq/Desktop/coral_person_packages/llm_fab74b4f/coral_llm_ops_i256_d512_v1_server_runtime/jobs/operators._jxei5s3
```

该job内实际attempt：`attempts/int8_0.g3eqoi8b/`，原始输出`_test.log`，配套`results.xml`、`_test-status.json`、`result.json`；job级`job.json`、`completed/int8_0.json`、`summary.md/json`。本机未直接取得这些完整文件，其路径依据工具命名和用户回传目录记录。

`decode_tiny`每路径4次样本：

- scalar_cycles：`[10563,10563,10563,10563]`。
- rvv_cycles：`[263,263,263,263]`。
- first/steady scalar_over_rvv：`40.163498098859314`。
- useful_macs_per_call：1024；empty_boundary_cycles：3。
- 最终标记：`LLM_SERVER_JOB_PASS cases=1 full_model=NOT_RUN VME=NOT_RUN`。

用户未回传该pilot墙钟耗时，不补造时间。单例job不改计划成为21例；完整套件应有新的job，不能拿此`cases=1`当整套验收。

## 5. 21例覆盖及软件来源

| 组别 | 数量 | 形状/验证重点 | 优化实现来源 |
|---|---:|---|---|
| INT8线性层 | 4 | M1/16，K/N32/64，INT8→INT32 | 原样官方`rvv_int8_matmul.cc` |
| FP32矩阵乘 | 2 | M1/4，K16/N32 | 原样官方`rvv_matmul.cc` |
| RMSNorm | 3 | decode/prefill、37维尾部，Gemma式`(1+w)` | 项目FP32 RVV基线 |
| Softmax | 2 | 稳定减max、±1000输入、37维尾部 | 项目混合RVV，exp仍标量libm |
| RoPE | 2 | split-half、预生成sin/cos | 项目FP32 RVV基线 |
| SwiGLU/GEGLU | 2 | 256元素门控乘法，不是整个FFN | 项目混合RVV，exp/tanh仍标量libm |
| 残差 | 1 | 512元素加法 | 项目FP32 RVV基线 |
| KV追加 | 1 | 旧前缀保持，只计时追加 | 项目FP32 RVV基线 |
| 因果GQA Attention | 4 | prefill/decode/首token/未来K/V毒化，2Q共享1KV | 项目小尺寸FP32基线 |

每路径首次+3次steady，交替执行顺序；fence+mcycle只包围内核，不含host加载/生成/逐项检查。FP32对独立Python FP64参考舍入后的结果核对，atol=2e-5、rtol=2e-4，拒绝NaN/Inf。INT8权重[-127,127]、激活[-128,127]遵守官方输入限制。所有输入resident DTCM，不测试外部流式权重带宽。

验收包括实际输入/两份输出前门读回、guard和未使用尾区、自然halt/status3/无fault/真实调用计数及栈底64字节canary。canary不是完整栈水位；较慢的RVV若正确仍是有效结果，不强迫比值大于1。

## 6. 耗时预估与沟通约定

用户要求：**以后每次给仿真命令，必须先给预计墙钟时间，说明是否包含编译、依据及不确定性；超时与预计分开。**

当前已给21例的估算为1～3小时、建议预留3小时，复用模型所以不含编译。估算基于此前同服务器Person等负载约2800～3000 NPU周期/秒以及本轮规模；4例INT8粗估20～30分钟，17例FP32尚无真实时间，尤其标量libm exp/tanh有不确定性。是低置信度粗估，不是本轮实测或完成承诺，也不是芯片执行时间。

`--timeout 5400`表示每例90分钟墙钟上限，不是整套90分钟。每例预算INT8 case0为200万周期，其余1000万周期，是停止上限而非必须跑满；故障/数值失败会提前停止。收到新case实际耗时后应修正预测，不把超过估计直接判死锁，也不盲目重跑。

## 7. 其他阶段的保留结论

| 阶段 | 已完成的重要事实 | 仍不能声称的内容 |
|---|---|---|
| 官方/Yangg152选型 | 功能/整核端点比较与限制已记录；团队确定官方 | 不继续把两版列为当前待选 |
| TCM容量 | 32/128/512KiB及1/2/4MiB几何抽样、小resident同ELF控制通过；小工作集周期相同 | 4MiB几何PASS不等于4MiB完整模型/全部性能通过 |
| DTCM驻留收益 | T12 32→128KiB同prefix比1.41476；T384 1→2MiB比1.205785 | 依赖固定调度/外存代理，不是阵列峰值或真实SoC带宽 |
| 仿真后端 | 同服务器1MiB T384 VCS37619.46s、Verilator13979.842s，结果EXACT | 不外推所有负载或所有服务器/VM速度 |
| 完整二分类MobileNetV1默认版 | 单person图真实RTL通过，Invoke190673191周期，分数[-113,113]，总65897.933s | 不是两图硬件验证、数据集准确率或VME整网通过 |
| VME Conv/RVV Pool | 短硬件probe分别8组/840和8组/659项通过；Conv片段默认91475 vs VME42713，2.14162倍 | 不是VME对RVV Conv结果，优化整网尚无完成结果 |
| SoC/综合 | 用户报告团队单NPU SoC集成测试通过，后续4核由团队负责 | 本人没有新增4核、DC/200MHz、网表/SDF门仿签核 |

## 8. 当前下一步和交回内容

1. 先确认用户是否已启动21例，不再额外发第二个`all`；取实际`LLM_CONSOLE_LOG`和新`LLM_SERVER_JOB_DIRECTORY`。
2. 已在运行则只读查看日志，不能为查看进度再启动仿真，不按过期PID操作进程。
3. 停止时保存`LLM_SERVER_STOP`、case的`_test.log`、XML、退出状态和job目录；分析原因后再选择resume或新版本，不关校验来通过。
4. 全部验收需新的`LLM_SERVER_JOB_PASS cases=21`及`summary.md/json`；收集原始文件，不只保存终端PASS行。
5. 更新每算子首/稳态周期、数值误差和实际墙钟，识别瓶颈，再讨论VME或完整block/小模型。当前未授权自动扩成完整LLM长任务。

不要改已导出包、旧RTL模型或审计身份，不删除失败日志，不停止其他人的仿真。后续完整可执行命令及接手材料见[HANDOFF-current.md](HANDOFF-current.md)。
