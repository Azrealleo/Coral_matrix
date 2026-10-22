# 先测Conv算子：默认TFLM vs 当前VME实现

**2026-10-22范围覆盖：** Conv case0真实2.14162倍结果已完成，VME对RVV比较因适用形状不重叠尚无结果。用户已转向LLM算子，本文下方导出/执行命令保留为复现，不是当前任务，不重复导出或启动旧长队列。最新见[进度快照](../PROGRESS-current.md)。

## 2026-10-22 最新断点（优先于下方历史说明）

服务器case0已实际通过：默认TFLM每次91475周期，VME每次42713周期，首次及后三次均一致；默认/VME=2.141620，1024项输出全等、0fallback/0mismatch。它不是VME对RVV的加速比，也不是整层/整网速度。用户随后要求VME对RVV，源码核对发现固定官方RVV Conv优化分支只针对4×4，而现有VME候选只支持1×1，没有共同优化形状。直接换注册会回退，不能标成RVV加速测试。详细证据、实际run路径及可选后续见[RVV比较适用性核对](RVV-COMPARISON.md)。尚无新增RVV Conv实现或NPU运行；下方“尚无周期/加速比、等待导出”等为此前阶段记录。

**最新实际进度：** VM `person_conv_v1.nTbcvy` 已完成固定TFLM reference vs emulated VME主机测试和真实完整链接/审计，最终`PERSON_CONV_HOST_AND_LINK_PASS full_model=NOT_RUN NPU_RTL=NOT_RUN`。ELF SHA `b94e1da3b4f7f2693727395073e65f172344f15454bd01a7b7bb8c2832f259b2`，ITCM占用113536、DTCM静态265584、heap242320字节，保持256/512KiB。**尚无NPU周期或加速比**。当前只需导出这个小固件包，不用再跑下方build.sh。

