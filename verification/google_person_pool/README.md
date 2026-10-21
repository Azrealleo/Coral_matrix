# 未优化算子第一步：RVV AveragePool 独立候选

**2026-10-21最新实际进度：** VM独立包已导出，归档SHA `7c8e0fe5121c0aeb37d9e8a54983dd7fe64603bf5de964b718aac4cd4b3076eb`。服务器`pool_7c8e0fe5/..._verilator_runtime/runs/probe.46bl5uqr`实际RVV Pool短测8组/659项/0错误/62向量块/签名642806987通过，256826周期自然halt、无fault、canary完好，执行85.614秒、总97.463秒；不是整网推理。默认参考完整模型的单有人图也已实际通过（Invoke190673191周期）。**当前下一步是[合并版完整模型校验](MODEL.md)**：包外新入口只读复用已编译模型，不改包、不重编；先validate有人图再决定fast/无人图。新入口7项本地合成检查通过；优化整网服务器实际运行尚未回传。以下导出/短测章节保留为复现流程。

2026-10-21。用户要求 Depthwise 暂时不要改动、使用官方实现，先处理没有现成优化的其他算子。本轮只新增 AveragePool 优化；不修改 Depthwise 源码，也不切换它的注册方式。当前仍是此前v1固件采用的官方默认 `tflite::Register_DEPTHWISE_CONV_2D_INT8()`，**不是宣称已启用官方RVV Depthwise**。

## 实际模型与优先级

固定原模型只有一个 AveragePool：`[1,3,3,256] -> [1,1,1,256]`，3×3、stride2、VALID、无融合激活。输入/输出 scale 都是0.01860933005809784、zero_point 都是-128。源码检查表明当前默认实现按通道反复计算窗口边界及循环相加，可沿连续NHWC通道向量化。

Softmax只有2个输出，Reshape只处理2个INT8元素，因此本轮不重写它们，也不声称改一个Pool就会让整网显著加速。卷积/Depthwise及量化初始化仍可能是主要开销，需周期实测。

| 部分 | 此候选处理 |
|---|---|
| 14个1×1 Conv | 原VME v1源码逐字保留 |
| 14个Depthwise | 官方默认注册不变，不新增自定义实现 |
| 1个AveragePool | 新增显式RVV候选 |
| Reshape / Softmax | 默认实现不变 |
| 模型、权重、RTL、RAM配置 | 不变，ITCM256KiB / DTCM512KiB |

## AveragePool 做了什么

- 窗口边界与有效样本数每个空间输出只计算一次，而不是每个通道重复。
- RVV沿通道连续加载INT8，符号扩展并用INT32向量累加；支持通道尾块，排除窗口外padding样本。
- 使用真实有符号整数向量除法 `vdiv.vx`，精确保留固定TFLM的正负数舍入：正和加count/2、非正和减count/2，再向零截断除法；不改为浮点近似、右移或ties-to-even。
- 按原激活上下界截断；沿用官方PoolingPrepare检查量化参数。输入/输出量化一致时不额外减zero_point，保持原参考内核语义。
- 累加数据只在向量寄存器中，无完整输出大小的INT32缓冲，无每次Invoke动态堆分配。校验版另外在arena申请输出INT8字节数的可复用scratch，本模型为256字节。
- 不支持的类型/几何显式回退并记录计数；固定模型固件要求pool_calls=1、fallbacks=0、vector_blocks>0、mismatches=0，校验版还要求validated=1，才允许完成。

`pool_core.h`共享窗口调度和独立标量模拟；`pool_rvv.h`是真实RVV backend，不把主机模拟计数当硬件向量执行。校验版执行原TFLM AveragePool并逐字节比较；测速版不重复reference计算，二者ELF和身份分开。

## 已实际完成的本地检查

- MinGW GCC6.2严格编译执行：2160组窗口/步长/SAME与VALID/批次/通道尾块/激活范围，比较1291923个输出元素；count1..49全部可能INT8求和范围的舍入测试通过，含负数和半整数边界、溢出/空窗口拒绝、输出guard。
- 本地玄铁GCC14.3、`rv32imf_zve32f_zicsr/ilp32`真实编译 `pool_compile_test.cc`；反汇编确认 `vle8.v`、`vsext.vf4`、`vadd`、`vmerge`、`vdiv.vx`、`vmax/vmin`、`vse8.v`。这是目标文件编译，不是固定官方工具链完整链接或RVV硬件执行。
- 7项新增工具测试通过：Depthwise/Softmax注册保持、父候选不覆盖、硬件/主机模式区分、模式化符号审计、路径限制等；原VME工具18项与默认路径34项回归亦全部通过。新脚本语法检查通过。
- 用实际原模型与样本生成17份候选文件，模型源码与父候选逐字相同。

