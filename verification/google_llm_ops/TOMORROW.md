# 明日执行入口：单NPU Transformer/LLM算子测试

**最新覆盖（用户确认）：只把仿真移到服务器，VM仍可构建。** 请优先按 [server/SERVER.md](server/SERVER.md) 执行：VM运行 `export_server.sh`，仅native参考/两ELF链接/审计/导出；服务器使用不含RTL的小包和原Pool已验证模型，先单例、再串行21例。无需服务器Bazel、不重新编译大RTL，不修改旧候选。下面VM `run_all.sh` 流程保留作备选，不是当前默认执行方式；新增FP32官方完整链接与RTL仍未收到实际结果。

准备日期：2026-10-22。范围仍是**算子性能与数值验证，不是完整LLM推理/聊天**。今晚不启动远程仿真；此文件给出明天的明确执行流程。单NPU、ITCM256KiB/DTCM512KiB、Ubuntu VM、Verilator，复用已经通过INT8测试的同一个RTL模型，不换RAM，不动旧实验。

## 当前证据

| 内容 | 状态 |
|---|---|
| INT8 decode_tiny M1/K32/N32 | 真实RTL通过；标量10563、RVV263周期，40.16倍 |
| INT8 prefill_tiny M16/K32/N32 | 真实RTL通过；标量168618、RVV4110周期，41.03倍 |
| INT8 K64/N64两例 | 已准备，尚未收到实际结果 |
| 新增17例FP32算子 | 本地主机参考/目标文件编译已检查，**官方完整链接/真实RVV执行仍待明天** |
| 完整Transformer block、预训练LLM、多token生成 | 尚未实现/运行，不因本套件通过而标成完成 |

本地准备检查：新增16项工具测试通过，包含实际17例native对FP64 gold、4份RV32对象编译/反汇编、真实fixtures表几何/无动态初始化、因果mask反例、内存/数值/日志拒绝及prepare-only→续测→21例汇总的**合成控制流**检查。旧INT8的10项与旧Person/Conv/Pool/VME的82项回归通过，合计108项工具测试；不是108个RTL用例。Bash和生成BUILD/Python语法通过。未启动远程RTL，不提前验收新增算子。

## 一条命令启动全部测试（前台、串行）

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_llm_ops/run_all.sh --mode all
)
```

先检查环境/可用磁盘和旧源码身份，再执行17例主机数值参考、交叉链接、资源审计和原RTL模型缓存构建；之后**依次**运行4例INT8与17例FP32，共21个单例RTL测试。包含对已经通过的INT8两例重新确认，不将旧摘要自动冒充本次验证。每例独立从固件入口重启，标量/RVV各首次+3次steady；不会并行占满VM，也不自动切到完整模型。

终端输出 `LLM_SUITE_DIRECTORY` 后请保存该路径。详细准备日志/逐例原始日志都在那里或由其state.json记录。每开始/结束一例会有 `LLM_SUITE_CASE_START/PASS`，不每几秒刷屏。任何构建/数值/越界/故障/超时问题都会停止，保留全部证据，不降低阈值或关闭检查来继续。

请避免同时运行其他Bazel构建；脚本使用noblock锁，若旧任务正在占用会直接停下，不抢占/杀掉它。保持主机和虚拟机不自动关机/挂起。准备/构建每阶段7200秒、单测试5400秒/1000万周期（INT8 case0为200万）均为停止上限，**不是耗时承诺**；不能先断言21例会在某个小时数内完成。

## 若只想先验证构建，不运行RTL

```bash
bash verification/google_llm_ops/run_all.sh --prepare-only
```

应看到 `LLM_SUITE_BUILD_READY RTL=NOT_RUN`。这仅证明实际主机参考、官方完整链接和内存/参数审计通过，不是算子RTL通过。之后用其输出的job路径续测。

## 中断、失败后续测

先保留错误输出，不修改生成包、ELF或数学检查。若是网络/VM重启/外部中断，恢复同一环境后：

```bash
bash verification/google_llm_ops/run_all.sh \
  --resume /home/lqq/coral_tcm_capacity_8e4_v1/llm_suite.替换为实际目录