## 当前下一步：只导出小固件，不带RTL

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_person_conv/export.sh \
  "$HOME/coral_tcm_capacity_8e4_v1/person_conv_v1.nTbcvy"
)
```

输出PERSON_CONV_PACKET_ARCHIVE/SHA256/BYTES后回传。严格核验已测源码manifest、ELF/report、五例native签名，并从ELF的真实RV32数据表核对每例派生模型与输入的地址/长度/哈希。只复制已测ELF/证据/工具，原ELF不变，不调用Bazel、不运行仿真。包内不含RTL或完整模型权重文件，服务器复用已通过Pool短测的原RTL编译模型，不需要重新生成/传输/编译大RTL。

新增服务器入口只允许选择一个case，默认0：M16/K8/N16、每次2048MAC，第一调用和后三个steady分别记录。原包、producer构建身份/环境/配方/二进制、同build的Pool原始短测证据都要重新核验，前门读回小模型/输入，再加载case selector；持原state锁，结果写到新小包同级_runtime，不覆盖原current_build。若条件不符就停止，不自动重编或修改校验值。

服务器步骤见[SERVER.md](SERVER.md)。默认2百万周期/1800秒仅是停止上限，不是预计耗时；用例完成可提前结束。实际结果必须有PERSON_CONV_CYCLE_COMPARISON及PERSON_CONV_RTL_PASS，才能回答加速多少；大于1才表示VME更快，小于1是有效的变慢结果，不为得到加速而删开销。软件矩阵发射数应为8（4次×2条），非退休计数。

本地新增4项合成小包导出/完整性/ELF数据布局/周期验收检查，连同此前Conv检查11项通过；旧Pool19/VME18/默认34项回归通过。另用本地玄铁GCC14.3实际编译生成数据的RV32目标文件，确认kConvCases大小180字节、无动态初始化，支持ELF布局解析；不是服务器实际ELF或RTL执行。小包实际导出和NPU周期仍待用户执行。

2026-10-21。用户要求暂缓完整模型长任务，先回答“Conv矩阵优化究竟提速多少”。本目录是新的独立单算子实验，**不执行上一轮run_model.sh，不启动完整MobileNet推理**，不修改原模型、VME/Pool候选或现有服务器包。当前尚无实测Conv加速倍数。

## 测什么

源为原Person模型SHA `808cfdfc0cf3a6fa6f6fa26bfa379ea97c16d5db7334637766e39c3408502e9d`。从它提取5个1×1卷积的原始权重、bias、输入/输出/逐通道量化参数、激活及其他Conv选项，构造只有一个Conv的**派生诊断模型**。只减少空间位置M，改为[1,1,M,K]到[1,1,M,N]，不是原完整预训练模型，也不是完整原层的速度。

输入是固定种子137+原operator index生成的有符号INT8数据，不是已捕获的有人图中间特征。两条路径使用完全相同的输入和派生模型；常量、输入、派生模型及来源均有SHA记录。

| id | 原operator index | 名称 | M | K/Cin | N/Cout | 有效MAC/次 |
|---:|---:|---|---:|---:|---:|---:|
| 0 | 2 | op2_m16_k8_n16 | 16 | 8 | 16 | 2048 |
| 1 | 8 | op8_m16_k32_n64 | 16 | 32 | 64 | 32768 |
| 2 | 24 | op24_m9_k128_n256 | 9 | 128 | 256 | 294912 |
| 3 | 26 | op26_m1_k256_n256 | 1 | 256 | 256 | 65536 |
| 4 | 28 | op28_m1_k256_n2 | 1 | 256 | 2 | 512 |

其中原op2有2304个空间位置，本实验只取16；op26原9个位置只取1。op24及op28保留原空间位置数（布局展平）。首轮服务器**只运行id0**，小数据/小权重先验证计时链路，之后再决定其他情况，不自动排队所有用例。

## 周期口径

- 同一个ELF、同一个原NPU RTL、ITCM256KiB/DTCM512KiB；两个MicroInterpreter分别只注册默认`Register_CONV_2D_INT8()`和现有`person_vme::RegisterPointwise()`。
- 新源码和现有VME自定义内核均-O2、禁止自动向量化/LTO，原TFLM依赖使用同一固定构建路线；不声称所有依赖库的逐文件编译选项因此都被重写，亦不另行启用官方手工RVV Conv。
- 分配arena、ConvPrepare/量化参数准备、输入装载在计时之外。每个时间窗口内只执行一次**单算子Interpreter.Invoke**，含框架分派及实际内核，不是纯MAC、也不是整个模型。
- VME时间包含其本来每次调用所做的权重/输入打包、零点bias修正、tile搬入/矩阵指令/搬出、TFLM逐通道重定量化、激活和写回；原VME源码逐字复制，不为测试删除这些开销或软件计数。
- 关闭候选内部reference校验（PD_VME_VALIDATE=0）。默认与VME各自计时后才逐字节比较输出，不把参考运行藏进VME窗口。
- 第0次记录首次调用，随后3次为steady样本；交替ref→VME、VME→ref顺序。首次不冒充稳态，使用带memory clobber的fence+mcycle边界，并单独报告空边界成本，不静默扣除。
- 两条路径所有输出一致、4次VME调用/0fallback/0mismatch/0内部校验、真实矩阵发射非零且非host emulator才允许硬件PASS。发射计数仍是软件计数，不是独立退休观测。
- 将来报告`ref周期/VME周期`以及逐次周期，不先许诺一定加速。窄输出/小M及打包开销可能让某些形状收益小或更慢。片段加速不能直接外推整网或硬件MHz。

## 当前实际验证与边界

- 本地使用原资产检查五份派生模型：恰好一个Conv，常量、全部量化字段和Conv选项逐项匹配来源；输入种子和有符号数据范围正确。
- 本地LiteRT BUILTIN_REF实际运行5份派生模型，输出形状/INT8正确，重复结果一致。这不是固定TFLM差分、更不是VME硬件测速。
- 7项新工具检查通过：来源/裁剪、原常量/量化、主机参考、独立安装/拒绝覆盖、5用例native证据、ELF数据段选择器与诊断大小、计时边界；脚本语法检查通过。
- **尚未执行**：VM固定TFLM原生reference与VME emulator五用例差分、官方完整交叉链接/资源审计、服务器实际周期及任何加速倍数。主机时间不拿来估算NPU速度。

## Ubuntu VM主机验证和固件链接（已通过，保留复现命令）

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_person_conv/build.sh
)
```

生成器首次在`$HOME/coral_tcm_capacity_8e4_v1/person_conv_generator_deps_v1`独立目录安装flatbuffers25.12.19/tflite2.18.0，不升级/覆盖Conda环境包。原资产不变，新Bazel包`tests/cocotb/person_conv_bench_v1`及单独manifest，不改原VME/Pool安装。先native测试5例并检查原TFLM与emulated VME输出，再只链接一个带5种可选case的固件、审计256/512KiB地址段及case selector必须在非零.data以免被CRT清零。结果新目录person_conv_v1.*。

成功应有5行`PERSON_CONV_HOST_CASE`、一个`PERSON_CONV_HOST_PASS`、`PERSON_CONV_ELF_AUDIT`和最终`PERSON_CONV_HOST_AND_LINK_PASS full_model=NOT_RUN NPU_RTL=NOT_RUN`。native结果包括每例输出签名，以便下一阶段硬件核对。

回传这些结果后再封装小固件与计数读取入口，在服务器**只读复用已有原RTL编译模型**跑id0；不在本轮自动启动RTL、不重新导出大RTL包、不运行完整模型。旧默认单图190673191周期是整网基线，不与本片段周期直接相除。