**2026-10-21用户实际回传更新**：`person_pool_v1.0u8RTz` 的两项主机测试、两份完整交叉链接和资源审计均PASS，最终为 `[PERSON_POOL_HOST_AND_LINK_PASS] ... NPU_RTL=NOT_RUN`。包括固定TFLM池化差分，以及原两图每图14 Conv+1 Pool的逐字节对照；主机仍使用模拟矩阵/向量后端，不证明实际RVV指令正确。资源如下：

| ELF | SHA256 | ITCM占用字节 | DTCM静态字节 | 堆余量字节 |
|---|---|---:|---:|---:|
| validate | `8137e2bf8777f5e0976a49887302724c64f27d491c886f14ec673d535eac0951` | 143296 | 483776 | 24128 |
| fast | `81f596bd9eb0fa94ef3fcdfb0cb33719e5e00cad949207b7600b91f7481253f8` | 142112 | 483760 | 24144 |

ITCM256KiB/DTCM512KiB、模型/父VME候选/Depthwise均保持不变。**真实RVV池化、VME+Pool整网RTL及性能仍待执行**。原VME短probe已在服务器8组/840项/0错误通过，它不是此池化后端的硬件证据。

## Ubuntu VM 原生测试与链接（已通过，保留复现命令）

新目录为 `tests/cocotb/person_detect_vme_pool_v1`，单独manifest；原 `person_detect_vme_v1` 和已导出的 `coral_person_vme_i256_d512_v1` 包不改。旧默认版/短VME probe可在服务器继续运行，本轮不操作它们。

待VM当前其他Bazel任务结束后执行；锁忙即退出，不杀进程：

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_person_pool/build.sh
)
```

脚本先用固定TFLM参考池化核做native差分，再跑原两张图片：14个Conv加1个Pool每图逐字节比较，共30层，最终输出仍须有人[-113,113]、无人[57,-57]。主机部分以C++模拟VME和RVV，不是硬件。

之后交叉编译validate/fast两份真实VME+RVV固件，审计原始模型、256/512KiB段界及两组计数器符号。结果在新的 `person_pool_v1.*`。成功标记 `[PERSON_POOL_HOST_AND_LINK_PASS] ... NPU_RTL=NOT_RUN`。

不需要为了导出重新跑本节全部构建；使用上面的实际结果目录。不要将新ELF替换进旧不可变包。当前没有测得池化或整网加速倍数。

## 当前下一步：独立导出，先验证真实RVV Pool

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_person_pool/export.sh \
  "$HOME/coral_tcm_capacity_8e4_v1/person_pool_v1.0u8RTz" \
  "$HOME/coral_tcm_capacity_8e4_v1/person_vme_export.F6GOKR/coral_person_vme_i256_d512_v1"
)
```

输出 `PERSON_POOL_BUNDLE_ARCHIVE` / `PERSON_POOL_BUNDLE_SHA256`。脚本严格验证实际主机日志、资源报告和候选manifest，复制旧VME包的原RTL/DPI/fixture/模型/输入，只新链接一个短RVV池化probe；已测validate/fast ELF只复制，不改写，不运行仿真。新目录 `person_pool_probe_v1` / `person_pool_export.*`，父候选、旧包和运行任务不变。

probe覆盖8组/659个INT8输出，包括真实模型3×3×256、通道尾块、padding、batch、负数与正数半整数舍入、激活截断和输出guard；预期签名642806987。沿用诊断字段 `commands=62`，**此处表示向量循环块数，不是矩阵指令数或硬件退休数**。原始标量参考独立计算窗口与舍入，实际RVV分支使用与候选逐字相同的pool_core.h/pool_rvv.h。该探针没有TFLM初始化，不是整网推理。

本地新增5项合成导出/完整性/拒绝错误结果/父文件防覆盖测试通过；合计12项Pool、18项原VME、34项默认路径回归通过。MinGW实际执行新probe为8/659/62/签名匹配；本地玄铁GCC14.3实际编译RVV分支并见vdiv/vsext等，仍不是官方完整链接或RTL运行证据。实际VM导出/服务器Pool probe尚未执行。

服务器操作见 [SERVER.md](SERVER.md)。先通过短RVV检查再准备同包两图整网验证；当前短probe入口不提供infer命令，不能将其PASS当作整网通过。

固定来源：NPU `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`；TFLM `b75c6ff4e2270047f2b48fa01f833c8101c31f43`。舍入依据该版本 `tensorflow/lite/kernels/internal/reference/integer_ops/pooling.h`；注册与量化检查依据 `micro/kernels/pooling.cc` / `pooling_common.cc`。