```

续测会重新验证工具身份、已通过用例的原始日志哈希及完整验收；只有完整且未改变的PASS证据才跳过。未完成用例从头重跑，**不是CPU checkpoint**。原错误目录不删除。若源码/工具/ELF身份改变，拒绝混用结果，需开新job；若为数值错误或NPU故障，请先发失败日志，不要反复重跑期待偶然PASS。

## 结果与验收

每通过一例自动更新job内 `summary.json`、`summary.md` 和 `state.json`。全部21例通过才打印：

```text
[LLM_SUITE_ALL_PASS] cases=21 full_model=NOT_RUN VME=NOT_RUN report=.../summary.md
```

若只通过部分用例，报告明确为INCOMPLETE，不能当ALL_PASS。终止后需要重新核验报告可执行：

```bash
bash verification/google_llm_ops/run_all.sh \
  --collect /home/lqq/coral_tcm_capacity_8e4_v1/llm_suite.替换为实际目录
```

回传 `summary.md`、`LLM_TX_ELF_AUDIT`、最终PASS/STOP标记。失败时回传job路径、终端尾部及对应原始test.log；不用传几十MB RTL。墙钟耗时仅表示仿真器运行速度，NPU性能比较使用mcycle，不混用。

## 覆盖表与实现来源

| 组别 | 用例数 | 实现与验证重点 |
|---|---:|---|
| INT8线性层 | 4 | 已有原样官方RVV；M1/16、K/N32/64；raw INT32精确比较 |
| FP32线性层 | 2 | 原样官方rvv_matmul.cc；decode/prefill小形状 |
| RMSNorm | 3 | 项目FP32 RVV基线；Gemma式`x*rsqrt(mean(x²)+1e-5)*(1+w)`，含37维尾部 |
| Softmax | 2 | 项目FP32混合RVV基线；稳定减max、±1000输入、37维尾部；exp仍为标量libm |
| RoPE | 2 | 项目split-half FP32 RVV；预计算sin/cos在时间窗外，非所有模型通用的旋转布局 |
| SwiGLU/GEGLU门控激活 | 2 | 项目FP32混合RVV；门函数exp/tanh仍标量，乘法向量化；不是整个FFN |
| 残差加法 | 1 | 项目FP32 RVV；独立数组，不宣称已验证所有in-place别名 |
| KV-cache追加 | 1 | 项目FP32 RVV；缓存旧前缀在窗外初始化，计时只含追加；不是完整多token生成 |
| 因果Attention | 4 | 项目小尺寸FP32 GQA，2个Q头共享1个KV头；prefill/decode及首token/未来K/V毒化对照 |

除了两种矩阵乘，新增FP32实现明确是**项目基线**，不是原官方Gemma优化内核，也不保证比标量快。Softmax/门控中exp/tanh仍标量，费用完整计入。官方现成Attention为无掩码，本套件不把它直接改名为因果Attention，而是独立实现并核对绝对query位置。

FP32固定绝对/相对容差2e-5/2e-4，拒绝NaN/Inf；两条路径对独立Python FP64计算、舍入为FP32的gold核对，且NPU前门读回全部实际输入/输出。每次调用有guard、最终有自然halt/无fault/4次调用/栈底64字节canary检查；canary不是完整栈水位。性能含实际内核调用，不含输入生成/host装载/参考检查；空边界单列不扣除。INT8与FP32、不同形状的比值不能直接互比成架构排名。

## 尚未覆盖，不能提前声称具备

- 预训练模型权重导入、tokenizer、完整模型图和采样/文本输出。
- 完整block/多层串联、真正持续增长KV cache的多步推理。
- BF16/INT4、权重解量化/重定量化、所选模型特定RoPE/归一化/激活语义。
- 外部AXI权重/大KV流式带宽、完整内存规划、DMA或多NPU。
- VME对这些LLM线性层的速度、MHz/STA、面积功耗或真实tokens/s。

本套件完成后先看正确性与周期瓶颈，再选一个小型模型落实上述模型特定工作；不要把单算子验证等同于已跑通LLM。
