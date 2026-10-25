# CoralNPU 当前进度：算子优化与 Transformer 子模块

更新：2026-10-25（香港时间）。最近代码提交 `445c3d8`。本次通过SSH只读复核VM证据，未新增仿真、未修改内核/RTL/封存包。10个作业的36条性能记录通过冻结收集器校验；其中旧官方GELU三条仅为算法诊断，不能写成“36个严格数学PASS”或“36个完整模型”。

入口：[当前交接](HANDOFF-current.md)、[全程记录第30节](WORKLOG-and-handover.md#section-30)、[机器可读证据索引](EVIDENCE-current.json)。[10月22日进度](PROGRESS-archive-20261022.md)只保留当时状态。

## 1. 当前方向与准确断点

- 团队已选官方CoralNPU；Yangg152比较保留为历史，不恢复选型。
- 单NPU固定 **ITCM256KiB / DTCM512KiB**，官方源 `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`；没有升级RTL/ISA。
- 已从单算子推进到三算子链、小型GEGLU FFN、单头Attention的prefill→一次decode。
- **Attention和FFN分别通过，尚未接成同一层Transformer。下一步是组合验证。**
- 未加载预训练LLM、权重/tokenizer，没有完整模型、长序列生成或tokens/s结果。
- 本机现可SSH直连VM，预计一小时内的仿真可在VM进行；服务器保留长任务备选。“VM只构建、必须服务器仿真”是旧分工。
- Depthwise保持官方实现；Person优化整网、Conv RVV比较、TCM/ITCM扫描不自动恢复。

## 2. 本次核实的完成范围

比例表示该作业的已验收性能例/计划性能例，均另有候选自己的探针。各作业是不同ELF/基线，不能拼接周期。目录均在 `/home/lqq/coral_tcm_capacity_8e4_v1/` 下。

| 阶段 | VM作业短名 | 完成 | 当前结论 |
|---|---|---:|---|
| RVV打包、补偿、直接写回VME | `llm_vme_opt_session.cjfZc9` | 4/4 | 四种INT8形状通过，最初快路径限M1/16 |
| M维度直接写回扫描 | `llm_vme_m_sweep.AahVsZ` | 6/6 | K=N64，M1/2/4/8/12/16通过 |
| 更大K/N、M分块 | `llm_vme_large.UDDMQw` | 1/8 | 只验收case0控制及新探针，另7例未完成 |
| configure-once K循环 | `llm_vme_mature.sdcZkW` | 4/6 | M1/8/12/16通过，M2/4未验收 |
| mt0/mt4共享输入 | `llm_vme_pair.kudXJL` | 3/6 | M8/12/16通过，M1/2/4未验收 |
| 原样官方RVV直接调用 | `official_rvv.aI9wIK` | 6/6 | Residual/RMS三例严格PASS，GELU三例仅算法诊断 |
| 独立高精度RVV GELU | `gelu_rvv_mlas_v2.4yHOrK` | 3/3 | 三例严格PASS，未改官方低精度实现 |
| RMSNorm→GELU×Up→Residual | `transformer_chain_v2.33mKyq` | 3/3 | 三阶段严格PASS |
| 含三次Linear的GEGLU FFN | `ffn.DkKE4z` | 3/3 | 六阶段严格PASS |
| 单头Attention+KV复用 | `attention.iMVr0T` | 3/3 | 13张量、因果关系、KV保留及硬件bulk对照通过 |

这只证明已测形状/输入/身份，不证明任意形状或完整模型。某些旧候选README仍写“尚未RTL”，那是参与冻结身份的准备时文字；以本表及原证据为准，不为改状态去编辑冻结输入。

## 3. VME优化结果与冷启动边界

原始四例VME已经真实RTL通过，但慢于官方RVV。分段profile显示打包、累加器初始化、输出布局的软件成本较大；后续依次实现RVV打包/补偿、直接写回、全M快路径、configure-once K循环、双累加器共享输入。借鉴成熟内核调度，不直接移植Arm指令、不改变旧矩阵编码。

最新pair-v2同一ELF，K=N64：

| M | RVV | 单tile完整/复用 | pair完整/复用 | RVV/pair复用 | 四次含一次预打包的pair总成本 |
|---|---:|---:|---:|---:|---:|
| 8 | 4605 | 7254 / 4766 | 6596 / 4103 | 1.1223× | 18855（RVV18420） |
| 12 | 6873 | 7830 / 5342 | 7172 / 4679 | 1.4689× | 21159（RVV27492） |
| 16 | 9141 | 8051 / 5563 | 7380 / 4887 | 1.8705× | 21991（RVV36564） |

pair一次权重预打包实测2443周期。复用列排除该成本，不是冷启动收益；M8四次含预打包仍稍慢，M12完整调用仍略慢，M16本作业完整调用已快于RVV。只读[摊销分析](google_llm_vme_analysis/README.md)不是额外RTL测量。不得插值宣称通用M切换阈值。

INT8仍为X[-128,127]、W[-127,127]到raw INT32，不含量化、激活或外存。large剩余形状没有被case0控制自动覆盖。

## 4. 官方FP32算子与新组合结果

### 4.1 原样官方RVV的实际效果

| 用例 | 原项目RVV | 官方RVV | 项目/官方 | 数学质量 |
|---|---:|---:|---:|---|
| residual256 | 598 | 280 | 2.1357× | 严格PASS |
| RMSNorm 1×64 | 620 | 308 | 2.0130× | 严格PASS |
| RMSNorm 3×37 | 1269 | 788 | 1.6104× | 严格PASS |
| GELU×Up32 | 11205 | 287 | 39.0418× | 严格FAIL，仅算法诊断 |
| GELU×Up37 | 13367 | 411 | 32.5231× | 严格FAIL，仅算法诊断 |
| GELU×Up256 | 89755 | 1771 | 50.6804× | 严格FAIL，仅算法诊断 |

官方GELU最大绝对误差约0.034～0.041，未放宽门限。[只读归因](google_official_rvv_analysis/README.md)表明当前输入未触发clamp，主要误差来自低阶有理函数，系数舍入影响不超过约5.96e-8。失败元素数不是数据集分类准确率。

### 4.2 已严格验收的新候选

每行均在同一新ELF内比较原项目RVV和候选；原项目门控的tanh仍为标量libm，不是任意RVV数学库的通用速度排名。

| 模块/形状 | 原项目RVV→候选周期 | 比率 | 精度 |
|---|---|---|---|
| 高精度GELU 32/37/256元素 | 11178→434；13338→571；89559→2828 | 25.76 / 23.36 / 31.67× | 3/3严格PASS |
| 三算子链1×32/1×37/4×64 | 11698→746；13577→938；91960→4154 | 15.68 / 14.47 / 22.14× | 三阶段PASS |
| FFN M/H/F=1/8/16、3/7/13、4/8/32 | 5807→1151；13554→2578；40132→4592 | 5.05 / 5.26 / 8.74× | 六阶段PASS |
| Attention P/H=1/4、3/6、4/8 | 7384→6557；13690→12867；18258→17453 | 1.13 / 1.06 / 1.05× | 13张量PASS |

高精度GELU采用固定ONNX Runtime MLAS高阶tanh方案的独立RVV移植，保留MIT许可，不是原样官方内核。主机81925点有界数值检查和三例RTL分开报告，不保证任意FP32/NaN/Inf。

三算子链没有投影；FFN有Gate/Up/Down三投影；Attention有QKV/O四投影。两条RVV路径的Linear相同，均为官方实现。Attention/RoPE主体仍为原项目RVV，exp仍标量libm，没有声称新增Attention核心优化。

Attention在一次调用内先prefill再追加一个decode；旧KV逐位保留、未来槽毒化不泄漏，并有独立FP64参考与额外整段硬件对照。其周期含缓存快照、软件计数和保护检查，不是去掉诊断后的生产内核周期。

详细报告：[GELU](google_gelu_rvv_mlas/RESULTS.md)、[三算子链](google_transformer_chain/RESULTS.md)、[FFN](google_ffn/RESULTS.md)、[Attention](google_attention/RESULTS.md)。

<a id="5-21例覆盖及软件来源"></a>

## 5. 历史基础与仍保留的边界

旧21例来源/形状的逐项表保留在[10月22日快照第5节](PROGRESS-archive-20261022.md#5-21例覆盖及软件来源)，上述兼容锚点供旧链接跳转。

| 阶段 | 已完成 | 不升级成什么结论 |
|---|---|---|
| 官方/Yangg152 | 功能、整核端点、共享权重批处理比较；团队选官方 | 不再作为当前选型，不等于PPA签核 |
| TCM容量 | 六档32KiB～4MiB几何抽样、同ELF小工作集控制通过 | 4MiB几何PASS不等于完整模型/全部性能通过 |
| 驻留收益 | T12 32→128KiB同策略1.41476×；T384 1→2MiB同策略1.205785× | 固定调度/外存代理，不是实际DDR或阵列峰值 |
| VCS/Verilator | 服务器1MiB/T384结果EXACT，37619.46s vs13979.842s | 不外推所有机器/负载 |
| 默认二分类MobileNetV1 | person单图RTL PASS，Invoke190673191周期，分数[-113,113]，约18.3h | 不是两图/数据集准确率，优化整网无完成验收 |
| Conv/VME和RVV Pool | 各自短硬件probe通过；Conv片段默认91475 vs VME42713 | 2.14×的对象是默认实现，不是RVV Conv |
| 原21例LLM算子 | 4 INT8+17 FP32服务器PASS，子进程和3136.512s | 用户回传的历史证据，不是本次重新登录服务器验收 |
| SoC/PPA | 用户告知团队单NPU SoC已跑通，4核由团队负责 | 本工作没有4核、200MHz STA、工艺宏/PPA或门仿签核 |

原21例见[原结果表](google_llm_ops/RESULTS-20261022.md)。本次只直接核验了VM，未查询服务器当前进程，不把历史运行状态写成实时状态。

## 6. 身份、耗时和下一步

上述10个VM作业均复用RTL SHA `477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2` 和Verilator可执行文件SHA `827680a52a5d3107cfaa3d123af533b9e9d208acf1b44d23a880833bbb09de6c`。这里的“模型二进制”是仿真器，不是神经网络权重。ELF各不相同，见证据索引与交接表。

| 最新组 | 三例VM命令耗时（秒，含Bazel） | 合计，准备/探针另计 |
|---|---|---|
| 高精度GELU | 37.98 / 44.75 / 156.23 | 约3分59秒 |
| 三算子链 | 64.00 / 69.05 / 272.15 | 约6分45秒 |
| FFN | 54.21 / 74.91 / 161.71 | 约4分51秒 |
| Attention | 64.26 / 101.68 / 143.92 | 约5分10秒 |

墙钟含各路径和检查，不是芯片时延；内部性能用同ELF的mcycle比。以后每次仿真先给ETA、编译是否另计、依据及不确定性；超时不是ETA。新整层尚未构建，不能把这些时间直接当其完成承诺。

下一步：连接Attention残差输出与FFN输入，建立整层独立参考，保留prefill/decode KV状态、绝对RoPE位置及中间检查；先小形状和新探针，再按估时运行单例。真实权重/tokenizer、长序列、更大head_dim、BF16/INT4、AXI/DRAM、完整模型及PPA/门仿另立实验。

large的其余7例、mature的M2/4、pair的M1/2/4仍未完成，但不是默认待跑队列。只读归档现有PASS，不为补文档重跑，不改阈值/哈希或覆盖失败日志。

约定：仅在用户明确要求时集中更新全局进度、工作记录与交接；日常候选证据独立保存。
