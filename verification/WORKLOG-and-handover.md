# CoralNPU 选型、验证、性能比较与 RTL 交接全程工作记录

初版日期：2026-10-04；本次更新：2026-10-22（香港时间）。对象：接替 NPU 软件/RTL验证工作的同学、SoC 集成人员、综合及验证人员。

本记录汇总从两套工程下载、跨平台同步、网络与工具环境搭建，到矩阵功能测试、整核性能比较、团队候选仓库和 RTL 综合交付的工作。目标是让接手人不依赖聊天上下文也能继续。它不是流片签核报告，也不把未执行的工作写成已完成。

初版整理时工具基线为`e3046dc`，10月19日核对到`c0b4b76098a88d5bace3c3fbdcef318c10e924f7`；本次结果整理基于`8c99fde`及用户回传的服务器21例整套控制台。工具commit不代替硬件源码、RTL、ELF或归档哈希。本次仅记录/分析结果，不修改封存包或启动远程任务。

**当前主线：单NPU Transformer/LLM算子微基准，ITCM256KiB/DTCM512KiB，VM只构建导出、服务器Verilator仿真。** 用户已回传完整21例真实RTL PASS（4 INT8+17 FP32），job `operators.cgtja4_x`；下一步只读回收报告/原始证据和实际墙钟，不重复运行整套。完整LLM/模型权重/tokenizer/多token仍未验证。团队已选官方，默认Person单图及Conv片段完成，优化整网/旧容量扫描暂停。接手先读[进度](PROGRESS-current.md)、[交接](HANDOFF-current.md)、[21例结果](google_llm_ops/RESULTS-20261022.md)及第29.5节；原交接完整保留为历史附件。

本文按阶段保留曾经的“当前/下一步/未完成”，第1～28节的这类说法均按当时语境理解；最新进度以上述入口和第29节为准。不能据旧段落自动恢复TCM扫描、默认模型长任务或重跑已完成pilot。用户报告团队SoC单NPU集成通过、后续4核，不等于本人已复跑SoC/完成PPA门仿。

上一阶段最新回传：Ubuntu1/2MiB T384配对PASS，同prefix策略少17.07%周期；服务器VCS1MiB/T384、2MiB/T12均PASS。服务器独立Verilator1MiB T12/T384现均完整PASS并精确匹配VCS，429.077/13979.842秒，复用了原模型。首次trace失败保留；2/4MiB T768尚未完成，服务器VCS2MiB/T384最终状态仍待回传。

### 目录

- [1. 早期目标与阶段结论](#section-1)
- [2. 证据等级](#section-2)
- [3. 仓库、版本、跨平台目录](#section-3)
- [4. 时间线](#section-4)
- [5. 三台机器的环境](#section-5)
- [6. 网络代理与SSH](#section-6)
- [7. 代码阅读入口](#section-7)
- [8. 功能测试与已知失败](#section-8)
- [9. 性能测量口径](#section-9)
- [10. 完整性能结果表](#section-10)
- [11. 适用情况与选型态度](#section-11)
- [12. 报错与修复索引](#section-12)
- [13. 三份RTL包的身份](#section-13)
- [14. RAM、AXI、启动事实](#section-14)
- [15. 待办和团队决策](#section-15)
- [16. 可执行命令](#section-16)
- [17. 文档、脚本、日志与未提交材料](#section-17)
- [18. Git提交索引](#section-18)
- [19. 交接验收清单](#section-19)
- [20. 10月4日之后的工作与范围更新](#section-20)
- [21. 新官方基线、TCM地址图与实验设计](#section-21)
- [22. 六档容量、计算控制和实际工作集结果](#section-22)
- [23. 独立VCS/Verilator、不可变包及排错经过](#section-23)
- [24. 仿真速度、性能分析与运行可靠性](#section-24)
- [25. ITCM讨论及暂停边界](#section-25)
- [26. 当前接手步骤、证据缺口与新增提交索引](#section-26)
- [27. 面积约束后转向完整模型（历史）](#section-27)
- [28. Person模型、优化算子及LLM准备时间线](#section-28)
- [29. 当前LLM服务器pilot、21例状态与交接更新](#section-29)

<a id="section-1"></a>

## 1. 早期目标与阶段结论（当前接手以第29节为准）

### 1.1 项目目标及已经确定的方向

团队处于 SoC 前端设计早期，准备流片。NPU 工作最初是比较官方 CoralNPU 与 Yangg152 分支的矩阵单元，判断是否能跑通、性能如何、后续需要什么验证。

后来已经明确：**最终要集成整个 CoralNPU 核到 SoC，不是只拿一个独立矩阵阵列。** 因此选型不能只看 PE 的乘加周期，还要看整核指令、装载、结果读回、软件支持、RAM、AXI 和 SoC 集成成本。

2026-10-04时官方工程作为候选版保存并交付RTL。之后团队已明确选择官方版本；Yangg152目录及失败记录保留为历史，不再作为当前待选方案。选型决定不等于所有功能、模型、PPA或流片签核已经完成。

已经明确或暂定的事项：

- Windows 修改代码，通过 Git 同步到 Linux，Linux 运行验证。
- Ubuntu用于Bazel/Chisel及单官方核Verilator/cocotb；CentOS7的独立Verilator1MiB T12/T384均已正式验收，读取同一不可变包并保留原VCS状态，其他容量的本后端验证仍待进行。
- 本轮性能比较以 signed INT8 输入、INT32 累加/输出为主。真实 uint8 需求暂缓，不能据此说 uint8 问题已经解决。
- 目标频率暂定 200 MHz，后续用 DC/实际工艺库评估；目前没有频率达标证据。
- 用户报告团队已集成并跑通单NPU SoC，后续4核暂不在本人当前任务内。DC/网表/库模型/SDF/门仿没有新增完成证据，继续列为待团队交接。
- 当前优先级：单NPU、DTCM扩到2/4MiB的收益与限制；ITCM容量实验工具已建立但用户要求暂缓，先继续DTCM。

### 1.2 当前结论一页表

| 项目 | 截至2026-10-19的状态 | 结论边界 |
| --- | --- | --- |
| 早期官方整核RTL生成 | `870993f7`基线已成功 | `VmeCoreMiniAxi`、外取指开启、ITCM8KiB/DTCM32KiB；新容量实验另锁`8e4df09b` |
| 官方原有 VME 基础回归 | 用户报告 12 个目标通过 | 不是仓库所有测试或所有 ISA 模式都已验证 |
| 两套 signed INT8 正负数压力测试 | 同向量 32 个用例均通过，每套 8192 元素 | 已覆盖选定四符号组合、极值、随机模式；不是穷尽证明 |
| 官方 K 边界 | Tk=1 路径，21 个 K 值通过 | 不是逐个验证全部 1～256，也不是优化尾部模式的性能测试 |
| Yangg152 K 边界 | 43 次运行：24 PASS / 19 FAIL | 18 次非 16 对齐 K>16 算术失败，另一次输出停顿测试失败；未修复 |
| Yangg152 true uint8 | 明确失败 | `cfg_signed` 未驱动 unsigned 运算路径；未修复 |
| 非满 M/N、非对齐 K | 补零驱动的模型形状测试通过 | 补零是软件适配，不代表原生任意形状或没有效率损失 |
| K>256 和多输出 tile | 2 个逻辑形状、5 个输出 tile 的分块/分段测试通过 | 不是完整模型，也不是两边同口径速度测试 |
| 同端点整核 7 用例、22 用例扫描 | 用户返回完整比较结果 | 官方 Tk=4 在这些任务中周期更少；不同核和驱动，不是纯阵列/PPA 结论 |
| 单次启动共享 B 的 9 组批处理 | 双方通过并返回比较 | 两边 B 复用策略不同，官方每 tile 重载 B，fork 复用权重 SRAM |
| fork 权重每 tile 重载对照 | 历史代码保留，未收到执行结果 | 官方已定型，不再列为当前下一步 |
| 官方选型及SoC | 团队已选官方；用户报告单NPU SoC集成测试通过 | 本人当前未审计/重跑团队SoC全流程，4核不是本轮范围 |
| 10月4日8/32KiB综合交付 | docs_v2原包身份及262文件核对记录保留 | 旧`870993f7`基线，不等于新的TCM容量实验或当前SoC RTL |
| 新官方DTCM容量几何 | 32/128/512/1024/2048/4096KiB六档Ubuntu PASS | 选定AXI位置和mask，不是全地址March/MBIST |
| 同ELF小工作集控制 | 六档PASS且完整日志配对检查通过 | K16/64/256均414/702/1854周期；不能推出大模型扩容无收益 |
| T12权重驻留 | 32/128KiB及1MiB在Ubuntu PASS；1/2MiB在VCS PASS | 48KiB权重在128KiB已能全部驻留，不足以选2/4MiB |
| T384跨1/2MiB | Ubuntu两档PASS，比较器PASS | 同prefix策略1MiB→2MiB少17.07%周期；固定调度合成负载，不是模型最优结果 |
| 服务器VCS大测试 | 1MiB/T384完整PASS | 2MiB/T384仅收到启动信息，当前状态需查日志，不声称仍在跑或已通过 |
| 1/2/4MiB独立包 | 三档均已在Ubuntu导出并核对RTL/ELF字节 | 1/2MiB已转服务器；4MiB未收到传输/构建/运行证据 |
| 服务器独立Verilator | 1MiB/T12和T384均完整PASS、VCS参考EXACT；429.077/13979.842秒 | 复用原模型，首次失败另存；2/4MiB后端验证与T768仍待进行 |
| ITCM扩容 | 8～128KiB前门几何工具已实现、本地14项检查PASS，当前暂停 | 没有本轮RTL执行PASS；1MiB需求需实际模型ELF/段布局决定 |
| DC、STA、LEC、门仿、完整 AI 模型 | 尚未完成 | 不得把 RTL 打包成功或功能仿真 PASS 当作这些工作的结果 |

### 1.3 最短接手路线

1. 先读[当前交接指南](HANDOFF-current.md)，核对固定`8e4df09b`基线、两个团队补丁、单核实验地址图和ITCM8KiB。
2. 保留Ubuntu实验source、Bazel缓存、三档不可变包及所有成功/失败日志；不要重新clone上游最新版本替换。
3. 按指南检查服务器2MiB/T384历史任务是否完成，收集结果；不要停掉其他人的simv。
4. 保存已通过的Server Verilator T12目录`t12_r0.fmvgge7f`、修复入口和VCS精确参考；不重复跑旧失败或重编已通过模型。
5. 保存已通过的1MiB Verilator T384及VCS精确参考，不重复该档；按指南先建立2MiB独立Verilator模型/T12，再准备2/4MiB T768，分别报告NPU周期与主机墙钟。
6. 后续准备T768的2/4MiB配对、外部延迟敏感性和实际模型/备选调度；ITCM待用户重新决定，DC/门仿待团队提供实际材料。

<a id="section-2"></a>

## 2. 记录证据等级：什么是实际核对过的

本文使用以下概念，避免把不同证据混在一起：

| 证据类型 | 含义 | 典型例子 |
| --- | --- | --- |
| 本地实物核对 | Windows 上实际存在的代码、Git 对象、压缩包、哈希、随包日志 | 262 文件交付校验、ZIP 与解包字节一致、提交历史 |
| 用户运行结果 | 用户在 Ubuntu/EDA152 执行指令，提供日志或摘要 | signed stress、K 边界、整核速度比较 |
| 源码分析 | 从实际源码解释实现机制；不是波形证明 | `cfg_signed` 未使用、activation chunk 向下取整、`result_ready` 未使用 |
| 本地验证工具自测 | Python 单元测试、向量/解析器/打包器检查、Bash 语法检查 | `check_*.py`、导出工具 11 个测试 |
| 计划/待执行 | 工具或命令已写好但没有有效执行结果 | fork 权重重载对照、DC/GLS、真实模型 dispatch 验证 |

Windows 没有实际运行本文所有 RTL 仿真。大部分 Linux 仿真由用户执行。除本次实际接收的 RTL 包内日志外，许多结果只保存了用户返回摘要，服务器完整日志与实际运行时 HEAD 仍需从对应机器收集。本文不会声称这些完整日志已经逐一独立审阅。

“本地 Python 测试通过”不等于 RTL 测试通过；“Bazel build 完成”不等于 cocotb test 通过；“仿真时间设为 1.25 ns”不等于硬件达到 800 MHz。

<a id="section-3"></a>

## 3. 仓库、版本及目录：不要混淆三个 Git 仓库

### 3.1 仓库职责

| 仓库 | 地址 | 当前用途 |
| --- | --- | --- |
| 个人比较/验证仓库 | https://github.com/Azrealleo/Coral_matrix | 两套源码并排保存，Windows/Linux 同步验证代码、脚本、工作记录 |
| 团队 SoC 仓库 | https://github.com/cheshire-coral-soc/cheshire-coral-soc | 用户后续报告单NPU已集成并跑通；本轮容量实验固定读取其中两个生成补丁，不自动跟随main |
| 团队官方候选仓库 | https://github.com/cheshire-coral-soc/coralnpu-official-candidate | 单独保存官方候选版，保留上游历史；创建时为私有，按团队主仓库私有属性处理 |

最新详细 RTL 说明及当前工作记录位于个人 `Coral_matrix` 仓库的 `verification/`，**不是自动同步到团队 SoC 主仓库**。候选仓库中历史 `codex/rtl-handoff` 分支存的是旧生产包工具链，见第 13 节，不应据分支名以为那就是当前推荐包。

fork 保留来源关系/历史，通常需要手动 fetch、合并或重放修改。**官方更新不会自动修改我们的候选源码或已交付 RTL。** 不要为了“保持最新”随意升级本轮基线。

这里解释的是Git fork/分叉的概念；团队私有候选保存上游历史，不应仅凭名称当作GitHub平台会自动维护、更新的原生fork。普通私有候选/镜像仓库与公开上游fork的可见性规则也不能混为一谈。

### 3.2 两套原始源码基线

| 工程 | 原始来源及固定提交 | 原始提交信息 |
| --- | --- | --- |
| 官方 | `google-coral/coralnpu`，`870993f7425066037f300c52237c283821e75cbb` | `Migrate VME testcases to VerilatorTestFixture`，2026-09-25 UTC |
| Yangg152 | `Yangg152/coralnpu`，`a3fb5f35aa227c6f6a46ca7374891cab37ac196e` | `V3.0.0`，2026-06-15 |

这两份不是同一个时间点的上游源码。fork 来源于官方并不表示矩阵实现、构建规则和工具版本与本轮官方快照一致。

比较仓库初始导入为 `403c4f1`，之后增加文件属性恢复、诊断测试、测试程序和 Bazel 兼容修复等。不能把当前比较仓库整体称为“完全未修改的两个上游仓库”。官方功能 RTL 没有为了测试结果被改写；Windows 大小写文件名兼容处理及测试/工具增补需单独说明。

### 3.3 三台机器的目录

| 环境 | 仓库目录 | 运行/交付目录 |
| --- | --- | --- |
| Windows | `E:\Projects\矩阵二选一` | `handoff_output/`；根目录接收原始 `.tar.gz` |
| EDA152 | `/home2/lqq/Desktop/Coral_matrix` | `/home2/lqq/Desktop/mxu_runs`，日志常显示规范路径 `/data/home2/lqq/Desktop/mxu_runs` |
| Ubuntu VM | `$HOME/桌面/Coral_matrix`，即 `/home/lqq/桌面/Coral_matrix` | 两子工程各自的 `bazel-bin/`、`bazel-testlogs/`；导出包在 `/home/lqq/` |

EDA152 上 `/home2` 对应数据盘路径，脚本使用 `pwd -P` 后可能显示 `/data/home2`。不要未经核对就认为日志路径变化代表又 clone 了一份。

Windows 本地 `.upstream-git/coralnpu-google.git`、`.upstream-git/coralnpu-Yangg152.git` 保存原始 Git 元数据，属于本地辅助材料，不是普通 clone 个人仓库后就一定会有的目录。后续可以从原始仓库重新获取，但不要依赖它们作为唯一交付来源。

### 3.4 Windows/Linux 同步曾遇到的真实问题

最初两个URL默认都会生成`coralnpu`目录；解决方式是显式取不同目录名，而不是覆盖前一个目录。最初独立检出可以这样做：

```bash
git clone https://github.com/google-coral/coralnpu.git coralnpu-google
git clone https://github.com/Yangg152/coralnpu.git coralnpu-Yangg152
```

但现阶段应clone已经整理好的个人`Coral_matrix`，它包含本轮固定快照与验证补丁。新执行上面两条会拿到上游当前状态，不等于复现本轮基线；不要把嵌套`.git`或最新上游文件直接覆盖进个人比较仓库。

最初 Linux `ls -l` 发现 wrappers 的 `clang` 是 9 字节普通文件、`driver.sh` 不可执行。原因是导入时符号链接/执行位没正确保留，不是 Linux 不支持 Windows 编辑的源码。

`a9f180e` 恢复 Git 文件模式：

- `toolchain/wrappers/clang` 是 `120000` 的链接条目，目标 `driver.sh`。
- `driver.sh` 等脚本保存为 `100755`。
- Linux 更新后实际得到 `clang -> driver.sh`、可执行 driver；用户报告工作树干净。

Windows 不必强求本地每条 symlink 都以 Linux 相同形式出现，但 Git 索引必须保持正确。不要把链接文件内容当脚本正文编辑。用 `git ls-files -s` 核对模式，不是对 wrappers 全部盲目 chmod。

官方同目录同时有 `SRAM.scala` 与 `Sram.scala`，Windows 大小写不敏感冲突。个人比较仓库将后者保存为 `SramBlock.scala`，并修改 Bazel 对应源文件条目；代码内容不是另一个 RAM 实现。团队官方候选原始历史保留上游文件名。Linux 原生文件系统适合重新生成官方 RTL。

跨平台继续使用 Git 是可行的：保持链接模式、执行位、大小写映射、文本换行设置，并在 Linux 干净检出中执行。不要把 Bazel 输出 symlink 当成源文件提交，也不要跨平台复用编译缓存。

<a id="section-4"></a>

## 4. 工作时间线与阶段成果

下表日期以 Git 提交时间、文档或用户提供的日志为依据。早期纯聊天配置操作没有单独提交，归入相应阶段，不虚构精确时刻。

| 阶段 | 时间/关键提交 | 做了什么 | 结果与后续 |
| --- | --- | --- | --- |
| 项目下载与同步 | 2026-09-26，`403c4f1` | 两套工程用不同目录名导入个人仓库 | 不再因同名 `coralnpu` 混放；Windows→Git→Linux 工作流建立 |
| 文件属性修复 | 09-26，`a9f180e` | 恢复上游执行位和链接；处理 Windows 大小写 | Linux 链接/脚本恢复，工作树干净 |
| fork 基础 VCS | 09-26，`fecb9e2` | 修复测试环境 timescale、FSDB 依赖；波形改为可选 | 初始四用例 256 输出 beats 通过 |
| unsigned 诊断 | 09-26，`2ed9808` | 加入高值真实 uint8 用例，纠正“非负 int8=uint8”误解 | true uint8 失败；保留诊断，未修 RTL |
| 官方 lane smoke 工具 | 09-26，`75a98e9` | 增加独立 ZVT integer lane 测试入口 | 工具在仓库；现有证据不足以单独记为执行 PASS |
| 新 Linux 环境 | 09-26～后续 | CentOS 新 Bazel 不兼容、Docker 不可用后，转向 Ubuntu VM + Conda | 官方 RTL 成功生成，Verilator/cocotb 回归通过 |
| fork 基础性能 | 09-29，`519ac9b` | 原 TB 只读 bind monitor，测 load/MMA/readback | K=16/64/256 MMA=19/67/259；不能和官方整核直接比 |
| 官方同向量与有符号诊断 | 09-29，`2113cf3` | signed B、Tk=1/2/3/4 与共用 golden 数据 | 用户报告诊断和共用测试通过 |
| 官方阵列观察 | 09-29，`2faf6a8` | 新模型选择性可见信号，原 RTL/程序不改 | 普通驱动开始间隔 24 周期，阵列有供应空档 |
| 稠密指令流 | 09-29，`ffb6b35`、`4f03352` | 预载复用操作数，同 tile 连续矩阵指令 | 间隔 4 周期，有限窗口 K+8，不能当完整 GEMM |
| 同向量 signed stress | 09-29～30，`4f03352`～`37b2ddb` | 正负/极值/随机，比较跨主机 hash | 每套 32 用例、8192 元素通过 |
| K 与输出停顿边界 | 09-30，`37b2ddb`～`4c60c9b` | 21 个 K，两输入节拍，单独输出 stall | 官方 21 PASS；fork 24 PASS/19 FAIL，记录而非隐藏 |
| 模型形状 tile | 09-30，`5979381` | 7 种 M/N/K，fork K 补零到 16 | 全输出检查通过；两边计时仍不同 |
| 多 tile、长 K | 09-30，`6026d2e` | M20N23K272、M1N10K528 分块/累加 | 算术可行，但不作为两套速度排名 |
| 同端点整核测试 | 09-30～10-01，`8dc4b1e`～`c79d7de` | fork 整核 ELF、Bazel 兼容、runner、异常定位、RVV 初始化 | 两套整核可比较同任务 launch→halt 周期 |
| 22 用例速度扫描 | 10-01，`42a2610` | K 边界与小 M/N 占用率 | 用户返回完整 22 行；官方 Tk=4 全部周期更少 |
| 单启动共享 B 批处理 | 10-01，`95e8415`、`b6e0792` | T=1/4/16，K=16/64/256；大缓冲移外部 BSS | 双方通过；展示复用与启动摊销影响 |
| 权重重载对照 | 10-01，`c8662a4` | 同 fork ELF 控制 B 每 tile 是否重载 | 尚无运行结果；用户随后打断转向团队候选/交付 |
| 团队候选与 RAM 说明 | 10-03～04 | 保存官方固定候选版，解释 SRAM 和容量参数 | 尚未接入 Cheshire SoC |
| 首次 prod RTL 包 | 10-04 前后 | 私有 CI 生成 prod 配置、lint、模板 | 外部取指关闭，与原仿真不同；被用户指出后纠正 |
| 导出已有仿真 RTL | 10-04，`887181e` | 不 build、不切配置，复制 Ubuntu 生成物 | 原包 SHA 匹配，262 文件校验，外部取指开启 |
| 详细综合/RAM 交接 | 10-04，`e3046dc` | 完善交接说明，doc-only 更新包，导出工具测试 | 当前推荐 docs_v2 包，RTL 字节不变；DC/GLS 待执行 |

<a id="section-5"></a>

## 5. 环境清单：哪些工具在哪台机器上

### 5.1 Windows

- 用户：`azrea`；当前工程：`E:\Projects\矩阵二选一`。
- Git 可用；本地 Python 路径 `E:\python\python.exe`。
- Clash Verge 本地代理端口 `7908`。
- VMware VMnet8 主机 IPv4：`192.168.58.1`。
- 原先代理只监听 `127.0.0.1:7908`，随后启用 LAN 访问，用户查看监听为 `:: :7908`，Ubuntu curl 实测成功。
- 本机主要承担代码修改、Git、记录整理、打包工具自测和交付包核对。
- WSL 曾尝试但启动失败 `HCS_E_HYPERV_NOT_INSTALLED`；没有通过修改系统虚拟化设置把它作为本轮执行平台。

### 5.2 实验室 EDA152

本节表格是最初环境调查。2026-10-17～19新增的Conda/VCS/Verilator环境及服务器硬件见第23～24节；“当时缺少”不代表现在仍未安装。原生Bazel的glibc问题没有通过升级系统库解决，而是导出源码包、在服务器本地编译仿真模型。

| 项目 | 实际报告值 |
| --- | --- |
| IP / 用户 | `172.27.127.152` / `lqq` |
| SSH | TCP 22，已有 sshd；3390 是远程桌面服务端口，不是 SSH |
| 用户权限 | 无管理员权限；UID 1037，组 `lqq uvvip` |
| OS / 架构 | CentOS Linux 7 / x86_64 |
| libc / GCC | glibc 2.17 / GCC 4.8.5 |
| Python / NumPy | Python 3.6.8 / NumPy 1.19.5 |
| VCS | `/opt/Synopsys/vcs/Q-2020.03-SP2-7/bin/vcs` |
| Java | 有 Verdi 自带旧 Java；不是本轮官方 Bazel 环境 |
| Docker | 只有 Docker 20.10.13 客户端；daemon/socket 不可用 |
| 当时缺少 | Bazel/Bazelisk、Verilator、Icarus、Conda/Mamba、Apptainer/Singularity 等 |
| 数据盘 | 当时报告总 8.8 T、可用约 2.4 T；不是当前实时余额 |

Bazel 8.6.0 Linux x86_64 可执行文件已下载至 `mxu_runs/tools` 并且 SHA256 校验 OK，但启动报 `GLIBC_2.25`、`CXXABI_1.3.11`、多个 `GLIBCXX` 版本缺失。这是系统运行库不兼容，下载完整不代表能运行。

不建议在共享服务器自行替换系统 glibc。Conda 可以隔离 Python/编译器等依赖，但不能保证所有新版二进制在旧宿主 glibc 上可运行。编译生成的仿真可执行程序从新 Ubuntu 搬回 CentOS 也有同类 ABI 风险；可综合 RTL 文件是文本，转交给服务器 VCS/DC 与转交 Ubuntu 二进制是不同问题。

Docker 诊断结论：`/var/run/docker.sock` 不存在；`docker version` 无法连接 daemon；`systemctl is-active docker docker.socket` 显示 unknown。`docker info --format` 的 panic 是客户端错误表现，不是容器运行成功。最终没有采用这台机器的 Docker。

### 5.3 Ubuntu VMware 虚拟机

| 项目 | 用户报告/已有日志 |
| --- | --- |
| 用户 / VM 地址 | `lqq` / 当时 `192.168.58.131`，DHCP 可能改变 |
| OS / 架构 | Ubuntu 26.04 LTS / x86_64 |
| 宿主 glibc | 2.43 |
| vCPU / 内存 | 8 核；7.2 GiB RAM；4 GiB swap |
| 空间 | 当时家目录所在盘可用约 63 GiB |
| 初始系统 Python | 3.14.4；command-not-found 的 SQLite 动态库报错 |
| Conda | Miniforge，`/home/lqq/miniforge3`，环境 `coral-matrix` |
| 环境 Python | 用户报告 3.11.16 |
| 编译器 / Java | clang 19.1.7 / OpenJDK 21.0.10-internal |
| Bazel / Verilator | 使用 Bazel 8.6.0；用户报告 Verilator 5.052 |
| 实际随包仿真日志 | Verilator 5.052、cocotb 2.0.0、Python 3.11.9 |

Bazel 可下载自己的 Python、JDK、Verilator、RISC-V 工具链。Conda Python 与仿真日志 Python 不同并不自动意味着错环境。`python` 直接跑摘要脚本所需 NumPy也不自动随 Bazel 依赖装入 Conda。

官方 `.bazelversion` 是 `8.6.0`；fork 原始 `.bazelversion` 是 `7.4.1`。本轮成功流程是 Conda 中的 `bazel`，fork 已补兼容 Bazel 8 的规则。若换成 Bazelisk，它可能按每个子项目文件选不同 Bazel；先核对 `command -v bazel` 和 `bazel version`，不要照搬旧缓存成功经验。

普通 `bazel --version` 曾报 Unknown startup option，应使用 `bazel version`。大多数命令使用 `--jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2` 限制并行；这适合当前 VM 的内存，不是全部硬件机器必须取 2。

**Ubuntu 仿真不需要 VCS：** Bazel 组织构建，Chisel/firtool 生成 SV，Verilator 把 SV 转成仿真模型，cocotb/Python 控制运行和结果检查。它是 RTL 仿真，不是只跑 Python 数学。VCS 用于 EDA152 的另一套独立单元验证。

<a id="section-6"></a>

## 6. 网络代理与 SSH：已解决的问题及可复用配置

### 6.1 EDA152：Windows 反向 SSH 代理

最初把远程桌面的 3390 误当 SSH，出现 `Connection timed out during banner exchange`。服务器后来确认 `/usr/sbin/sshd -D` 已存在，并监听 22。用户使用自己的 `lqq` 账号连接不会影响 `gzc` 的正常 SSH 会话；本轮没有重启系统 sshd 或关闭其他人的连接。

在 Windows PowerShell 打开专用终端，保持窗口运行：

```powershell
ssh -N -T -p 22 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:17908:127.0.0.1:7908 lqq@172.27.127.152
```

说明：

- `-N` 不执行远程命令；`-T` 不分配终端，所以成功后没有 shell 提示符是正常的。
- `-p 22` 指定 SSH 服务，不是远程桌面端口。
- `-R` 前半段 `127.0.0.1:17908` 是服务器上的监听；后半段 `127.0.0.1:7908` 是 Windows 上代理目的地。
- 这里两个 `127.0.0.1` 分别属于两台机器的回环地址。`17908` 可换成空闲高端口，但客户端配置要一起换。
- `ExitOnForwardFailure` 让监听失败时明确退出；keepalive/count 是建议保活参数，不保证服务器永远不留下旧会话。
- SSH 会要求密码，除非已经配置可用密钥；密码输入不回显。成功转发不等于本地代理进程一定正常。

首次连接出现主机真实性提示。历史用户提供 ED25519 指纹 `SHA256:NibqGuG1FztZIMOI1MXC6IR2An5BXPwk6wYMEr6RyXw`；接手人应通过可信团队渠道核实，不要把本记录代替管理员确认，也不要关闭 host-key 检查。

在 EDA152 的本次终端中设置与测试：

```bash
export http_proxy=http://127.0.0.1:17908
export https_proxy=http://127.0.0.1:17908
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
curl -x http://127.0.0.1:17908 -I --connect-timeout 10 --max-time 30 https://github.com
```

Git 若需要单独配置，推荐只设置当前仓库，避免改所有用户/项目：

```bash
cd /home2/lqq/Desktop/Coral_matrix
git config --local http.proxy http://127.0.0.1:17908
git config --show-origin --get-regexp '.*proxy' || true
```

`export` 只对本 shell 及子进程有效；Git local config 可以持久保存。两者都不会替代 SSH 隧道本身。Windows 专用终端关闭/休眠/断网后，要重新确认代理；不要仅凭配置仍在就认为联网有效。

### 6.2 旧隧道没有立即释放的事件

网络中断后新 Windows 终端提示 `remote port forwarding failed for listen port 17908`。服务器仍有 `127.0.0.1:17908` 监听：历史 UID 1037、socket inode 339406047；`ps` 显示旧 `sshd: lqq` PID 189931。

最初严格核对 `/proc/<pid>/fd` socket 的关闭脚本拒绝操作，因为 sshd 的 fd 目录不可读；即使同 UID，也可能因进程安全属性限制访问。随后用户核对自身 UID、PID 真实/有效 UID、会话情况，执行 `kill -TERM 189931`，确认该进程和监听消失，重新建立隧道成功。

**189931 和 inode 只用于说明历史，不是现在可以照抄执行的关闭对象。** 后续用新 `ss` / `ps` 识别自己的旧连接；若不能确认，换一个空闲远程端口并更新代理，或者找管理员。不要 `pkill sshd`、kill root 父进程或杀其他用户会话。

诊断命令：

```bash
ss -lntpe | grep -E ':(17908|17909)[[:space:]]'
ps -u "$(id -un)" -o pid,ppid,tty,etime,args | grep '[s]shd'
```

### 6.3 Ubuntu：直接使用 Windows VMware 网卡代理

Ubuntu 与 Windows 同在 VMnet8，可直接访问主机代理，不必再加 SSH。最初 Windows 代理仅监听 localhost，虚拟机不能访问；Clash Verge 开启 LAN 访问后监听变成 `::`，用户实测以下下载 HTTP=200：

```bash
curl -x http://192.168.58.1:7908 -fL --connect-timeout 10 --max-time 90 \
  -o /dev/null -w 'ninja HTTP=%{http_code}\n' \
  https://github.com/ninja-build/ninja/releases/download/v1.11.0/ninja-linux.zip
```

本终端的可复用配置：

```bash
export http_proxy=http://192.168.58.1:7908
export https_proxy=http://192.168.58.1:7908
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
export no_proxy=localhost,127.0.0.1,::1
export NO_PROXY="$no_proxy"
```

接手时先检查 `hostname -I`、Windows VMnet8 IP、7908 监听和 curl。若防火墙需放行，限制在 VMware 网络/必要来源，不把代理随意公开到其他网络。

曾出现 GitHub 首页 HTTP=200、Ninja 首跳 HTTP=302，但 `curl -L` 下载超时。原因定位到下载重定向后的网络路径，不是 RTL。不要用“网页能打开”判断所有 Bazel 依赖都可下载。必要时给 Bazel JVM 显式代理，启动参数必须放在 `test` 之前：

```bash
# 备用明确配置；已有正常代理环境时不必重复加。
bazel --host_jvm_args=-Dhttp.proxyHost=192.168.58.1 \
      --host_jvm_args=-Dhttp.proxyPort=7908 \
      --host_jvm_args=-Dhttps.proxyHost=192.168.58.1 \
      --host_jvm_args=-Dhttps.proxyPort=7908 \
      test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 --test_output=errors \
      //tests/cocotb/vme_test:vme_test_vme_matmul_int8_test
```

<a id="section-7"></a>

## 7. 代码阅读与实现差异：从哪里继续看

### 7.1 官方矩阵扩展，不在独立 `hdl/mxu` 目录

官方 VME/ZVT 主要 RTL 入口：

```text
coralnpu-google/hdl/verilog/rvv/design/Zvt/
  zvt.sv                  顶层连接
  zvt_ctrl.sv             命令/控制
  zvt_pe_array.sv         PE 阵列
  zvt_pe_block.sv         阵列分块
  zvt_pe_mulbulk*.sv      乘法路径，整数/浮点 lane
  zvt_pe_adder*.sv        加法路径，整数/浮点 lane
  zvt_mt.sv、zvt_mt_reg.sv tile 存储/寄存器
  zvt_acc.sv              累加相关
```

整核生成与参数：`hdl/chisel/src/coralnpu/BUILD`、`Parameters.scala`、`CoreAxi.scala`、`TCM.scala`、`SramNx128.scala`、`SramBlock.scala`；低层 RAM：`hdl/verilog/Sram.v`。

已有回归与新增验证位于 `tests/cocotb/vme_test/`。软件卷积相关在 `sw/opt/litert-micro/conv.cc`、`conv.h` 等。源码配置/注释只能作为阅读线索，必须与当前执行结果核对；曾有旧测试注释说 altfmt/Tk 受限，与实际已跑 signed/Tk=4 结果不一致。

### 7.2 Yangg152 独立 MXU 与整核副本

```text
coralnpu-Yangg152/hdl/mxu/
  rvv_backend_mxu_unit.sv  FSM、输入缓冲、16×16 PE、结果读出
  rvv_backend_mxu_pe.sv    signed 8×8 乘法 + 32-bit 累加，两级
  rvv_backend_mxu_wrapper.sv 与 RVV uop/写回连接
  Sram_256x128.v           权重缓冲行为模型
  mxu_tb.v                原始四用例及可选 uint8 诊断
  golden.py               原始 NumPy 向量/HEX 生成

coralnpu-Yangg152/hdl/verilog/rvv/design/
  同名 MXU unit/PE/wrapper/SRAM 整核使用副本
```

已检查独立与整核 unit 副本相同。后续若获授权修 RTL，必须明确两个路径的真实 build 依赖，避免只改独立测试副本而整核仍用旧实现。

unit 操作类型：MCFG=0、MLOAD_W=1、MLOAD_A=2、MZERO=3、MMA=4、MSTORE=5、MFENCE=6。`cfg_Tk=0` 表示 256，不是 K=0。当前 PE 有 256 个累加位置，每次 K 步做一个 16×16 外积累加。

矩阵内部存储与整核 TCM 不应混淆：fork 权重缓冲 `256×128 bit=4 KiB`，activation 数组 `16×256×8 bit=4 KiB`，256 个 32-bit accumulator 共 1 KiB。后两者是 RTL 状态数组/寄存器描述，不代表已经映射成对应工艺 SRAM 宏。

### 7.3 模型软件路线尚未验证

fork 专用软件入口为 `sw/opt/litert-micro/mxu.cc`、`mxu.h`，新增整核基准程序只复用其指令编码，不运行 TFLM 全模型。

曾检查到普通 MobileNet 示例注册 `Register_CONV_2D`，fork PoseNet 示例显式注册 `Register_MXU_CONV_2D`。所以“模型推理能跑”不证明矩阵单元实际参与。需要逐层确认 MXU/RVV/标量 fallback 路径。

源码分析还提出 fork 非 1×1 MXU 卷积路径的边界风险：固定 16-channel 缓冲被按 `output_depth` 索引，没有对应 `output_depth<=16` 的 dispatch 保证。**这是待验证的软件问题，不是已经复现的 RTL 故障。** 真模型测试前需检查路由、索引范围、分块、量化和输出精度。

<a id="section-8"></a>

## 8. 功能验证工作与已知限制

### 8.1 fork 最初 VCS smoke

用户在独立运行目录生成 `cases/`，用 VCS 编译 SRAM、PE、unit、TB。先后遇到：

1. TB 有 timescale、前面模块没有，VCS 报 `Illegal timescale for module`。使用 `-timescale=1ns/1ps` 统一默认。
2. `$fsdbDumpfile/$fsdbDumpvars/$fsdbDumpMDA` 未定义。环境没有加载 Verdi PLI，改成 `MXU_ENABLE_FSDB` 条件开启，默认不 dump；不把这当 DUT 算术修复。
3. 编译失败时 `simv` 不存在，所以 `./simv` 报 No such file。必须编译成功再运行，不能拿旧 simv 的结果冒充新构建。

四组初始用例：K=16、64、256，另一个 K=16 的非负 INT8。每组 64 个 128-bit 输出 beat，每 beat 4 个 INT32，整矩阵 256 元素。最终 `PASS:256 FAIL:0` 是四组总计 **256 个 beat、1024 个 INT32 元素**，不是 256 个不同矩阵用例。

### 8.2 true unsigned 失败：没有被修复或消失

原第四组名字含 unsigned，但输入限制在 signed INT8 也能表达的非负范围，不足以证明 128～255 的 uint8 运算。增加可选 `MXU_TEST_TRUE_UNSIGNED` 第五组：`cfg_signed=0`，高值 uint8 输入。

用户返回：0/64 输出 beat 通过、64 失败；典型每个 INT32 实际 `0xfffff580`（-2688），期望 `0x00002580`（9600）。

源码根因依据：unit 声明 `cfg_signed`，wrapper 从 rs1 bit8 传入，但 unit 不使用它改变数据解释；abuf/weight/act 都 signed 8 bit，PE 乘积 signed 16 bit，再符号扩展至 32 bit累加。

本轮决定暂不做 uint8 性能比较。结论只能是 **fork 已测 signed INT8 功能成立，true uint8 当前失败**，不是“用户不需要所以支持没有问题”。真实模型若有 uint8、非零 zero_point，需要选择转换/补偿/新实现并重新验证，不能把符号位重新解释当成等价转换。

### 8.3 官方原有回归

用户先成功生成约 11 MiB 的 `VmeCoreMiniAxi.sv`；构建耗时 837.113 s（1359 actions）。之后 int8 首轮构建/测试 1106.830 s，不是芯片执行一次矩阵需要 1106 s。

聊天中明确返回通过的官方目标：

```text
//tests/cocotb/vme_test:vme_test_vme_matmul_int8_test
//tests/cocotb/vme_test:vme_test_vme_matmul_fp32_test
//tests/cocotb/vme_test:vme_test_vme_msettm_matmul_test
//tests/cocotb/vme_test:vme_test_vme_load_store_test
//tests/cocotb/vme_test:vme_test_vme_msettk_clamp_test
//tests/cocotb/vme_test:vme_test_vme_msettm_clamp_test
//tests/cocotb/vme_test:vme_test_vme_transpose_test
//tests/cocotb/vme_test:vme_test_vme_altfmt_test
//tests/cocotb/vme_test:vme_test_vme_decode_test
//tests/cocotb/vme_test:vme_test_vme_mset_csr_test
//tests/cocotb/vme_test:vme_test_vme_mset_retire_test
//tests/cocotb/vme_test:vme_test_vme_vset_mtype_reset_test
```

已有 BUILD 中其他目标，例如 mstatus 相关，不因文件存在就记为本轮已执行。FP32 用例通过不等于所有 FP32/BF16 精度、异常、舍入模式都已回归。

随后新增 `vme_matrix_signed_diagnostic_test` 与 `vme_matrix_common_perf_test`，用户报告均 PASS。有符号诊断为选定负 B、四符号组合、INT8 极值及 Tk=1/2/3/4 共 9 个实例。

### 8.4 跨主机 signed stress

8 个 batch，每个 4 组基线 K/类型实例，合计 32 用例。两边共用逻辑 A/B/C，INT32 golden 使用扩展精度，检查所有输出；每套 8192 个元素均通过。

| Batch | 覆盖重点 | 两主机相同 SHA256 |
| --- | --- | --- |
| positive_positive | A/B 非负 | `58d8d2697423a1782f17fae699f02a344abf777625ebc9d9bbbd75f6a4136245` |
| positive_negative | A 正、B 负 | `291a0f7171d4057f1bfb43065cafd6b334ce28ebfcad4dbca77890c55e068f09` |
| negative_positive | A 负、B 正 | `ab36dfccc926b0c3ee5b6fd8b24b932c8d3e62e98fca054a1dfd0735ad8cbbfb` |
| negative_negative | A/B 负 | `db9d79e4c5d16503d739c40a58395455b7cc224ad3c19f93f5d0a9880853d824` |
| signed_edges | signed 边界 | `8260cbea8dd6576c2eab67143e4bcb28af513506bb8f6cdb281fccce142bde41` |
| random_seed137 | 固定种子随机 | `ec4d6d1feceb63a1b616065d63150cb8d2c579ca399179a94028914e16c3772b` |
| all_minus128 | 全 -128 | `fc271b0bfeaeaee5789e6b3f562e79c8685ab6439577531dda41fdc432a83ec9` |
| alternating_extremes | 极值交替 | `c06a5c82b88e62355df290f74248e22b67494d5f4fa98af4177487b3f57f0d15` |

服务器目录：`/data/home2/lqq/Desktop/mxu_runs/Yangg152_signed_stress.f9j80n`。用户提供8个 PASS行及总 marker，然后提供 `vectors.log` 中 8 个 manifest hash，与官方摘要完全一致。

官方摘要首次 `ModuleNotFoundError: numpy` 是 shell Python 缺依赖，不是 RTL 错。使用 `conda run -n coral-matrix python ...` 并安装该环境的 NumPy后完成摘要。相关命令见第 16 节。

### 8.5 K 边界、输入 bubbles、输出 backpressure

共同逻辑向量 K：

```text
1 2 3 4 7 15 16 17 31 32 33 63 64 65 127 128 129 240 241 255 256
```

向量集 SHA256：`b71ab7aecb33652c0d7fcda2887e10db948e35fc482b03ef8d28bb374afd888a`。两主机 manifest 一致。

官方：Tk=1 按 K 累加，21 用例、5376 元素检查通过。没有给官方接口注入与 fork 同样的输出停顿，不能说它在这轮已完成同等 backpressure 覆盖。

fork：21 个 K × 2 种输入时序 + 1 个输出 stall = 43 次。两种输入时序为连续 beat，以及每第三个 continuation beat 前插两个 valid-low bubble。每个用例独立 VCS 进程，输出常 ready（单独 stall 除外）。padding 用非零毒化值，避免靠补零隐藏错误。

| K | 两种输入时序 | 用户报告现象 |
| --- | --- | --- |
| 1,2,3,4,7,15,16,32,64,128,240,256 | 均 PASS，共 24 次 | 每次 64/64 output beats 匹配 |
| 17,31,33,63,65,127,129,241,255 | 均 FAIL，共 18 次 | 64 次输出握手，但 0/64 匹配，所展示输出为 X |
| K=16，额外输出 stall | FAIL 1 次 | `valid/data not held while ready=0` |

完整目录：`/data/home2/lqq/Desktop/mxu_runs/Yangg152_boundary.8KOTaG`。总计 `runs=43 pass=24 fail=19`，脚本非零退出是正确报告失败，不是“环境运行异常导致结果可忽略”。

源码解释：

- MCFG 对 K>=16 使用 `cfg_Tk[7:4]` 算 activation chunks，即向下取整，而载入布局需要 `ceil(K/16)`。例如 K=17 应两 chunk，却按一 chunk 推进行；行索引回绕导致早期数据覆盖、所需后段没有正确写入。K=256 有特殊 16-chunk 编码。
- `result_ready` 虽声明却未参与 MSTORE 的 valid/payload 保持、索引推进或 done。wrapper 将 downstream ready 传入，但自身写回路径还需独立检查。

这些是源机制与结果一致的解释，不是已有内部波形逐周期定位。若设计合法 K 只允许某集合、消费者保证始终 ready，要把限制写成明确契约；未明确前不要悄悄扩大“支持任意 K/标准 ready-valid”的声明。整核 ROB 下的实际停顿行为仍待验证。

### 8.6 为什么 AI 模型需要关注 K、M/N 和 uint8

逻辑 GEMM 为 `C[M,N] = A[M,K] × B[K,N]`。卷积 reduction K 常对应卷积核面积×输入通道；例如 3×3×3=27、3×3×8=72，1×1×17=17。实际模型不自然保证每个 K 是16倍数；K 还可能大于256。

不一定要求硬件一条指令直接支持每个 K，但系统必须有可靠、开销可接受的尾部/补零/分段方案。当前 fork 测试明确使用 K 补到16倍数的 workaround；不能把它写成修好了原生非对齐 K。

M/N 也不必恒为16×16。16×16是本轮物理 tile，真实层有小 batch、输出 channel尾块等。补零可保证算术正确，却浪费运算/访存；M=1,N=10 时 M/N占用率只有10/256≈3.91%。小 M/N 的优化或 fallback要看实际模型和内存开销。

是否必须 uint8，取决于量化格式、zero_point、权重范围、混合类型和工具链。此前没有最终模型，不能替团队决定“不需要”。当前 signed测试不覆盖 bias、requantization、激活裁剪、per-channel scale、非零zero_point以及端到端精度。

<a id="section-9"></a>

## 9. 性能测量的演进：哪些数字可以比

### 9.1 单位与口径

| 字段/单位 | 内容 | 不包括/不能代表 |
| --- | --- | --- |
| VCS/cocotb real time、Bazel Elapsed time | 编译或模拟器在宿主机耗时 | 芯片延迟、吞吐或频率 |
| `mma_latency_cycles` | fork MMA接受到注册done的周期间隔 | 装载、CPU指令、输出读回 |
| `input_to_output_span_cycles` | 独立MXU第一输入到最后结果握手，含TB空档 | 完整NPU软件/SoC过程 |
| `array_schedule_elapsed_cycles` | 官方首条阵列issue到最后tile写入，含供应间隙 | 主机上传、完整程序启动/读回 |
| `launch_wait_to_halt_cycles` / fullcore cycles | ELF/input已准备后，从fixture启动计时点到halt | Python整理、外部主机上传/下载、完整AI模型预后处理 |
| useful MACs | M×N×K；一次乘加计一个MAC | 有人按两次operation统计，不能混用 |
| physical MAC slots | 256×K_hw，本轮全物理tile名义槽位 | 实际切换功耗/面积/能效 |

阵列 monitor使用 elapsed intervals，独立MXU有 inclusive span字段，不能忽略边界差异直接相减。一切性能行先要求结果正确、完整输出、规定重复次数、向量hash和稳定周期通过解析器。

### 9.2 fork 原 TB 基础性能

提交 `519ac9b25e8d0c5e3eff44103fc32fcb1095a21c`，monitor_version=1，`scope=existing_mxu_tb_schedule`。日志目录 `Yangg152_perf.7x8re7`。

| K | load span | MMA latency | readback span | input→output | config→output | useful MACs | MMA MAC/cycle |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | 34 | 19 | 128 | 186 | 192 | 4096 | 215.579 |
| 64 | 130 | 67 | 128 | 330 | 336 | 16384 | 244.537 |
| 256 | 514 | 259 | 128 | 906 | 912 | 65536 | 253.035 |

非负K16重复首行。MMA=K+3符合当前FSM/流水预测，长K平均逼近256MAC/cycle。读回每128-bit beat需要独立MSTORE；原TB插入空档，所以不等于优化后流式吞吐。

### 9.3 官方普通矩阵程序与只读阵列观察

使用原仿真RTL、相同编译宏，额外模型只开放所需内部信号；没有更改矩阵功能RTL。observer检查每条指令四分块的唯一tile写入覆盖、完整INT32字节mask、指令PC、最后strip/retire和实际送MT的写使能，不用估计值冒充测量。

| K | Tk4指令数 | 单命令latency | delivered start interval | array window | MAC/window cycle | 无命令inflight interval | fullcore cycles |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | 4 | 12 | 24 | 84 | 48.761905 | 36 | 432 |
| 64 | 16 | 12 | 24 | 372 | 44.043011 | 180 | 722 |
| 256 | 64 | 12 | 24 | 1524 | 43.002625 | 756 | 1876 |

各重复3次；非负K16同首行。RAW等待和 full-offer/no-strip/no-RAW均0。window=`24×(K/4−1)+12=6K−12`；busy=47/191/767，active union=48/192/768，半开窗口边界导致差1正常。

不能用单命令12cycles当整个K=256运算，也不能把24cycle delivered间隔写成阵列固有限制。观察到没有命令在途，是这个驱动的稀疏供应，不自动证明CPU某具体逻辑是瓶颈。

### 9.4 预载复用同 tile 的 burst

新程序仅预载一个16×4 A与4×16 B，随后直线发4/16/64条矩阵指令，累加同tile；逻辑A/B沿K重复同一个chunk。**不是之前随机GEMM输入，也不是连续不同输出tile。**

| K | Tk4指令数 | 单命令latency | start interval | array window | MAC/window cycle | fullcore cycles |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | 4 | 12 | 4 | 24 | 170.666667 | 371 |
| 64 | 16 | 12 | 4 | 72 | 227.555556 | 419 |
| 256 | 64 | 12 | 4 | 264 | 248.242424 | 611 |

各重复3次，全部完整结果匹配。window=K+8，最后8个no-offer interval是pipeline尾部，RAW/no-inflight均0。证明这些条件下相邻同tile累加可重叠、4cycle开始间隔可达；不是宣称通用模型都达到256MAC/cycle。

fork原MMA的K+3与官方burst的K+8可以解释有限窗口填排差异，但输入预载、命令和边界不同，不能由此直接选整核。接下来才建立同端点整核对比。

<a id="section-10"></a>

## 10. 从模型形状诊断到整核速度：完整结果表

### 10.1 早期 7 种模型形状：功能成立，但两个计时窗口不同

共同逻辑集SHA256：`87085fb87e02f0b4d28c7de2aa256e55df836807842fe899538367211c72fbda`。每例重复3次，检查256个物理INT32输出，包含无效M/N区域应为0。

| 逻辑case | M | N | K | fork K_hw | 官方Tk1 fullcore | fork MMA | fork input→output |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| control_m16_n16_k64 | 16 | 16 | 64 | 64 | 1874 | 67 | 392 |
| conv3x3_c3_m16_n16 | 16 | 16 | 27 | 32 | 984 | 35 | 296 |
| conv3x3_c8_m7_n13 | 7 | 13 | 72 | 80 | 2066 | 83 | 440 |
| pointwise_c17_m15_n11 | 15 | 11 | 17 | 32 | 744 | 35 | 296 |
| pointwise_c65_m16_n16 | 16 | 16 | 65 | 80 | 1898 | 83 | 440 |
| fc_batch1_out10_k127 | 1 | 10 | 127 | 128 | 3386 | 131 | 584 |
| tail_m16_n9_k241 | 16 | 9 | 241 | 256 | 6123 | 259 | 968 |

fork目录 `/data/home2/lqq/Desktop/mxu_runs/Yangg152_model_tile.oP53jp`，7×3全部通过。fork readback span为191 cycles，不是最初TB的128；驱动/测量时序不同，不能据此说DUT退化了63cycles。

这组只验证卷积/FC类似的形状，不是实际层运行。官方是整核程序，fork是独立单元；当时fork看起来快很多，主要有口径不一致，不能宣布它是更高效的NPU。

### 10.2 K>256 与多输出 tile 的诊断

共同逻辑集SHA256：`77d2281e35119c649f96f030303bf487411ac10dcfe2eb59970cb889af890376`。每例重复3次。

| 逻辑case | 形状 | 物理输出tile | fork K passes | 官方sum tile fullcore | fork sum input→output | fork sum MMA |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| multi_tile_m20_n23_k272 | M20N23K272 | 4 | 256+16 | 27456 | 4112 | 1112 |
| three_pass_m1_n10_k528 | M1N10K528 | 1 | 256+256+16 | 13008 | 1808 | 537 |

fork每个输出tile只MZERO一次，随后MCFG/load/MMA保留累加，最后读回。第一例每tile input→output=1028、MMA总278；第二例1808/537。服务器目录 `Yangg152_layer.gPjV4B`，2例5tile×3次全部通过。

它验证分段累加不会被后续配置/装载清掉，以及M/N分块的算术正确性。不覆盖生产模型im2col、量化、层间内存、cache和真实dispatch，也不按不同计时端点的27456/4112计算NPU加速比。

### 10.3 同端点整核 7 用例：当前有效速度基线之一

官方使用 `VmeCoreMiniAxi`/ZVT，fork使用 `RvvCoreMiniAxi`/MXU。两边ELF和输入先装载，再计从fixture `execute_from()`/run-to-halt计时边界到停止的周期；名义clock=1.25ns、外部内存backing=4MiB。完整输出、逻辑hash、三次重复均由比较脚本检查。

官方Tk=4作为主要性能路径，K补至4倍数；fork K补至16倍数。Tk=1保留作功能诊断和历史对照，不拿它替代官方最佳已测路径。

| Case（顺序同10.1） | 官方Tk1 | 官方Tk4 | fork fullcore | Tk4 K_hw / fork K_hw | 官方Tk4 / fork |
| --- | ---: | ---: | ---: | --- | ---: |
| control_m16_n16_k64 | 1874 | 722 | 1939 | 64 / 64 | 0.372357 |
| conv3x3_c3_m16_n16 | 984 | 504 | 1291 | 28 / 32 | 0.390395 |
| conv3x3_c8_m7_n13 | 2066 | 770 | 2263 | 72 / 80 | 0.340256 |
| pointwise_c17_m15_n11 | 744 | 456 | 1291 | 20 / 32 | 0.353215 |
| pointwise_c65_m16_n16 | 1898 | 746 | 2263 | 68 / 80 | 0.329651 |
| fc_batch1_out10_k127 | 3386 | 1107 | 3235 | 128 / 128 | 0.342195 |
| tail_m16_n9_k241 | 6123 | 1803 | 5827 | 244 / 256 | 0.309422 |

ratio定义始终是官方cycles除以fork cycles，越小表示官方用周期越少。这7例官方Tk4是fork的约31%～39%，即此fixture任务的周期优势约2.56～3.23倍。仍有不同核、合法指令流、load次数、padding、驱动优化程度等差异，不能等同纯矩阵阵列效率或实测硅速度。

这是用户后来说“现在是不是可以直接比较速度”的背景：**可以比较同任务同端点的逻辑周期，不能在没有等频时序/外部系统评估时直接声称实际芯片倍速。** 两边若将来真的都能稳定200MHz，cycle×5ns才能换算该窗口时间。

### 10.4 22 用例整核扫描：完整用户结果

逻辑集SHA256：`4b2922a33acc0f69ace9aa0d8c3efe144e07fa6a903fc106126ce45f2aa9d4d4`，22例、每例3次。用户附件返回fork target PASS及全部22个paired行；不是只有脚本已生成。下面前17行M=N=16，后5行K=64。

| M×N | K | 官方 K_hw | fork K_hw | 官方Tk4 fullcore | fork fullcore | 官方 / fork |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 16×16 | 1 | 4 | 16 | 358 | 968 | 0.369835 |
| 16×16 | 4 | 4 | 16 | 358 | 968 | 0.369835 |
| 16×16 | 8 | 8 | 16 | 383 | 968 | 0.395661 |
| 16×16 | 15 | 16 | 16 | 432 | 968 | 0.446281 |
| 16×16 | 16 | 16 | 16 | 432 | 968 | 0.446281 |
| 16×16 | 17 | 20 | 32 | 456 | 1291 | 0.353215 |
| 16×16 | 31 | 32 | 32 | 529 | 1291 | 0.409760 |
| 16×16 | 32 | 32 | 32 | 529 | 1291 | 0.409760 |
| 16×16 | 33 | 36 | 48 | 553 | 1615 | 0.342415 |
| 16×16 | 63 | 64 | 64 | 722 | 1939 | 0.372357 |
| 16×16 | 64 | 64 | 64 | 722 | 1939 | 0.372357 |
| 16×16 | 65 | 68 | 80 | 746 | 2263 | 0.329651 |
| 16×16 | 127 | 128 | 128 | 1107 | 3235 | 0.342195 |
| 16×16 | 128 | 128 | 128 | 1107 | 3235 | 0.342195 |
| 16×16 | 129 | 132 | 144 | 1131 | 3559 | 0.317786 |
| 16×16 | 255 | 256 | 256 | 1876 | 5827 | 0.321950 |
| 16×16 | 256 | 256 | 256 | 1876 | 5827 | 0.321950 |
| 1×1 | 64 | 64 | 64 | 722 | 1939 | 0.372357 |
| 1×16 | 64 | 64 | 64 | 722 | 1939 | 0.372357 |
| 16×1 | 64 | 64 | 64 | 722 | 1939 | 0.372357 |
| 8×8 | 64 | 64 | 64 | 722 | 1939 | 0.372357 |
| 15×15 | 64 | 64 | 64 | 722 | 1939 | 0.372357 |

17个K的变化体现padding/固定开销；K64五个小M/N形状与满tile同周期，说明**当前驱动仍计算/读回完整物理tile，没有把小逻辑尺寸变成更短执行时间**。这不是证明所有可行内核的小M/N性能都必然相同。

22例全是隔离tile，不测跨tile权重复用或模型层内持续执行。官方在这组也是较少周期，但不将多个不同任务的ratio简单平均当模型推理加速比。

### 10.5 一次启动、共享 B、多输出 tile：9 组结果

逻辑集SHA256：`3b833b15bab9c223589889cf2534fd903db046b989658a0979ffb7fd1abfb3bb`。K=16/64/256，T=1/4/16不同Atile，共享同B，每例3次，全部输出检查。

大输入/输出移至 `.extbss` 外部地址 `0x20000000`，小控制字保留DTCM。这与此前DTCM单tile程序的访存条件不同；即使T=1也不能跨套件把cycle差全归因于batch长度。

官方Tk4每tile从内存重新加载A/B；fork只载B一次到权重SRAM，各tile清C、重载A后计算。因此本轮是合法驱动策略的总体比较，尚未拆清同核复用贡献，也没证明官方schedule最优。

| K | Tiles | 官方总cycles | fork总cycles | 官方cycles/tile | forkcycles/tile | 官方 / fork |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | 1 | 872 | 1271 | 872.000 | 1271.000 | 0.686074 |
| 16 | 4 | 2891 | 3938 | 722.750 | 984.500 | 0.734129 |
| 16 | 16 | 10967 | 14606 | 685.438 | 912.875 | 0.750856 |
| 64 | 1 | 1544 | 2507 | 1544.000 | 2507.000 | 0.615876 |
| 64 | 4 | 5579 | 7370 | 1394.750 | 1842.500 | 0.756988 |
| 64 | 16 | 21719 | 26822 | 1357.438 | 1676.375 | 0.809746 |
| 256 | 1 | 4232 | 7449 | 4232.000 | 7449.000 | 0.568130 |
| 256 | 4 | 16331 | 21096 | 4082.750 | 5274.000 | 0.774128 |
| 256 | 16 | 64727 | 75684 | 4045.438 | 4730.250 | 0.855227 |

官方仍较少周期，长batch差距变小，fork复用权重与启动摊销可能有贡献，但因不同核心/指令流不能仅从跨核ratio分离因果。新加了fork同核强制每tile重载B的对照；**这项是尚待继续的工作**，不是已经跑完的第10张结果表。

<a id="section-11"></a>

## 11. 适用、不适用与目前选型态度

| 方向 | 官方候选 | Yangg152 |
| --- | --- | --- |
| 整个NPU作为SoC候选IP | 更适合作为当前主候选：本轮生成、整核回归/比较和交付已建立 | 需保留为对照或研究候选，先解决接口/合法K/数据类型契约及软件路线 |
| 只研究signed INT8 16×16矩阵 | 官方路径较复杂，涉及指令与tile状态；有更多模式 | 独立unit结构清楚，VCS可少文件跑起来，便于学习/局部改动 |
| 整核同任务速度 | Tk4在已测7例、22例、9组batch中周期更少 | 独立MMA很快不等于整核更快；整核测试已纠正早期误解 |
| K尾部/小M/N | 已测功能方案可行；还需优化实际内核和tail | 补零到16可用，原生非对齐K>16的选定实例明确失败 |
| uint8 | 本记录不声称已完成官方uint8全语义回归 | 高值uint8诊断失败；不适合未经转换/修复直接接需uint8的模型 |
| 输出可停顿消费者 | 需增加对应整核/AXI/阵列压力覆盖 | 独立unit标准ready-valid保持测试失败，整核协议仍待确认 |
| 浮点/BF16等更多模式 | 有配置和若干测试，不能把“开启”写成全部覆盖 | 本轮主要验证signed INT8，不据此提供同等浮点能力结论 |
| 真实模型、频率、面积、功耗 | 未完成最终证明 | 同样未完成，不能因PE简单直接宣称更省面积/能耗 |

“官方完善到什么程度”的当前可回答范围：它不是只有一个乘法模块，有完整核、扩展、生成工具和多类测试；本轮确认所执行路径能运行。但任何公开源码/官方身份都不代替我们的SoC集成与工艺签核。源码里其他配置的TODO/已知限制也不能靠本轮一个顶层回归消除。

目前不要写“最终已选定官方，fork无价值”，也不要写“fork比官方快很多”。合理表述是：**整核集成目标下，官方是当前交付/验证主候选；fork继续用于对照，但存在明确已知限制；最终决定待模型、系统及PPA证据。**

<a id="section-12"></a>

## 12. 报错很多的原因与具体修复：交接排错索引

### 12.1 为什么 fork 独立单元不用 Bazel，整核又需要

独立MXU测试只有几个已写好的SV/Verilog文件，VCS直接编译即可。整个CoralNPU还需要Chisel生成核/AXI/TCM、构建RVV源码、RISC-V ELF、模拟器、依赖和测试runner，所以整核流程采用Bazel。

fork来自较旧官方基线，携带作者本地路径与较旧构建规则。本轮改用较新的Bazel8/Verilator/cocotb后暴露的是一串依赖和runfiles兼容问题；绝大多数错误发生在真正执行DUT之前。不能用错误数量推断矩阵算术质量，也不能把修好构建系统说成修好了所有功能。

### 12.2 已记录修复表

| 错误/现象 | 原因/处理 | 提交或状态 |
| --- | --- | --- |
| wrappers权限、symlink错误 | Git模式未恢复；恢复120000/100755 | `a9f180e` |
| VCS timescale混用 | 加默认`-timescale=1ns/1ps` | 服务器运行脚本保留 |
| FSDB系统任务未定义 | 没有加载Verdi PLI；改可选`MXU_ENABLE_FSDB` | `fecb9e2` |
| 高值unsigned数值错误 | `cfg_signed`未驱动unsigned实现 | `2ed9808`增加诊断，未修DUT |
| CentOS Bazel运行库缺失 | glibc/libstdc++太旧 | 转Ubuntu；没有替换服务器库 |
| Docker template panic / daemon连不上 | 只有客户端、无可用服务socket | 放弃此服务器Docker路线 |
| 系统command-not-found SQLite报错 | 系统Python helper/动态库问题，命令本身未找到 | 建Conda并正确初始化/激活；非RTL错误 |
| Bazel依赖下载超时 | GitHub release/archive重定向路径网络失败 | Windows代理，VM可直连、server反向SSH |
| fork硬编码`/home/yang/.../tflite-micro` | 作者本地checkout不存在 | 固定远程patched归档，`8dc4b1e`相关更改 |
| `rules_java_deps.bzl`不存在 | fork旧Java规则缺该扩展 | pin到工作正常的rules_java9.6.1，`62f3472` |
| `compatibility_proxy` WORKSPACE循环 | repository定义/load顺序错误 | 调整先定义再引用，`596291b` |
| `**/*.elf` glob未匹配 | Bazel8默认空glob限制 | 显式允许可选ELF，`6664a44` |
| `bool_flag`没有`scope` | transitive skylib太旧 | 提前pin bazel_skylib1.9.0，`3e61d23` |
| `CcToolchainInfo`没有`.cc` | provider接口假设不匹配 | 直接使用CcToolchainInfo，`ec67d8e` |
| pyelftools/pytest包glob cocotb源失败 | 通用wheel annotation把可选cocotb文件当必有 | 可选glob，`b941151` |
| Bison filegroup不支持`path` | BUILD属性非法 | 去掉不支持属性，`4219431` |
| local firtool目标/文件不存在 | 预期本地归档未有；空glob先阻塞加载 | 允许可选glob后加载既有sh_binary及外部firtool依赖，`004b81a` |
| rules_proto中`proto_common`未定义 | 规则版本与Bazel8不匹配 | pin兼容版本，`4232dfe` |
| RVVI的`*.v`空glob | 仓库含可选扩展，单一pattern无匹配 | 可选HDL扩展glob，`6585db4` |
| `verilated_std.sv/.vlt`找不到 | Verilator runfiles root假定错误 | 依据tool owner定位root，`5804830` |
| runner Python相对路径不存在 | 运行目录是runfiles，不是原execroot | runfiles Python路径，`e71664f`、`327519c` |
| `libcocotbvpi_verilator.so`找不到 | 动态库未按runfiles定位 | LD_LIBRARY_PATH解析，`85d8a6d` |
| fork首条MXU非法指令 | RVV reset后vill=1，驱动未初始化合法vector状态 | `3ff8203`先vsetvli，`c79d7de`完成验证 |
| shared batch linker location counter backwards | 静态数据过大超过DTCM32KiB布局 | 大缓冲移`.extbss`，`b6e0792`；没扩DTCM |
| 摘要脚本缺NumPy | shellPython不同于Bazel hermeticPython | Conda安装NumPy并conda run；非DUT失败 |
| SSH17908监听失败 | 旧lqq隧道还占端口 | 确认会话后关闭，端口释放；勿照抄旧PID |

### 12.3 fork 整核非法指令定位细节

最初真实仿真在首个control例、repeat0、cycles139失败。加入fault CSR报告和**首次异常捕获**后得到：first_mepc=`0x198`，first_mcause=`0x2`（非法指令），first_mtval=`0x0e001057`（MZERO）。之后异常处理又出现final mtval=`0x16c`、mcause=`0x19`，会掩盖最初根因。

`d22fd8f`、`58cd3dc`新增诊断后，在基准程序开始先执行 `vsetvli ... e8,m1,ta,ma`，建立合法vector状态，然后MCFG/MZERO。LoadA/LoadW/Store按向量宽设置所需VL/SEW。程序主入口也检查K_hw在16～256且是16倍数，避免把已知不合法载入布局塞入整核比较。

这是验证程序前置条件修复，没有为了通过而更改MXU算术RTL。新增首次异常采集仍值得保留：如果未来模型出现trap，优先定位首个异常和其PC，不只看halt/final fault。

### 12.4 常见 warning 的解释

- `WORKSPACE support will be removed...`：迁移提醒，本轮先固定已验证Bazel版本；不是当前测试失败。
- Java `-Xverify:none/-noverify` deprecated：JDK警告，不当作RTL错误。
- enum cast `[W001]`：硬件生成提示，生成成功不等于可以忽略所有后续lint。
- Bazel `tests whose specified size is too big`：test size/timeout分类提醒，不是用例FAIL，也不是NPU太大。
- mirror404后若fallback源成功，单个下载warning不一定导致失败；须读最后ERROR/target状态。
- 两状态Verilator PASS不能代替四状态VCS的X初始化、门级时序和真实RAM测试。

<a id="section-13"></a>

## 13. 10月4日历史RTL交付：旧包、原始仿真包、文档版三个身份

### 13.1 团队候选版与历史 prod 工具

团队官方候选仓库 `main` 当时保存上游固定提交 `870993f7425066037f300c52237c283821e75cbb`。历史工具分支 `codex/rtl-handoff` 的已记录head是 `4da4090aab747589a70c49c1b1b1bb0f0a164c69`；其中有生产包导出、workflow、DC/SDC模板和黑盒方案。该分支不是本记录日期以后永不变化的保证，接手时读实际ref。

最初为给组员综合，选了官方 `prod` 目标：

```text
//hdl/chisel/src/coralnpu/prod:vme_core_mini_axi_prod_cc_library_emit_verilog
```

它来自官方源码，但 `enableAxiInstructionFetch=false`，与之前普通仿真目标true不同。用户问“是不是之前跑仿真的正确RTL”时发现不一致；随后要求只保证原来仿真那份。本次已纠正，**这是配置选择的失误，不应在交接中隐去。** `prod`名字不表示只有它才能综合，也不表示此前功能测试自动覆盖它。

旧包通过固定源码生成、文件完整性及generic lint，未做与之前相同的prod整核功能回归。旧私有GitHub Actions使用Ubuntu24/Bazel8.6，lint使用Verilator5.020；这也不同于原仿真日志5.052。旧compile-unit包装曾修复header/macro/typedef作用域与文件顺序，不是修改原始RTL算术。

旧最终生产包，仅作历史参考：

```text
Windows: E:\Projects\矩阵二选一\handoff_output\coralnpu_rtl_870993f.tar.gz
SHA256: cf206a6bde79b78b4f0f32363393f5a22158154134f49c4496c1ce0d4e39a9ce
外部AXI取指: false
```

历史CI run IDs `37141980733`、`37143321212`，本地保留artifact ZIP，包括`11280324862`、`11280654985`、`11281136525`。这些含生产包/中间包装，不能仅按时间或文件名任选；私有artifact还需要团队访问权限。

### 13.2 原始 Ubuntu 仿真 RTL 导出包：实物已接收

`887181e` 增加 `export_simulated_google_rtl.py`，它只复制已存在生成物，不调用Bazel、不更改配置、不修改RTL、不清理缓存。检查参数、现有PASS日志、tracked核心改动、ZIP路径、文件冲突和复制前后hash。不存在生成物时停止，不擅自重新生成。

用户实际导出：

```text
Ubuntu目录: /home/lqq/coralnpu_sim_rtl_20261004_042513
Ubuntu包:   /home/lqq/coralnpu_sim_rtl_20261004_042513.tar.gz
Windows包:  E:\Projects\矩阵二选一\coralnpu_sim_rtl_20261004_042513.tar.gz
包SHA256:   0a7d737dc1c18d49781b9cdb246a4fe0bf11ffeb1db509ca8263bca255f271ed
```

用户输出及Windows独立核对均确认：top=`VmeCoreMiniAxi`、AXI取指true、`checked_files=262`、`existing_passing_logs=1`、`original_rtl_unchanged=true`。249个原ZIP解包文件字节一致。原始包仍保留，未覆盖。

导出时比较仓库HEAD=`887181e512439b29e0d873eea2bb2ab2a4209808`。**这是导出时checkout，不是对旧Bazel缓存生成时提交的独立证明。** 随包旧测试日志也没有记录运行时RTL文件hash；不能把现有材料包装为已建立完整可追溯功能签核链。实际交付用下面文件hash锁定身份。

| 原始生成文件 | SHA256（文档版也必须相同） |
| --- | --- |
| `original/VmeCoreMiniAxi.sv` | `56bdb782f4dff93b5ed3a2341ddf702ef8ec6ce66cbc819d245656e5bedb4c8c` |
| `original/VmeCoreMiniAxi.zip` | `995399afeedb86b85cab374523c744a28ab4de940d4d27deea605793db294b26` |
| `original/VVmeCoreMiniAxi_parameters.h` | `adcd2566a0492b27d9776ca83b9592f73f92aacac73da46cd02a2d88153a0bbd` |

`evidence/test_00.log` 的SHA256为 `fe8929650e6d61893029d1fb38a923a6a000e80c6c729db4aeb959f3862f735d`。它是官方shared-weight batch target的已有通过日志：9逻辑case×3次=27次，48384个INT32输出元素匹配，cocotb `TESTS=1 PASS=1 FAIL=0`。不是一份包含之前全部回归的日志合集。

### 13.3 10月4日推荐文档更新版：当时给综合组员这一包

`e3046dc` 完善362行详细交接说明，并增加doc-only刷新工具。新包只改`HANDOFF.md`、`manifest.json`、`SHA256SUMS`；RTL、编译入口、原文件、证据日志不变。导出/刷新工具本地11个单元测试通过；这验证打包工具，不是新跑DUT。

```text
推荐压缩包:
E:\Projects\矩阵二选一\handoff_output\coralnpu_sim_rtl_20261004_042513_docs_v2.tar.gz

SHA256:
efbb74e249413f5f99320b7305a9a5064e76d50bc936913f07f52b0b9888a06c

本地解包目录:
E:\Projects\矩阵二选一\handoff_output\coralnpu_sim_rtl_20261004_042513_docs_v2
```

v2包仍262文件，两个版本的原始RTLhash保持一致。原始包和文档包的整包SHA不同是预期，不是换了DUT。后续仅改工作记录也不会自动重打或上传这份RTL包。

### 13.4 当前包内容与综合入口

```text
HANDOFF.md                      详细RAM、接口、综合及网表回传说明
manifest.json / SHA256SUMS       配置/来源/文件身份
verify_export.py                标准库完整性检查
LICENSE                         原许可证
original/                       原始sv、zip、参数头
rtl/                            原ZIP解包文件
compile_units/all.sv             按官方顺序include的单编译入口
filelist_synth.f                 宏、include dirs及唯一入口
dc_sources.tcl                  顶层、宏、源文件和目录变量
evidence/test_00.log             已有通过日志
evidence/*BUILD.txt              仿真模型/生成目标定义证据
```

推荐从包根目录校验，然后只分析`compile_units/all.sv`。不要同时加入单文件sv、拆分文件和include包装，避免重复定义；不要重新按文件名排序header和package。

```bash
sha256sum -c SHA256SUMS
python3 verify_export.py --verify .
```

清单宏为：`SYNTHESIS USE_GENERIC VLEN_128 TB_SUPPORT ZVE32F_ON ZVT_ON`。`SYNTHESIS`切RAM可综合数组分支，不会关闭生成时的AXI外取指；`TB_SUPPORT`是原RVV接口/类型宏，不因名字带TB就可删。

当前包**没有**`run_dc.tcl`、SDC、黑盒替换、工艺RAM模型或网表。这些名字只出现在旧生产工具包；当前交接说明给最小DC接入代码，由组员结合实际库和约束流程执行。源码中受`ifndef SYNTHESIS`保护的验证资源不应另行打开进行综合。

<a id="section-14"></a>

## 14. RAM、AXI 与启动：交接必须保留的硬件事实

### 14.1 当前实际生成参数

| 配置 | 当前值 |
| --- | --- |
| top | `VmeCoreMiniAxi` |
| enableRvv / rvvVlen | true / 128 |
| enableVme | true |
| enableFloat / enableZfbfmin / enableVectorBf16 | true / true / true |
| enableVerification | false |
| enableAxiInstructionFetch | true |
| ITCM / DTCM | 8 / 32 KiB |
| fetch/LSU数据宽 | 128 bit |
| AXI master/slave 地址、数据、ID | 32 / 128 / 6 bit；strobe16 bit |

以实际参数头/顶层端口为准。Scala默认值、prod目标、verification目标与此生成实例不能混写；同名top不保证同配置。

### 14.2 TCM SRAM 规格

| 存储 | 字节容量 | 当前逻辑组织 | 端口与掩码 |
| --- | ---: | --- | --- |
| ITCM | 8192（8KiB） | 1×512×128 bit | 每bank单端口1RW，16bit byte mask |
| DTCM | 32768（32KiB） | 4×512×128 bit，深度bank扩展 | 同左；不是4独立访问口 |
| 合计 | 40960（40KiB） | 5bank，327680bit | 不包括向量/矩阵/流水寄存器等 |

相对top实例与基址：

```text
itcm.sram.sramModules_0   0x00000000
dtcm.sram.sramModules_0   0x00010000
dtcm.sram.sramModules_1   0x00012000
dtcm.sram.sramModules_2   0x00014000
dtcm.sram.sramModules_3   0x00016000
```

每bank地址9bit字地址，一字16byte；clock上升沿访问，enable/write高有效，wmask[i]控制wdata[8*i+:8]，读协议一周期。`rvalid=enable`延迟一周期，包含写请求，当前bank包装不用这个输出。没有RAM清零reset或ECC/parity接口。

`SRAM_2048x128.sv`是4个512bank的包装，不是这份包已经绑定了一颗2048×128宏。通用分支只在读时更新读地址；同地址写可能改变输出，不应承诺所有idle/write状态下rdata保持不变。

### 14.3 可调容量与范围的准确表述

ITCM/DTCM可通过**生成配置**改变，不是运行时写CSR扩容。源码`MemoryRegions.highmem()`为TCM容量到1MiB预留地址，ITCM基址0、DTCM基址`0x00100000`、CSR基址`0x00200000`；也有8/128KiB生产目标。

这不能简化成“任何数字都能无条件生成/综合”。`SramNx128`默认候选bank深度512/128，需满足整除/布局规则，还要检查地址冲突、宏供应、linker、fixture、主机访问和重新回归。当前8/32KiB交付没有更改，也没有运行扩容后的容量扫描。

### 14.4 RAM 会影响哪些仿真与实现结果

容量影响程序/数据能否放下、外部访存比例和带宽；端口数量、数据宽、mask、读延迟、读写同时行为、使能极性、输出保持、上电未知值、ECC、低功耗/BIST等也会影响适配、吞吐和验证。

当前Verilator使用官方DPI-C RAM行为模型，支持后门加载；综合宏选择同`Sram.v`的数组分支。文件字节相同但编译分支不同，DPI回归不能自动证明数组/宏后的门级功能。

官方提供TSMC12FFC/GF12LPP/GF22适配分支，但本轮没有团队工艺库。真实宏需匹配1RW、128bit、byte mask和一周期响应；低有效CE/WE/BWE需核对极性。用两个64bit宏拼128bit也是新物理映射，要记录实际宏数量。

若数组综合成触发器，面积/时序不能当SRAM硬宏结果；若RAM黑盒，面积/时序覆盖不完整、输出不可用于功能验证。组员必须明确哪个结果是逻辑-only、哪个含实际RAM。

### 14.5 AXI 外取指与 SoC 集成形式

取指开启表示**可以从AXI取指，不是只能从AXI取指**。PC在ITCM范围走本地ITCM，否则IBus2Axi主动发起master读请求。主CPU不需要逐条把指令推给NPU。外部指令与数据master读经仲裁共享资源，会受外部存储延迟/竞争影响。

关闭外取指不等于关闭AXI slave装载或master数据访问；本次包保留true。将来可以程序放ITCM、共享SRAM/ROM/DDR等，但必须由SoC真实互连响应相应地址。

当前核内地址：ITCM `0x00000000～0x00001fff`，DTCM `0x00010000～0x00017fff`，CSR `0x00030000～0x00030fff`。这是核内地址，不是Cheshire最终全局地址分配。fixture的`0x20000000`外部memory仅是本轮测试配置。

主要接口：`io_aclk`、低有效`io_aresetn`、test enable`io_te`、`io_boot_addr`、AXI master/slave、DM调试、halted/fault/wfi。`io_irq/io_timer_irq/io_software_irq`是**进NPU的输入**，不能直接当作给主CPU的计算完成中断输出。

### 14.6 复位、门控和启动

RstSync异步断言、同步释放（复位/门控各有延迟级）；ClockGate的低电平透明enable latch加与门是有意门控结构，不是见到latch就删除。映射ICG后需记录单元、test-enable、约束。

CSR offset0 reset值3：bit0核reset、bit1门控。offset4启动PC、offset8状态bit0halted/bit1fault。**只释放外部aresetn不会自动运行程序**；准备程序/数据，设置入口，向`0x30000`写0才释放核控制。

AXI数据128bit、CSR32bit，PC写应落WDATA[63:32]，状态读RDATA[95:64]，配合地址/WSTRB。不能所有CSR都把数据放低32bit。

门仿/实际SoC建议经AXI slave装载，不依赖RTL RAM数组内部路径或DPI后门。状态判断必须包含fault和超时；WFI不是自动成功。更详细流程、宏/端口和组员回传清单以[HANDOFF-simulated-rtl.md](HANDOFF-simulated-rtl.md)为准。

<a id="section-15"></a>

## 15. 历史截至10月4日的待办与验证路线（当前以第26节为准）

### 15.1 不应被接手人误认为已完成的事项

- 没有完成真实AI模型端到端推理与精度/层耗时对照。
- 没有证明示例模型逐层实际走ZVT/MXU，而不是RVV/标量fallback。
- 没有修复fork的uint8、非对齐K>16、输出ready保持问题，也没有完成整核ROB压力定位。
- 没有完成中途reset、异常/flush、连续不同tile依赖、全指令组合和长累加overflow语义的覆盖闭环。
- 没有统一全部访存/driver策略，也没有证明任何一边内核已经最优。
- 没有验证两套都能达到200MHz；当前仿真周期只是逻辑时间基准。
- 没有实际DC综合报告、STA签核、LEC、时序门仿、scan/DFT/BIST、布局布线或功耗结果。
- 没有将候选RTL完整接入Cheshire互连、reset/clock、地址图、软件启动或完成通知流程。
- 没有把每个历史测试完整日志和生成时RTLhash都收齐成正式可追溯归档。
- 新fork权重重载对照尚待执行；不要从已有batch日志猜它的结果。

### 15.2 需要和团队确定的内容

| 决策项 | 需要具体回答的问题 | 影响 |
| --- | --- | --- |
| 模型清单 | 首批跑哪些模型、输入尺寸、batch、各层M/N/K与算子？ | 选型权重、tail/小M/N/大K覆盖、真实性能目标 |
| 数值格式 | signed INT8还是uint8/混合；activation/weight zero_point、scale、bias、累加/舍入规则？ | 指令支持、量化补偿、精度与unsigned需求 |
| 系统目标 | 延迟、持续吞吐、功耗、面积预算，200MHz目标角与裕量？ | 不只看cycle最低，还看PPA和能效 |
| 最终TCM | ITCM/DTCM多大、程序/数据放内部还是外部？ | RAM面积、linker、启动、带宽和外取指占用 |
| SRAM供应 | 工艺节点、宏深宽/端口/mask/延迟、模型和.lib/.db？ | 适配RTL、真实时序、功能门仿 |
| SoC接口 | AXI位宽/ID转换、地址重映射、master路由、错误响应/超时？ | 正确装载、外部执行、数据搬运与协议验证 |
| 时钟复位 | 是否同域、CDC、ICG、reset同步、低功耗策略？ | 时序约束、集成可靠性、DFT |
| 主CPU控制 | 程序装载、启动寄存器、完成轮询或额外IRQ、故障恢复？ | 驱动和系统级测试 |
| 软件路线 | 采用哪套TFLM/算子实现、如何确认每层实际调用NPU矩阵指令？ | “加速器存在”与“模型真正加速”之间的差距 |
| fork处理策略 | 保留限制并适配，还是授权修复并重新验证？ | 版本管理、回归范围、维护成本 |
| 候选固定版本 | 本轮固定源码是否继续冻结、如何接受上游更新？ | 避免测试与交付失去对应 |
| 验证责任 | 谁提供golden/库模型，谁跑RTL/GLS，谁签约束/RAM/DFT？ | 交接接口和验收标准 |

目前团队唯一已明确的系统范围是“集成整个CoralNPU”；其余选择待讨论，不替团队默认拍板。

### 15.3 推荐接下来按这个顺序推进

1. **保全历史证据。** 从Ubuntu/EDA152拷贝完整日志、向量manifest、实际HEAD、工具版本，避免Bazels后续运行覆盖`test.log`。对本轮已给组员的RTL包记录hash和接收人，不仅记文件名。
2. **跑fork同核权重重载对照。** 两种模式同新ELF、同fixture，解释权重复用的周期收益；参考第16.5节。
3. **补系统条件的速度测试。** 统一外部内存延迟/带宽、加入AXI stall与竞争；把装载、执行、结果返回和预后处理分别计时，合理优化两边驱动，明确reuse策略。不能静默改旧suite基线。
4. **真实模型路线核验。** 先少量层确认quantization/golden和dispatch，再完整模型。输出逐层MxNxK、实际MXU/ZVT/RVV/fallback调用、准确度、周期和memory traffic。
5. **继续功能/协议覆盖。** 随机矩阵、reset/flush、命令依赖、长K累加、overflow、backpressure、AXI错误响应；fork若修复要先有失败复现、再双副本及整核回归。
6. **组员DC首跑。** 用当前仿真包和明确RAM处理，5ns约束评估；输出时序、面积、库角、门控时钟/未约束路径报告，不能仅看工具exit=0。
7. **网表回传后门仿。** 首先不带SDF功能门仿，经顶层装载程序；再加可用SDF/时序检查，并与RTLgolden对照。LEC/DFT及更完整签核由团队另行安排。
8. **SoC集成闭环。** 在Cheshire真实接口、全局地址/启动软件/中断方式下再回归和测模型；最终PPA与应用结果再定方案。

### 15.4 综合组员应回传什么

不是只回传一个`.v`网表。至少包括：top/网表、综合脚本与DC版本/日志、实际SDC、标准单元与ICG功能模型、若采用宏则RAM模型/适配层/库版本、bank到宏映射、面积/时序/check_design/未约束路径报告、是否扁平化/插DFT/换RAM等变更说明。SDF有则说明角、单位和来源，无则明确没有；DDC可选。

有许可限制的标准单元/PDK/工艺模型按团队许可内部共享，不随意上传公开仓库。RAM黑盒输出没有有效功能，缺模型时不能报告门仿结果正确。

<a id="section-16"></a>

## 16. 早期两版本比较及8/32KiB交付的复现命令（历史用途）

以下是操作入口，不要求把所有已通过测试立刻重跑一遍。先判断目的、确认环境和保存旧日志；**每个阶段失败就停，不连续执行后面的比较脚本。** 当前仓库的各专题README有更完整的guard与解释。

### 16.1 Git同步与版本核对

两子工程在个人仓库内不是需要分别pull的独立子模块；从根目录更新一次。

Ubuntu：

```bash
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git status --short
git remote -v
git fetch origin
git rev-list --left-right --count HEAD...origin/main
git log --oneline --left-right HEAD...origin/main
git pull --ff-only origin main
git rev-parse HEAD
```

EDA152：

```bash
cd /home2/lqq/Desktop/Coral_matrix
git status --short
git fetch origin
git rev-list --left-right --count HEAD...origin/main
git pull --ff-only origin main
git rev-parse HEAD
ls -l coralnpu-google/toolchain/wrappers/{clang,driver.sh}
ls -l coralnpu-Yangg152/toolchain/wrappers/{clang,driver.sh}
```

如果fetch因代理失败，后面的`HEAD...origin/main`只比较本地陈旧远程ref，`0 0`不能证明远程没更新。若工作树有用户修改或出现分叉，先沟通/备份，不用`reset --hard`、强制checkout或随意stash抹掉工作。

Windows正常开发也要先核对工作树，只stage任务相关文件，明确查看diff，再提交并push个人repo；不要使用`git add -A`把交付压缩包、工艺库、未确认的历史文件全部加入。

### 16.2 Ubuntu环境检查与摘要依赖

```bash
# 新shell若conda未初始化，先加载已有Miniforge，不改系统Python。
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
command -v python
command -v bazel
python --version
bazel version
clang --version | head -n 1
verilator --version
conda run -n coral-matrix python -c 'import numpy; print(numpy.__version__)'
conda list -n coral-matrix
```

NumPy缺失时此前文档给出的固定命令：

```bash
conda install -n coral-matrix -c conda-forge 'numpy=2.3.4'
```

不要把此环境安装命令当成“CentOS系统必须装numpy2.3.4”；EDA152的Python3.6/NumPy1.19.5已经用于它的向量脚本。新接手人若重建Conda环境，最好由原VM导出package清单再创建，不从本记录零散版本猜一份完整lock。

已安装环境只读/记录用：

```bash
conda env export -n coral-matrix --from-history
conda list -n coral-matrix --explicit
```

保存输出时注意人工审阅，勿把私有认证URL或其他凭据提交。服务器VCS依赖既有许可环境，本记录不包含license secret，也没有替团队新配置许可服务。

### 16.3 官方生成与基础回归

只在缺生成物、明确需要重建或新配置验证时build；不要为重新写文档生成另一份RTL：

```bash
cd "$HOME/桌面/Coral_matrix/coralnpu-google"
bazel build --jobs=2 \
  //hdl/chisel/src/coralnpu:vme_core_mini_axi_cc_library_verilog
ls -lh bazel-bin/hdl/chisel/src/coralnpu/VmeCoreMiniAxi.sv
```

以下12目标是本轮已有通过记录的集合。为新版本回归可显式运行，不建议盲目`bazel test //...`拉入EDA/FPGA/外部许可测试：

```bash
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=errors \
  //tests/cocotb/vme_test:vme_test_vme_matmul_int8_test \
  //tests/cocotb/vme_test:vme_test_vme_matmul_fp32_test \
  //tests/cocotb/vme_test:vme_test_vme_msettm_matmul_test \
  //tests/cocotb/vme_test:vme_test_vme_load_store_test \
  //tests/cocotb/vme_test:vme_test_vme_msettk_clamp_test \
  //tests/cocotb/vme_test:vme_test_vme_msettm_clamp_test \
  //tests/cocotb/vme_test:vme_test_vme_transpose_test \
  //tests/cocotb/vme_test:vme_test_vme_altfmt_test \
  //tests/cocotb/vme_test:vme_test_vme_decode_test \
  //tests/cocotb/vme_test:vme_test_vme_mset_csr_test \
  //tests/cocotb/vme_test:vme_test_vme_mset_retire_test \
  //tests/cocotb/vme_test:vme_test_vme_vset_mtype_reset_test
```

首次生成/整核编译可能耗时较长并下载数百MiB工具链；保持proxy、磁盘空间、jobs限制。缓存不需要因为每个报错都clean；历史某次939秒构建主要是依赖和首次编译，不是芯片慢。

### 16.4 两套整核速度扫描复现

在同一个Ubuntu clone，运行两个子工程，避免重新把fork独立VCS数字拿来比较：

```bash
cd "$HOME/桌面/Coral_matrix"
conda run -n coral-matrix python verification/check_fullcore_sweep.py
cd coralnpu-google
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=errors \
  //tests/cocotb/vme_test:vme_matrix_speed_sweep_vme_matrix_speed_sweep_test
cd ../coralnpu-Yangg152
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=errors \
  //tests/mxu:mxu_fullcore_speed_sweep_mxu_fullcore_speed_sweep_test
cd ..
conda run -n coral-matrix python verification/compare_fullcore_sweep.py \
  coralnpu-google/bazel-testlogs/tests/cocotb/vme_test/vme_matrix_speed_sweep_vme_matrix_speed_sweep_test/test.log \
  coralnpu-Yangg152/bazel-testlogs/tests/mxu/mxu_fullcore_speed_sweep_mxu_fullcore_speed_sweep_test/test.log
```

7用例Tk1/Tk4/fork三日志的完整流程见[README-fullcore-fair.md](README-fullcore-fair.md)。如果Tk1历史日志丢失，可以重跑对应model-tile测试，而不能编造旧行或用速度sweep日志替换解析器格式。

### 16.5 尚未完成的下一项：fork 权重重载对照

先pull并确认当前代码包含 `c8662a4` 后，再跑**两个**fork目标，确保同版本ELF；别把旧reuse日志和新reload日志配对：

```bash
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git status --short
git pull --ff-only origin main
git rev-parse HEAD
conda run -n coral-matrix python verification/check_fullcore_batch.py
cd coralnpu-Yangg152
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=errors \
  //tests/mxu:mxu_fullcore_shared_weight_batch_mxu_fullcore_shared_weight_batch_test \
  //tests/mxu:mxu_fullcore_shared_weight_batch_reload_mxu_fullcore_shared_weight_batch_reload_test
cd ..
conda run -n coral-matrix python verification/compare_fullcore_batch_reuse.py \
  coralnpu-Yangg152/bazel-testlogs/tests/mxu/mxu_fullcore_shared_weight_batch_mxu_fullcore_shared_weight_batch_test/test.log \
  coralnpu-Yangg152/bazel-testlogs/tests/mxu/mxu_fullcore_shared_weight_batch_reload_mxu_fullcore_shared_weight_batch_reload_test/test.log
```

只有两个目标PASS、解析器通过才接收`[FORK_WEIGHT_REUSE_PAIR]`。新结果应记录HEAD、逻辑hash、total/cycles-per-tile、B重载次数、同核节省周期，然后补本记录的pending状态。

若要重新跨核比较9组batch，官方目标与比较器是：

```bash
cd "$HOME/桌面/Coral_matrix/coralnpu-google"
bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 \
  --cache_test_results=no --test_output=errors \
  //tests/cocotb/vme_test:vme_matrix_shared_weight_batch_vme_matrix_shared_weight_batch_test
cd ..
conda run -n coral-matrix python verification/compare_fullcore_batch.py \
  coralnpu-google/bazel-testlogs/tests/cocotb/vme_test/vme_matrix_shared_weight_batch_vme_matrix_shared_weight_batch_test/test.log \
  coralnpu-Yangg152/bazel-testlogs/tests/mxu/mxu_fullcore_shared_weight_batch_mxu_fullcore_shared_weight_batch_test/test.log
```

### 16.6 EDA152 独立 MXU 工具入口

在server根目录，每个脚本建立新随机运行目录、保留旧结果。不要从Windows PowerShell直接运行这些VCS命令：

```bash
cd /home2/lqq/Desktop/Coral_matrix

# 原始TB四组性能
bash verification/run_yangg152_perf.sh \
  /home2/lqq/Desktop/Coral_matrix /home2/lqq/Desktop/mxu_runs

# 正负/极值压力
bash verification/run_yangg152_signed_stress.sh \
  /home2/lqq/Desktop/Coral_matrix /home2/lqq/Desktop/mxu_runs

# 原生K/输入gap/输出stall；当前DUT预期报告已知失败，不是全PASS基线
bash verification/run_yangg152_boundary.sh \
  /home2/lqq/Desktop/Coral_matrix /home2/lqq/Desktop/mxu_runs

# 补零适配的7模型形状
bash verification/run_yangg152_model_tile.sh \
  /home2/lqq/Desktop/Coral_matrix /home2/lqq/Desktop/mxu_runs

# 多tile、长K累加
bash verification/run_yangg152_layer.sh \
  /home2/lqq/Desktop/Coral_matrix /home2/lqq/Desktop/mxu_runs
```

这些是不同任务入口，按需要单独运行，不表示允许在第一个失败后继续执行整段。边界脚本在控制例通过后故意收集已知失败，用自己的末尾summary/nonzero反映失败；普通回归若失败则先诊断。

脚本默认不启用FSDB或true uint8。需要波形时先配置Verdi PLI并明确磁盘开销；需要unsigned诊断时明知它当前失败，单独运行和归档，不把它混入已通过signed性能baseline。

### 16.7 官方新增功能/阵列测试目标速查

下列target均在 `coralnpu-google` 目录运行同样的 `bazel test --jobs=2 --repo_env=CORALNPU_MAKE_JOBS=2 --cache_test_results=no --test_output=errors <target>`。

| 用途 | Target | 摘要工具（从官方目录用`../verification/`） |
| --- | --- | --- |
| signed诊断 | `//tests/cocotb/vme_test:vme_matrix_perf_vme_matrix_signed_diagnostic_test` | 日志`GOOGLE_MATRIX_PERF/CHECK` |
| 共用原始向量 | `//tests/cocotb/vme_test:vme_matrix_perf_vme_matrix_common_perf_test` | 同上 |
| 阵列普通schedule | `//tests/cocotb/vme_test:vme_matrix_engine_vme_matrix_engine_profile_test` | `summarize_google_array.py <test.log>` |
| 预载同tile burst | `//tests/cocotb/vme_test:vme_matrix_engine_vme_matrix_engine_burst_test` | `summarize_google_array.py --burst <test.log>` |
| signed stress | `//tests/cocotb/vme_test:vme_matrix_signed_stress_vme_matrix_signed_stress_test` | `summarize_signed_stress.py <test.log>` |
| K边界Tk1 | `//tests/cocotb/vme_test:vme_matrix_boundary_vme_matrix_k_boundary_test` | `summarize_google_boundary.py <test.log>` |
| 7模型形状Tk1 | `//tests/cocotb/vme_test:vme_matrix_model_tile_vme_matrix_model_tile_test` | `summarize_google_model_tile.py <test.log>` |
| 7模型形状Tk4 | `//tests/cocotb/vme_test:vme_matrix_tk4_tile_vme_matrix_tk4_tile_test` | 根目录`compare_fullcore_tiles.py`配三日志 |
| 长K/多tile | `//tests/cocotb/vme_test:vme_matrix_layer_vme_matrix_layer_test` | `summarize_google_layer.py <test.log>` |

典型摘要命令：

```bash
conda run -n coral-matrix python ../verification/summarize_signed_stress.py \
  bazel-testlogs/tests/cocotb/vme_test/vme_matrix_signed_stress_vme_matrix_signed_stress_test/test.log
```

独立lane smoke位于`verification/google_zvt_int_lane/{run.sh,tb.sv}`；不要把这个局部入口当成完整官方回归。使用前阅读脚本要求的simulator与参数。

### 16.8 导出、校验与仅更新文档

维护者在Ubuntu导出已有产物：

```bash
cd "$HOME/桌面/Coral_matrix"
python3 verification/export_simulated_google_rtl.py --repo coralnpu-google
```

如果默认已有shared-weight PASS日志缺失，允许明确指定别的已有VME整核PASS日志：

```bash
python3 verification/export_simulated_google_rtl.py --repo coralnpu-google \
  --test-log bazel-testlogs/tests/cocotb/vme_test/vme_matrix_tk4_tile_vme_matrix_tk4_tile_test/test.log
```

这不是重新生成或重新测试。当前组员已经有v2包，不需要再执行导出。接手者应优先复制本轮已核对包，并记录其外层SHA，再在解包根目录运行`verify_export.py --verify .`。

Windows本轮实际校验示例：

```powershell
Set-Location -LiteralPath 'E:\Projects\矩阵二选一'
Get-FileHash -Algorithm SHA256 -LiteralPath 'handoff_output\coralnpu_sim_rtl_20261004_042513_docs_v2.tar.gz'
python verification/export_simulated_google_rtl.py --verify handoff_output/coralnpu_sim_rtl_20261004_042513_docs_v2
python -B -m unittest discover -s verification -p 'test_export_simulated_google_rtl.py' -v
```

只改说明应使用`refresh_simulated_rtl_docs.py`的独立输出流程，先读`--help`与工具测试，不用重新build，更不覆盖原包；当前工作记录的新增本身不改变v2 RTL交付内容。

<a id="section-17"></a>

## 17. 材料清单、日志归档与工作树注意事项

### 17.1 个人仓库内可继续使用的专题文档

| 文档（`verification/`下） | 内容 |
| --- | --- |
| 本记录 `WORKLOG-and-handover.md` | 全程经过、结果、边界、复现、待办 |
| [README-mxu-perf.md](README-mxu-perf.md) | fork基础profile、官方同向量/observer/burst、signed stress结果与hash |
| [README-mxu-boundary.md](README-mxu-boundary.md) | K、input gap、output stall、19失败分类与限制 |
| [README-model-tile.md](README-model-tile.md) | 7种模型形状及padding/软件路线风险 |
| [README-layer.md](README-layer.md) | 多tile/长K分段累加及不同计时口径 |
| [README-fullcore-fair.md](README-fullcore-fair.md) | 7例同端点整核与RVV初始化前提 |
| [README-fullcore-sweep.md](README-fullcore-sweep.md) | 22例同端点扫描执行流程 |
| [README-fullcore-batch.md](README-fullcore-batch.md) | 9组shared B及fork重载对照 |
| [README-simulated-rtl.md](README-simulated-rtl.md) | 已有仿真RTL原样导出简明步骤 |
| [HANDOFF-simulated-rtl.md](HANDOFF-simulated-rtl.md) | 面向综合组员的详细RTL/RAM/AXI/网表回传说明 |

`README-official-sram.md`是本地另存的旧RAM说明，当前整理开始时尚未提交个人仓库。完整RAM交接已经写入已提交的`HANDOFF-simulated-rtl.md`；不能要求新clone后一定存在这份未跟踪文件。

### 17.2 工具按职责分组

- 向量生成：`generate_signed_stress.py`、`generate_mxu_boundary.py`、`generate_mxu_model_tile.py`、`generate_mxu_layer.py`。官方共享向量模块在`tests/cocotb/vme_test/vme_matrix_*_vectors.py`。
- EDA152运行：5个`run_yangg152_*.sh`；独立TB/monitor在`verification/`，核心原RTL仍在fork目录。
- 本地工具自测：`check_google_matrix_vectors.py`、`check_google_array_counter.py`、`check_google_burst.py`、`check_signed_stress.py`、`check_mxu_boundary.py`、`check_model_tile.py`、`check_mxu_layer.py`、`check_fullcore_fair.py`、`check_fullcore_sweep.py`、`check_fullcore_batch.py`。
- 严格摘要/比较：`summarize_*.py`、`compare_fullcore_tiles.py`、`compare_fullcore_sweep.py`、`compare_fullcore_batch.py`、`compare_fullcore_batch_reuse.py`；拒绝不全重复、hash不对、输出不全、不稳定周期等。
- 当前RTL交付：`export_simulated_google_rtl.py`、`refresh_simulated_rtl_docs.py`、`test_export_simulated_google_rtl.py`。
- 历史prod工具：本地`verification/rtl_handoff/`和团队候选`codex/rtl-handoff`，只作历史参考，不替代当前仿真包。

### 17.3 服务器已报告运行目录

```text
/data/home2/lqq/Desktop/mxu_runs/Yangg152_perf.7x8re7
/data/home2/lqq/Desktop/mxu_runs/Yangg152_signed_stress.f9j80n
/data/home2/lqq/Desktop/mxu_runs/Yangg152_boundary.8KOTaG
/data/home2/lqq/Desktop/mxu_runs/Yangg152_model_tile.oP53jp
/data/home2/lqq/Desktop/mxu_runs/Yangg152_layer.gPjV4B
```

各脚本的新运行会创建新随机目录，不应用本记录目录名作为新输出目标。保留compile.log、run/stdout日志、vectors.log、vectors/manifest.json、HEX、源hash和HEAD。未来完整交接应从server实际确认这些历史目录仍存在并拷出，本文没有在2026-10-04远程重新遍历确认。

### 17.4 Ubuntu 日志备份规则

`bazel-testlogs`是指向Bazel输出树的链接，同target重新运行可能覆盖旧`test.log`。Git clone不会带这些文件；另一个子工程的Bazel cache/output base也不同。当前比较仓库有多个历史日志路径，不等于用户打包时已包含所有日志。

建议在下一轮测试**之前**做一次独立日志快照。以下新建时间戳目录，只复制已存在材料，不删除原文件；这是交接建议，不是声称过去已执行：

```bash
cd "$HOME/桌面/Coral_matrix"
log_snapshot="$HOME/coral_matrix_logs_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$log_snapshot"
git rev-parse HEAD > "$log_snapshot/revision.txt"
git status --short > "$log_snapshot/worktree.txt"
for variant in coralnpu-google coralnpu-Yangg152; do
  if [ -d "$variant/bazel-testlogs" ]; then
    cp -aL "$variant/bazel-testlogs" "$log_snapshot/$variant-testlogs"
  fi
done
printf '日志快照：%s\n' "$log_snapshot"
```

目录若已有同名需换新名字，磁盘不足则先按target挑选必要日志。更正式报告还应记录源文件/ELF/生成RTLhash、bazel version与执行命令，覆盖未来的可追溯缺口。

### 17.5 当前 Windows 工作树未提交材料

本次整理开始时除已提交`e3046dc`之外还有：

```text
 M .gitignore
?? coralnpu_sim_rtl_20261004_042513.tar.gz
?? verification/README-official-sram.md
?? verification/rtl_handoff/
```

本地`handoff_output/`包含原包接收解压、docs_v2、旧prod及多个CI中间artifact，不作为源代码正常Git上传。这个目录和`.upstream-git/`等有本地ignore配置；不要替接手人强行清理掉，也不要只clone后假定能找到压缩包。

本次只新增工作记录及README入口，不把上述材料混进新提交、不修改交付RTL或其压缩包。正式工作交接还要以团队允许的文件通道单独发送推荐包和完整测试证据，并保存校验值。

<a id="section-18"></a>

## 18. Git 提交索引：定位任一步是怎么引入的

下面是个人比较仓库截至`e3046dc`的实际历史。要查看具体改动用`git show <hash>`；不要通过checkout/reset覆盖当前未提交工作。

| 日期 | Commit | 说明 |
| --- | --- | --- |
| 09-26 | `403c4f1` | 两工程初始导入 |
| 09-26 | `a9f180e` | 恢复上游执行位与symlink |
| 09-26 | `fecb9e2` | FSDB dump可选 |
| 09-26 | `2ed9808` | opt-in true uint8诊断 |
| 09-26 | `75a98e9` | 官方ZVT integer lane smoke工具 |
| 09-29 | `519ac9b` | fork MXU performance monitor |
| 09-29 | `2113cf3` | 官方同向量和signed诊断 |
| 09-29 | `2faf6a8` | 官方阵列只读cycle observer |
| 09-29 | `ffb6b35` | 预载同tile连续指令stream |
| 09-29 | `4f03352` | burst结果与shared signed stress |
| 09-30 | `a0a0183` | server压力PASS和NumPy依赖说明 |
| 09-30 | `37b2ddb` | paired stress PASS，K/stall诊断 |
| 09-30 | `71b0d39` | K与输出停顿失败结果 |
| 09-30 | `4c60c9b` | 跨主机K向量hash相同 |
| 09-30 | `5979381` | 7模型形状tile |
| 09-30 | `6026d2e` | 长K与多tile |
| 09-30 | `8dc4b1e` | paired整核signed tile基准 |
| 09-30 | `62f3472` | fork rules_java兼容pin |
| 09-30 | `596291b` | WORKSPACE compatibility_proxy顺序 |
| 09-30 | `6664a44` | 允许可选checked-in ELF glob |
| 09-30 | `3e61d23` | 提前固定skylib |
| 09-30 | `ec67d8e` | 直接用CcToolchainInfo |
| 09-30 | `b941151` | wheel中可选cocotb文件 |
| 09-30 | `4219431` | Bison filegroup属性兼容 |
| 09-30 | `004b81a` | 可选本地firtool glob |
| 09-30 | `4232dfe` | fork rules_proto兼容版本 |
| 10-01 | `6585db4` | 可选HDL扩展glob |
| 10-01 | `5804830` | Verilator runfiles root |
| 10-01 | `e71664f` | runner Python runfiles路径 |
| 10-01 | `327519c` | runner兼容补丁整理 |
| 10-01 | `85d8a6d` | cocotb VPI库runfiles定位 |
| 10-01 | `d22fd8f` | fork故障CSR报告 |
| 10-01 | `58cd3dc` | 捕获首次异常 |
| 10-01 | `3ff8203` | MXU指令前初始化RVV状态 |
| 10-01 | `c79d7de` | 整核tile基准完成 |
| 10-01 | `42a2610` | 22case speed sweep |
| 10-01 | `95e8415` | 单启动shared-weight batch |
| 10-01 | `b6e0792` | 大batch buffer放external BSS |
| 10-01 | `c8662a4` | fork每tile重载权重对照 |
| 10-04 | `887181e` | 原样导出已有仿真RTL |
| 10-04 | `e3046dc` | 详细综合/RAM交接，doc-only更新 |

这份记录是在该历史基础上新增，未来提交hash不会反向改变已导出包的源码/RTL身份。不同仓库的commit号互不替代。

<a id="section-19"></a>

## 19. 早期选型/RTL交付验收清单与更新约定

下列为10月4日原始检查清单，供复核历史工作；当前接手使用[HANDOFF-current.md](HANDOFF-current.md)的清单，不自动恢复fork比较任务：

- [ ] 有个人比较仓库权限，知道团队SoC与候选仓库不是同一仓库。
- [ ] 保存Windows当前修改和未跟踪交付材料，没有误clean/reset。
- [ ] 能进入Ubuntu `coral-matrix` 环境，确认Bazel、proxy和两个子工程路径。
- [ ] 能进入EDA152自己的账号、VCS许可环境和运行目录；SSH22/远程桌面3390不混用。
- [ ] 拿到当前docs_v2 RTL包，整包SHA匹配，262文件校验通过。
- [ ] 知道外部取指true、8/32KiB、完整VmeCoreMiniAxi，是原仿真配置；旧prod包不混用。
- [ ] 已保存或列明缺失的历史完整日志、向量manifest、提交与工具版本。
- [ ] 理解fork已知uint8/K/stall失败仍未解决，补零通过不代表原生修复。
- [ ] 比速度用fullcore同端点日志，记录driver/padding/reuse/内存条件；不把模拟器秒数当芯片性能。
- [ ] 明确下一项pending是fork权重重载对照，或由团队指定新的优先级。
- [ ] 综合人员收到RAM/clock/接口说明，并承诺回传网表、SDC、库模型与报告，而非只传一个`.v`。
- [ ] 团队决策事项有责任人/待讨论时间，200MHz仍写为目标，不写已达标。

以后每次新增结果至少写：日期、执行机器、repo完整HEAD/工作树、target/命令、工具版本、输入与golden hash、RTL/ELF身份、PASS/FAIL与输出数、性能边界、完整日志路径、遗留问题。失败结果也保留，修复前后并列；不要用最后一次PASS覆盖最初失败的机制与契约。

本记录不包含密码、Git token、私钥、商业license或PDK。后续交接权限与机密材料由团队既有流程处理。

<a id="section-20"></a>

## 20. 2026-10-04之后：任务切换及新增时间线

### 20.1 已确定的范围变化

1. 用户明确告知：团队已选官方矩阵版本，后续不再考虑Yangg152。
2. 用户明确告知：团队已把一个NPU集成进SoC并跑通测试，之后计划四个NPU。这里记录团队进展，不把它冒充本实验的SoC回归证据。
3. 用户当前任务是比较**单NPU**不同ITCM/DTCM规格的性能；“2M/4M”在讨论中明确为**每个DTCM的2/4MiB**，不是Mbit，也不是两块TCM之和。
4. 先固定ITCM8KiB、只扫DTCM；短暂提出ITCM扩容后，用户又要求暂缓ITCM，回到DTCM并尝试服务器Verilator。

fork既有uint8、K、输出停顿失败保留，未授权修复，也不再是接手后的必跑任务。原比较结果仍可用于解释选型过程，不再用来选择另一条主线。

### 20.2 新阶段时间线

| 日期/阶段 | 工作与关键版本 | 实际结果或边界 |
| --- | --- | --- |
| 10-14 | `a70f238`：读取团队较新官方基线及两个补丁，建立独立DTCM容量实验 | 不覆盖早期870版本，不修改团队SoC源码 |
| 10-15 | HTTPS凭据/PAT pending问题后改SSH；`430551f`；关闭刷屏进度`1c68076` | 私有仓库读取用于提取补丁；密钥口令是本人设置值，不是服务器密码 |
| 10-15～16 | 六档DTCM前门几何检查；随后加入同ELF计算控制组 | 六档均PASS；完整控制日志比较器PASS |
| 10-16 | `128b077`：用Bazel cquery解析经过配置转换的RISC-V ELF位置 | 修复build成功后按错误bazel-bin路径复制ELF失败；不用伪造或手拷未知ELF |
| 10-16 | `ddf2efa`：增加固定输入优先权重驻留、CSR阶段计数和AXI观察器 | 两策略、各3次，完整输出和流量判据 |
| 10-16 | `deb148c`：cocotb超时单位修复；`181ba52`：局部忽略Python缓存 | 精确识别旧版本、备份迁移；不隐藏真实源码改动 |
| 10-16～17 | 32/128KiB及1MiB的T12实际运行与配对 | 32→128KiB同prefix策略少29.32%周期；1MiB在此小负载没有额外驻留收益 |
| 10-17 | 首次1MiB/T384遇Bazel一小时墙钟上限；`6a1f175` | 原运行INCOMPLETE；保存部分日志，未拼成PASS。后续显式6h/24h保护 |
| 10-17 | `088b836`：Ubuntu只生成RTL/固件并导出独立VCS包 | 1/2/4MiB均导出、字节核对；不是VCS仿真PASS |
| 10-17 | `d34fa2e`：旧VCS elaboration选项；系统/Conda编译器隔离 | 1MiB VCS模型60.523秒编译PASS，RTL及原SRAM源码未改 |
| 10-17 | `23afde9`、`760bda8`：SGR颜色与ELF容器类型兼容 | 原T12无需重跑即可严格验收；不是删掉失败记录或改golden |
| 10-17～18 | VCS T12正常测速、Python profiling、资源采样 | 正常流程约1178.5秒；profiling单独约1403.893秒，不混作速度基线 |
| 10-18 | 服务器1MiB/T384夜间运行 | 完整PASS，流程37619.46秒；原始6条结构化记录及完成标记已回传 |
| 10-18 | Windows自动关机导致VM重启 | 首次VM夜间任务中断，旧日志不能当PASS；之后新目录从头运行 |
| 10-18 | Ubuntu顺序重跑1/2MiB、T384 | 两档均完整PASS；比较器输出1.205785周期比，队列17:20:45全部通过 |
| 10-18 | 服务器2MiB传输、编译和T12 pilot | 编译54.893秒、T12流程1187.676秒，完整PASS |
| 10-18 | 服务器2MiB/T384夜间任务启动 | 启动13:28:53；截至本次整理未收到最终结果，不能推定运行状态 |
| 10-18 | `9019d91`：独立ITCM几何工具 | 本地14项PASS；没有用户RTL执行结果，随后暂停 |
| 10-19 | 安装`coral-verilator`，`92937fe`：包外独立入口 | glibc2.17上环境基本检查PASS，1MiB模型434.214秒编译PASS |
| 10-19 | 首次服务器Verilator T12退出255；`c0b4b76`修复WAVES/GUI | 1.777秒、未超时；本地25项PASS，失败日志保留 |
| 10-19后续回传 | 修复后Server Verilator1MiB/T12完整PASS | 原模型只读复用，VCS参考EXACT，429.077秒；同服务器当前T12流程比VCS观察快约2.75倍 |
| 后续回传 | Server Verilator1MiB/T384完整PASS | 复用原模型，VCS参考EXACT，13979.842秒；同服务器比VCS流程观察快2.69倍，VM流程仍更快 |

没有因为夜间任务后台运行就减少验证次数；无checkpoint，断电后必须重跑完整六次，而不是把残缺日志拼接成完整证据。

<a id="section-21"></a>

## 21. 新官方实验基线、内存组织和测量契约

### 21.1 与10月4日RTL包分开锁定

| 身份 | 固定值 |
| --- | --- |
| 官方源码 | `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a` |
| 团队补丁来源提交 | `95e06e872bff13b3625721a837b4b739a93bed6f`，团队SoC仓库 |
| 补丁1 | `rtl/npu-generator-patches/0001-order-core-csr-addresses.patch` |
| 补丁1 SHA256 | `a3cb2de716d3c14c1675ddf5ff638af6ac96b159a8f1cb0859bbd03da8b93acc` |
| 补丁2 | `rtl/npu-generator-patches/0002-fix-cvfpu-sticky-width-at-source.patch` |
| 补丁2 SHA256 | `9bf28f7f33038ceb4c808910cde4da25d94a9bdea207bf4e664dabc7b1ef615b` |
| 实验目录 | `/home/lqq/coral_tcm_capacity_8e4_v1` |
| 官方源码实验副本 | 上述目录的`source/`，固定上游后应用受控实验变更 |
| 团队Git对象 | `team.git`，用于读固定补丁，不是运行整个SoC |
| Bazel | 9.1.0，实验目录内独立二进制及`bazel-user/`缓存 |

上游提交、团队提交、个人工具提交、生成SV哈希、ELF哈希是五种不同身份；任何一个不能代替另外几个。10月4日`870993f7`的8/32KiB docs_v2综合交付包继续保留原身份，不因为本轮更新文档就变成`8e4df09b`的MiB级实验包。

### 21.2 地址和参数

| 区域 | 当前单核实验地址/容量 | 说明 |
| --- | --- | --- |
| ITCM | `0x00000000`起，8KiB | 程序装入前完整NOP填充；性能窗口不含主机装载 |
| DTCM | `0x01000000`起，32～4096KiB | 4MiB末地址`0x013FFFFF` |
| CSR | `0x02000000`起 | 统一避开所有DTCM档位；不是旧包`0x30000` |
| fixture外部存储 | `0x20000000`起，16MiB backing | 主机NumPy代理，不是片上SRAM或DDR规格 |

原高容量默认图的DTCM与CSR不适合本轮2/4MiB容量直接共用，实验统一修改生成入口和linker地址。**这些地址不是建议直接覆盖团队SoC全局地址图**；真实SoC窗口、路由、软件和启动协议需另行同步。

其他参数：XLEN32、VLEN128、AXI数据128bit/ID6bit、fetch/LSU128bit，RVV/VME/FP/BF16开启，verification=false、AXI外部取指=true、FetchL0=false。行为RAM仍按一周期响应。每个逻辑bank为512×128bit、8KiB、1RW、16bit字节mask；DTCM六档分别4/16/64/128/256/512个bank。扩大bank数不是增加同等数量的独立端口，也不是已经找到对应的大容量工艺宏。

### 21.3 三阶段为什么必须分开

1. **前门几何**：核停止，经AXI访问每个8KiB DTCM bank首/中/尾与mask。验证抽样地址不镜像，不启动计算，不是性能测试或March/MBIST。
2. **同ELF小常驻控制**：低32KiB放得下的相同数据，前门预载，比较相同程序/输入。验证改变容量本身没有让这一小窗口改变周期，不能推出大模型不需要容量。
3. **跨容量工作集**：不预载正式权重到DTCM，由NPU自己通过CPU向量load/store搬运。固定调度和外部代理，观察多保留权重能省多少真实AXI事务及执行周期。

### 21.4 T12、T384、T768与重复次数

`T`是**不同权重块数**，不是K、测试编号或重复次数。K始终256，每个B块256×16 INT8=4096字节。三个不同A块各16×256，程序顺序为输入轮次在外、权重块在内；总逻辑形状M48、N=16T、K256。

| 名称 | 权重集 | M/N/K | 每次输出INT32元素 | 每次有用MAC |
| --- | --- | --- | ---: | ---: |
| T12 | 48KiB | 48/192/256 | 9216 | 2359296 |
| T384 | 1.5MiB | 48/6144/256 | 294912 | 75497472 |
| T768 | 3MiB | 48/12288/256 | 589824 | 150994944 |

两策略为stream和prefix_cache；每个策略独立复位重复3次，每次程序内又有3个输入轮次。完整一档是6次运行，T384共检查1769472个输出元素，不能把“3个round”误作“3份独立重复”。

低DTCM16KiB留给软件、输入/输出暂存与栈。剩余4KiB槽数`S=(DTCM字节数-16384)/4096`。prefix若能全容纳则驻留T块，否则驻留`S-1`块、留一个流式槽；三轮权重读取量为`4096×(T+2×(T-R))`。因此1MiB/T384驻留251块，2MiB/T384驻留384块；2MiB/T768预计507块，4MiB/T768预计768块。后两个是静态计划，不是实际PASS。

### 21.5 不可放宽的验收和性能边界

每次检查完整输出、ELF/段/符号、向量SHA、CSR阶段及轮次计数、AXI请求/响应/实际有效字节；所有3次重复必须稳定，有完整完成标记和XML无FAIL/SKIP。输出读回/主机初始化不计入等待halt窗口；正式权重/输入搬运、计算、外部输出属于该窗口。阶段计数含软件/CSR/fence开销，阶段之和不要求恰等于总周期。

同频、同负载时可用NPU周期比较；模拟器墙钟仅用于安排仿真资源。固定输入优先不是最优模型调度：当前输入总共只有12KiB，重排循环或缓存多输入可能让小DTCM少读权重。实验有意固定策略，不据此断言所有模型必须2/4MiB。

<a id="section-22"></a>

## 22. 新阶段实际结果汇总（截至2026-10-19）

证据来自用户回传的Linux终端摘要和保存的粘贴日志；本次复查了这些附件中的原始记录，但没有直接登录两台Linux遍历磁盘。完整文件仍须按下述路径交接，不能说个人仓库已带齐全部测试报告。

### 22.1 六档几何及小常驻计算

六档DTCM32/128/512/1024/2048/4096KiB均前门几何PASS；同ELF小控制也均PASS，K16/64/256及极值K16周期分别414/702/1854/414。每档4例×3次×256输出，六档合计72次、18432元素。六份完整日志比较PASS，文件`/home/lqq/coral_tcm_capacity_8e4_v1/control_compare.L0Pxte.log`。

完整目录见[STAGE1-results.md](google_tcm_capacity/STAGE1-results.md)和[CONTROL-results.md](google_tcm_capacity/CONTROL-results.md)。控制ELF为`8e2032348a4148ea22cf2b0c5010aad8bb0e148047c09099fc0f5f8535815ed8`，不要与工作集ELF混用。

### 22.2 工作集数据身份

| 材料 | SHA256 |
| --- | --- |
| 共同工作集ELF | `a8aa2d6feaefd56a5901f8bcca4f8f6bbf5394932add092243aff8f5eb497192` |
| T12输入/golden | `5f48b97cefb656ad1e4a96dc80a3f42804ed86d9c0553dade288d14519ebeb93` |
| T384输入/golden | `e32a9e3d4b09c5dae8706a34fbc35f061b60d78d146e49861c31f728ee08fe0d` |

ELF装载段为ITCM从0起1664字节、DTCM从`0x01000000`起16384字节；运行时权重池利用更高DTCM地址，固件不是按每档重新链接。

### 22.3 T12：小权重集已饱和，不能替代MiB级测试

| 执行环境 | DTCM | stream等待halt | prefix等待halt | prefix外部权重字节 | 状态 |
| --- | ---: | ---: | ---: | ---: | --- |
| Ubuntu Verilator | 32KiB | 225219 | 205177 | 122880 | PASS |
| Ubuntu Verilator | 128KiB | 225219 | 145026 | 49152 | PASS；与32KiB完整日志比较PASS |
| Ubuntu Verilator | 1MiB | 225222 | 145029 | 49152 | PASS |
| EDA152 VCS | 1MiB | 225222 | 145029 | 49152 | 初次验收及正常复测均PASS |
| EDA152 VCS | 2MiB | 225226 | 145033 | 49152 | PASS |
| EDA152 独立Verilator | 1MiB | 225222 | 145029 | 49152 | 修复后完整PASS、VCS精确参考匹配，429.077秒 |

32→128KiB同prefix策略周期少29.3166%，权重字节少60%；stream完全相同。128KiB已经能全部保存T12权重，更大容量的同一测试没有额外权重收益。1MiB与128KiB、2MiB与1MiB之间，内部CSR计数、轮次和AXI数据相同，等待halt窗口分别多3/4周期；只知道差异位于该CSR窗口之外，原因未定位，不擅自校正，也不解释为阵列或SRAM物理频率变化。

### 22.4 T384：Ubuntu1/2MiB完整配对

| 指标 | 1MiB stream | 1MiB prefix | 2MiB stream | 2MiB prefix |
| --- | ---: | ---: | ---: | ---: |
| pool槽数 | 252 | 252 | 508 | 508 |
| 驻留权重块 | 0 | 251 | 0 | 384 |
| 等待halt周期 | 6885516 | 5208090 | 6885520 | 4319251 |
| 内部总CSR周期 | 6885263 | 5207833 | 6885263 | 4318994 |
| 输入阶段周期 | 10002 | 10002 | 10002 | 10002 |
| 权重阶段周期 | 3852288 | 2177114 | 3852288 | 1289472 |
| 计算及读出周期 | 1930752 | 1930752 | 1930752 | 1930752 |
| 输出阶段周期 | 1028736 | 1028736 | 1028736 | 1028736 |
| 第0轮周期 | 2295074 | 2295828 | 2295074 | 2296227 |
| 第1/2轮各周期 | 2295074 | 1455982 | 2295074 | 1011363 |
| 外部权重读取字节 | 4718592 | 2662400 | 4718592 | 1572864 |
| AXI完成读字节 | 4730880 | 2674688 | 4730880 | 1585152 |
| AXI读事务/拍数 | 295680 | 167168 | 295680 | 99072 |
| AXI写事务/拍数 | 73728 | 73728 | 73728 | 73728 |

四列输入均12288字节、输出均1179648字节，每次294912元素检查；ELF与T384向量SHA相同。Ubuntu结果目录：

```text
/home/lqq/coral_tcm_capacity_8e4_v1/workset_d1024_t384_r0.AMFGqg
/home/lqq/coral_tcm_capacity_8e4_v1/workset_d2048_t384_r0.xymg0S
/home/lqq/coral_tcm_capacity_8e4_v1/overnight_vm.Qy9tDJ/console.log
```

1MiB于10月18日14:51:40结束，2MiB及配对队列于17:20:45全部通过。比较器回传同prefix策略周期比`1.205785`：1→2MiB少888839周期，减少**17.0665%**；外部权重少1089536字节，减少**40.9231%**。第1/2热轮次各少30.5374%；总窗口含首轮冷加载，因此不能把热轮改善当完整运行加速比。

1MiB的stream/prefix内部策略比较少24.36%周期；2MiB的内部策略比较少37.27%。这些不是容量比较的17.07%，不要混报。2MiB stream比1MiB等待窗口多4周期，但内部总CSR和各阶段不变，同样保留差异，不凭空解释。

### 22.5 同配置VCS结果与还未完成的矩阵

服务器1MiB/T384完整6条记录的周期、CSR、AXI、数据身份与Ubuntu1MiB摘要一致，已收到`TCM_VCS_RUN_PASS`和`OVERNIGHT_ALL_PASS`。日志在：

```text
/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_runtime/runs/t384_r0.pyg9qm5e
```

服务器2MiB/T384仅收到`/home2/lqq/coral_vcs_tools/overnight_vcs.TdW8Yk`、10月18日13:28:53启动、当时launcher PID344971；PID只是历史定位线索，不能拿它现在直接kill。查完成日志后才更新结论。

| 尚无完成证据的项目 | 状态 |
| --- | --- |
| EDA152 VCS 2MiB/T384 | 已启动，最终结果未回传；不是断言当前还在运行 |
| EDA152 独立Verilator2/4MiB、T768 | 尚无实际PASS；各包须先自己的T12；1MiB T384已完成 |
| T768的2/4MiB容量配对 | 尚未进行，不能从T384推导4MiB收益 |
| 附加读延迟8周期配对 | 尚无完整PASS，只有0等待结果 |
| 真实AI模型、四NPU竞争、物理SRAM/PPA | 当前实验未验证 |

<a id="section-23"></a>

## 23. 服务器独立仿真：包、环境及修复经过

### 23.1 导出与复用原则

Ubuntu只负责生成并核对对应容量的SV/ZIP/参数头、共同ELF和原始SRAM/fixture源码。传给CentOS后**本地编译模型**，不运行Bazel，也不搬Ubuntu仿真可执行文件来赌glibc兼容。每种容量一个RTL包、一个或多个独立构建身份；同包改变T或读延迟可复用模型，但源码/参数/编译环境/可见性变化必须重新审查身份。

| DTCM | Ubuntu导出目录后缀 | 原归档SHA256 | 服务器状态 |
| --- | --- | --- | --- |
| 1MiB | `vcs_export_d1024.yzU5z6` | `0e969183cd48d3f7a9eaa062e31aded9d89b011fa8fcddee58febd69823b8cb8` | 已传输；VCS及独立Verilator已编译，运行状态见第22节 |
| 2MiB | `vcs_export_d2048.T5HEGi` | `499a7c31d97d06cb39ff8dcebe1ac2c6232605943d044af5d2eaa83ebe27d768` | 已传输并VCS编译/T12通过；T384完成证据待回传 |
| 4MiB | `vcs_export_d4096.W2JmMH` | `272a4e81560856660801d9c7dbcf28b40d8d290b3d1886395aa5f0c46d5269a5` | 仅确认Ubuntu导出，不声称服务器已有 |

归档名为`coral_tcm_vcs_d<KiB>.tar.gz`，路径和组成见[EXPORT-results.md](google_tcm_vcs/EXPORT-results.md)。包名含vcs不限制其源码给Verilator使用。包内`vcs_simulation=NOT_RUN`是**导出时**事实，后续仿真结果写包外，不修改旧manifest来宣布通过。

### 23.2 服务器三个互不混用的环境

| 环境 | 用途 | 已确认工具 |
| --- | --- | --- |
| 系统CentOS7 | VCS生成C代码构建 | glibc2.17；`/bin/gcc`、`/bin/g++`4.8.5 |
| `$HOME/coral_vcs_tools/miniforge3/envs/coral-vcs` | VCS+cocotb及独立SRAM DPI C++17 | Python3.11.9；Conda GCC/G++15.3；cocotb2.0.0、NumPy1.26.4、pyelftools0.32、find-libpython0.5.1 |
| 同Miniforge下`coral-verilator` | 独立Verilator模型编译/运行 | Python3.11.17；Verilator5.052；Conda GCC/G++15.3；make4.4.1；同四个Python依赖版本 |

VCS构建时系统PATH优先，但先保存Conda Python和SRAM DPI G++绝对路径；DPI独立使用C++17/匹配VCS DPI头，不用GCC4.8硬编原SRAM源码。Verilator则用Conda新版GCC/G++及Verilator自己的DPI头，不套VCS的系统编译器PATH，也不加载VCS DPI SO。新版Conda库安装在用户目录，没有替换系统glibc；原生Bazel不兼容问题仍由导出方案绕开。

两边都是编译型仿真流程；不能解释成“VCS解释执行、Verilator编译执行”。同一原SRAM C++存储语义、同一Python时钟策略及完整输出判据保留，不能为提速改SYNTHESIS、初始化全零、删断言或减少重复。

### 23.3 故障、原因、修复与尚缺的验收

| 现象 | 定位/修复 | 目前证据 |
| --- | --- | --- |
| 私有团队仓库HTTPS认证失败、403/pending | 不用账号密码当PAT；最后采用SSH及本地私钥代理读取固定补丁 | 已能建立实验；不包含凭据，不能把SSH私钥口令当服务器密码 |
| build成功后找不到`control_program.elf` | 配置转换改变实际输出路径，改cquery+ELF32/RISC-V身份验证 | 六档控制组后续PASS |
| cocotb超时单位`s`非法 | 改`2000ms`；严格识别旧SHA后备份迁移 | 后续T12/T384通过，不回写旧失败日志 |
| T384只跑出两条stream后Bazel TIMEOUT | `eternal`仍有默认1h上限；显式6h/24h并保留退出/原始日志 | 完整新目录重跑后PASS，部分旧运行仍INCOMPLETE |
| VCS elaboration `$fatal`要求选项 | 加`-assert svaext`，为旧包新建`svaext_v1`副本 | 原RTL/固件不变；后续VCS构建PASS |
| rmapats.c隐式函数声明被新版GCC当错误 | VCS内部C构建实际受PATH默认编译器影响，改系统GCC优先；保留Conda DPI C++ | 1/2MiB VCS构建PASS；不修改VCS生成C文件 |
| VCS T12 `Extra data` | JSON末尾SGR颜色复位码；包外严格解析器仅去显示边界颜色 | 复用旧运行验收PASS，原日志不改 |
| 首版ANSI入口仍报ELF/layout不匹配 | 元组/列表表示差异；统一容器表示，不放宽地址/长度/hash | `760bda8`入口验收PASS |
| Verilator T12 `--trace requires...` | 旧入口WAVES/GUI字符串0被cocotb2当真；`c0b4b76`移除变量 | 本地25项PASS；后续Server T12完整PASS，旧失败不覆盖 |

1MiB原包保留，VCS升级副本是`coral_tcm_vcs_d1024_svaext_v1`。VCS状态在`..._runtime`，独立Verilator状态在`..._verilator_runtime`，不相互覆盖。旧VCS ANSI入口是包外`/home2/lqq/coral_vcs_tools/ansi_fix_v2.bzKDlm/vcs_workset.py`，SHA为`e2668cd25e690177dea89087f4804b7fb4a426c8c9e8a2a2d19c9effb04999f0`。

### 23.4 Verilator原trace故障与模型复用身份

```text
包：/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1
已通过构建：同级 coral_tcm_vcs_d1024_svaext_v1_verilator_runtime/builds/e6ab26657e58.xbhdmzuj
首次失败运行：同级 coral_tcm_vcs_d1024_svaext_v1_verilator_runtime/runs/t12_r0.zl1315rn
原入口：/home2/lqq/coral_vcs_tools/verilator_runner.JdVpsd/verilator_workset.py
原控制台：/home2/lqq/coral_vcs_tools/verilator_pilot.fenT2T.log
```

初次编译434.214秒PASS；失败运行`_test-status.json`记录exit_code255、timed_out=false、elapsed_seconds=1.7773396475240588。新脚本提交`c0b4b76098a88d5bace3c3fbdcef318c10e924f7`，脚本SHA256为`9031f22eadbfc75d308f2bcd67bde9b943b06822ccbbe8da702b821112273855`。

修复入口仅允许在完整旧构建身份/包/环境、二进制与编译命令/visibility哈希、成功构建状态全部一致时只读复用前版模型；保留实际旧build_identity和当前运行adapter_sha256，不改旧指针或伪造重编。新运行需匹配同容量VCS参考`..._runtime/runs/t12_r0.mraudje0/_test.log`，逐项核对周期/CSR/AXI/ELF/向量。必须同时有REFERENCE_MATCH及RUN_PASS才解锁大测试，未知差异立即停止。

### 23.5 2026-10-19后续回传：Server Verilator T12正式通过

实际入口`/home2/lqq/coral_vcs_tools/verilator_trace_fix.S7nNd7/verilator_workset.py`，控制台同目录`console.log`；脚本SHA仍9031f22e开头的固定值。新运行目录：

```text
/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_verilator_runtime/runs/t12_r0.fmvgge7f
```

用户回传BUILD_REUSED、RUNTIME_FIX、两条完整SUMMARY、`REFERENCE_MATCH cycles_counters_axi_elf_vectors=EXACT`及`RUN_PASS simulation_wall_seconds=429.077`。两策略各3次、共55296输出检查，stream225222周期、prefix145029周期；CSR总224975/144782，权重外读147456/49152字节，AXI读拍9984/3840、写2304，其他阶段/轮次、ELF和向量均与原VCS参考完全相同。

模型`e6ab26657e58.xbhdmzuj`、包与构建记录没有因修复而更改；434.214秒编译另计，不计入429.077秒运行墙钟。本结果确实完成严格外层验收，不是从编译或本地单元测试推断。

同服务器当前T12配置中，对比正常VCS wrapper1178.5秒，观察速度比2.74659、墙钟少63.5913%。不是同一时刻/主机负载控制试验，不宣称纯仿真内核或所有模型比值；后来T384也已通过，见下一节，T768/其他容量仍需自己的模型和T12。

### 23.6 后续回传：Server Verilator1MiB/T384完整PASS

控制台`/home2/lqq/coral_vcs_tools/verilator_t384.ydMKyr.log`；新运行完整路径：

```text
/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_verilator_runtime/runs/t384_r0._66rc55e
```

`_66rc55e`中的下划线是实际后缀字符。已回传BUILD_REUSED/RUNTIME_FIX、两条完整SUMMARY、REFERENCE_MATCH=EXACT和RUN_PASS=13979.842秒。1MiB原模型/构建记录未改，编译不计入本次墙钟；同ELF、T384向量、ITCM8KiB、附加读等待0。

两策略各3次、每次294912个输出，合计1769472元素检查。stream等待6885516、CSR总6885263、权重阶段3852288周期、权重外读4718592字节；prefix等待5208090、CSR总5207833、权重阶段2177114、驻留251块、权重外读2662400。输入/计算/输出阶段、轮次和全部AXI事务/拍/有效字节与VCS参考完全一致。

当前Server Verilator约3h53m；同服务器VCS37619.46秒约10h27m，观察快2.69098倍，墙钟少62.8388%。VM同容量Bazel test6736.5秒约1h52m，比服务器Verilator流程观察快2.07524倍；机器、当时负载及少量计时边界不同，不当纯CPU/引擎基准。本次/T12墙钟比32.5812接近32倍tile数，但不保证其他容量或T768同比增长。

这次是已知1MiB工作集的后端交叉验证，不是新的扩容收益。当前不再重跑1MiB，转向2/4MiB T768前置；先用已有2MiB包/VCS T12日志建立该容量Verilator模型并验收。4MiB服务器传输/运行未确认，不能复用1MiB前置。可执行入口见[当前指南](HANDOFF-current.md#server-verilator-2m-pilot)。

<a id="section-24"></a>

## 24. 主机仿真速度调查、后台任务与网络可靠性

### 24.1 已测墙钟：不等于NPU性能

| 执行环境/配置 | 测试墙钟 | 构建/边界说明 |
| --- | ---: | --- |
| Ubuntu Verilator 1MiB/T12 | Bazel test 292.4秒 | test命令elapsed299.707秒；RTL/固件此前另构建 |
| EDA152 VCS 1MiB/T12正常复测 | wrapper1178.5秒；cocotb1172.38秒 | 编译60.523秒另计；profiling关闭 |
| EDA152 VCS 1MiB/T12 profiling | wrapper1403.893秒 | 开销分析用，不作正常速度基线 |
| EDA152 VCS 1MiB/T384 | wrapper37619.46秒；cocotb37605.01秒 | 约10h27；完整运行PASS |
| Ubuntu Verilator 1MiB/T384 | Bazel test6736.5秒 | 约1h52m；command elapsed6739.349秒 |
| Ubuntu Verilator 2MiB/T384 | Bazel test8789.0秒 | 约2h26m；command elapsed8940.854秒含新模型动作 |
| EDA152 VCS 2MiB/T12 | wrapper1187.676秒 | 编译54.893秒另计 |
| EDA152独立Verilator1MiB/T12 | wrapper429.077秒；复用原模型 | VCS精确参考匹配；编译434.214秒另计，首次失败另存 |
| EDA152独立Verilator1MiB/T384 | wrapper13979.842秒，约3h53m | 同原模型，VCS参考EXACT；不是NPU计算时间 |

VCS/VM的T384观察墙钟比约5.58，但CPU、系统、编译器和计时边界不同，不能当纯仿真引擎加速比。VCS从T12到T384的仿真逻辑时间增长约32.31倍，正常wrapper增长约31.92倍（37619.46/1178.5），在已测范围近似线性；不能保证T768线性，也没有“大测试会自动反超”的证据。

2MiB的NPU计算窗口更短，但VM完成整项仿真墙钟比1MiB更长约30.47%。行为模型大小、主机资源、编译及测试平台开销都可能影响仿真速度，这不等于硬件扩容后变慢；2MiB生成报告中的62.048秒是Verilator转换时间，不是整项仿真时间。

### 24.2 资源采样和Python profiling事实

EDA152报告Xeon Gold6240，4socket×18core×2线程=144在线逻辑CPU，内存251GiB。当时可用内存约224GiB，vmstat无持续换入换出或明显I/O等待。空闲时CPU MHz约1000不能证明仿真持续以1GHz运行；`Cpus_allowed_list=0-367`也不等于368在线核。

对本次自身进程的采样约99.77% CPU，主要用户态、无major page fault，RSS约203～245MiB。支持所测过程主要占一核、不是明显交换等待，但Python内嵌于simv，不能把CPU全部归RTL内核。总CPU只有1%也可能是一核满载，不能认为144核自动并行这项仿真。

profile目录为1MiB运行`..._runtime/runs/t12_r0.xluxpvy5`，文件实际叫`cocotb.pstat`。记录638658902次函数调用，profile总433.861秒；event_loop累计364.588秒、代理monitor56.235秒、AXI probe52.677秒、Python时钟44.771秒、halt轮询22.779秒。调用路径嵌套，累计时间**不能相加**，wrapper减去profile也不是精确RTL内核时间。VPI读写/回调约千万级，说明测试平台调度成本值得关注，但没有已测的关闭检查优化收益。

VCS使用`-debug_access+all`/`+acc+3`且出现ASICACC提示，是可能成本来源，不是已量化的根因。保持原可见性/行为的同服务器Verilator T12可复核结果现已建立；下一步看大测试，不先改变判据追求提速。两者都需要VPI/cocotb，不是把Python彻底移除了。

### 24.3 运行安全与恢复

- 后台/nohup本身不会使计算明显变慢；共享CPU、内存、主机休眠/重启、profiling、波形才是需要分别核对的条件。nohup不能保证断电重启后继续，VM首次夜间任务已实际被宿主关机打断。
- `tail -f`只跟踪日志，不是任务本身，Ctrl+C退出tail不会结束仿真；已收到结束标记后也不必让tail继续等。
- 查询自己的VCS用`pgrep -a -u "$(id -u)" -x simv`。曾用`ps -u ... -C simv`误把筛选当交集，该命令实际可包含他人simv；看到长时间运行PID不代表是自己的任务，严禁据此kill。
- Windows到EDA152仍用SSH22反向转发17908→本地7908。断网可能留下旧sshd持有端口；检查UID/进程归属且确认不是当前连接后才TERM该旧会话。PID32796等仅为历史，不能复用为当前目标；不killall sshd、不动gzc会话。
- 代理只用于下载，不应是本地仿真运行条件。VM直接使用`192.168.58.1:7908`是另一条链路；RDP3390和SSH22、远程桌面剪贴板是独立问题。
- Bazel默认安静输出，长时间无新摘要不等于卡死。看正确的运行目录、自己的进程CPU时间、原始日志和退出状态，不每几秒刷Analyzing，也不只按控制台最后一行判断。
- VM磁盘最后报告99G总量、67G已用、28G可用，是当时快照，后续模型可能增加。不要为ITCM/新后端复制整套Bazel cache，也不擅自删除旧缓存和证据。

<a id="section-25"></a>

## 25. ITCM扩容讨论：已准备什么、没有验证什么

`9019d91`新增[google_itcm_capacity](google_itcm_capacity/README.md)：DTCM固定2MiB，ITCM8/16/32/64/128KiB，独立`itcm_geometry_manifest.json`及新测试包，复用旧source/cache但不更改旧DTCM文件和manifest。核停止，仅前门地址/别名/mask检查。本地14项静态/合成测试通过，**没有用户实际RTL PASS**；后续代码工作集/取指性能阶段尚未实现。用户已暂停此线，接手不自动启动它。

当前DTCM workset的ITCM加载段仅1664字节，8KiB足以容纳这份程序及其当前布局。DTCM容量从32KiB扩到4MiB，不会自然要求指令容量等比例扩大；这个事实不能外推为完整AI软件也只需8KiB。

用户提出完整MobileNet约1001分类的需求。核对固定`8e4df09b`源码后发现：官方`tests/npusim_examples:run_full_mobilenet_v1_binary`目标明确设ITCM=1024KiB、DTCM=1024KiB，依赖MobileNetV1 0.25/224的dummy示例；它不是已经验证过的用户1001分类模型，也不是1MiB最小需求证明。本项目尚未运行该完整模型。

需要纠正过于简单的“模型权重都在DTCM”表述：官方`toolchain/coralnpu_tcm.ld.tpl`把`.text`、`.rodata`、init/fini段放ITCM；若模型const数组未指定外部段，也可能计入ITCM。示例另有外部arena安排，不能把整个软件需求等同DTCM大小。应先拿实际模型、算子实现和编译选项生成ELF/map，统计真实加载段、常量、栈/arena，再决定ITCM候选；不要从分类数猜容量，也不要把1MiB一概判为没必要。

<a id="section-26"></a>

## 26. 接手断点、剩余任务与新增提交索引

### 26.1 当前第一件事

按[HANDOFF-current.md](HANDOFF-current.md)先保存已通过的1MiB T12目录`t12_r0.fmvgge7f`、T384目录`t384_r0._66rc55e`与修复入口，不重复该档。当前准备服务器2MiB独立模型/T12，再进入2/4MiB T768；同时只读核对旧VCS2MiB/T384最终状态。下载/编译/单元测试仍不等于RTL通过，其他容量不能复用1MiB的前置结果。

同时从服务器2MiB/T384的固定旧队列目录取最终日志/退出码；不要再启动重复任务来覆盖它，也不要因为时间过去就写ALL_PASS。服务器路线成功后，才安排同机速度对照和大工作集。Ubuntu1/2MiB T384不需要为了换模拟器重新跑一遍。

### 26.2 后续任务按依赖排序

1. 归档现有1/2MiB完整工作集日志、参数、ELF、向量、退出码/命令和包身份；完整原始报告不全在Git里。
2. 保存已通过的Server Verilator1MiB T12精确参考验收材料、入口与429.077秒记录，不重跑旧失败；新大测试失败仍看`_test.log`和`_test-status.json`，不删旧包/日志、不手改manifest/hash。
3. 确认VCS2MiB T384历史结果；同一服务器、同一包做可比墙钟时，记录并发用户、profiling/波形、模型编译器及计时边界。
4. 当前1MiB T384也已完成，先建立2MiB自己的Verilator模型及T12；再安排2/4MiB T768，保留两策略各3次、全部输出和AXI检查。
5. T768的2MiB/4MiB配对：先传4MiB不可变包并自己的T12；这才是区分2/4MiB驻留收益的后续工作集。当前只有静态预期，未测结果。
6. 附加读等待8周期、真实SoC外存条件、备选循环调度和真实模型：需分别控制变量，不把代理0等待当真实零延迟SRAM/DDR。
7. ITCM实验等用户重新排期；完整模型先编ELF/map，不能拿现有1664字节微基准证明模型ITCM需求。
8. 200MHz、物理RAM宏、DC/STA/门仿、四NPU竞争仍须团队提供实际配置/库/网表与单独验证。

### 26.3 新增提交速查

| 提交 | 用途 |
| --- | --- |
| `a70f238`、`430551f`、`1c68076` | 固定官方单核容量、SSH、安静进度 |
| `baad5f6`、`128b077`、`4295642` | 控制组、配置ELF定位、六档控制PASS记录 |
| `ddf2efa`、`181ba52`、`deb148c` | 权重驻留与AXI、局部Python缓存、超时单位迁移 |
| `07c0eb9`、`1a50873`、`ca5beb2` | T12实际结果、跨容量审计与MiB阈值检查 |
| `6a1f175` | Bazel墙钟上限及不完整日志保留 |
| `088b836`、`34877f2` | 独立VCS包、1MiB导出记录 |
| `d34fa2e`、`3112b6b` | VCS svaext升级、2/4MiB导出进展 |
| `23afde9`、`760bda8`、`e4944de` | ANSI/ELF表示修复及验收记录 |
| `9019d91` | ITCM前门几何工具，当前暂停 |
| `92937fe` | 独立Verilator入口，首次版本存在WAVES/GUI问题 |
| `c0b4b76098a88d5bace3c3fbdcef318c10e924f7` | 最新trace启动修复、严格只读复用已编译模型 |

本次更新只完善记录/交接文档，不运行Linux仿真，不重新生成RTL/ELF，不改变上述固定包和任何已回传结果；个人仓库文档更新也不自动推送团队SoC仓库。未跟踪的旧RTL压缩包、`.gitignore`修改和`verification/rtl_handoff/`仍按第17节保护，不混入本次文档提交。

### 26.4 本次文档完善的核对范围

更新当前总记录、独立接手指南及专题入口/结果说明，共14份Markdown；检查本地链接和锚点、代码围栏，并对48个Bash代码块执行仅语法检查（不执行命令）。历史RTL导出/文档刷新工具11项本地合成回归通过，测试临时包不是新的NPU仿真或交付包。

原始10月4日RTL归档仍为`0a7d737dc1c18d49781b9cdb246a4fe0bf11ffeb1db509ca8263bca255f271ed`；固定Verilator脚本仍为`9031f22eadbfc75d308f2bcd67bde9b943b06822ccbbe8da702b821112273855`。`572894e`时修复后T12未回传、`f84fa31`时Server T384未回传；现在按用户新EXACT/RUN_PASS记录补入23.5/23.6，不回写旧失败。VCS2MiB/T384最终结果和Verilator2/4MiB、T768仍不能补写为通过。

<a id="section-27"></a>

## 27. 面积约束后转向完整MobileNetV1（2026-10-19）

用户要求单NPU、DTCM暂定512KiB、ITCM评估但上限512KiB；完整MobileNetV1输出1001分类，后端选择更快者。本阶段优先Verilator：旧T384服务器同配置VCS/Verilator约2.69098倍，不外推整模型耗时。旧容量扫描及不可变包保持，本轮尚未开始完整模型RTL。

只读下载团队SoC主分支`fa4b83e43bb0b1d58b18eb5f4c31d98ee4054123`到`.upstream-git/cheshire-coral-soc.git`审查。团队`sw/models/cnn-series/npu.cc`和三轮优化后的`sw/models/h4-resnet8/npu.cc`确有conv/depthwise/dense调用VME，具备im2col、pack复用和bias/tile初始化优化；量化/残差/GAP主要标量。四个固定未训练小诊断图的报告已阅读，但没有本机新SoC仿真。之前“未发现矩阵优化算子集成”的结论只限官方原始`sw/opt`，不能用于团队派生软件。

未收到团队指定模型文件，先采用官方MobileNetV1 1.0/224量化版候选；原模型不改。归档SHA`d32432d28673a936b2d6281ab0600c71cf7226dfe4cdcef3012555f691744166`，FlatBuffer SHA`ecc3a67c47c5a609ec35f6a58a7d97532834e43df4cb7d3f1204a8164b7d20dd`。静态确认输入UINT8 `[1,224,224,3]`、输出UINT8 `[1,1001]`，15普通卷积+13深度卷积+池化/reshape/softmax各1。模型4276352字节、常量4257900字节，最大特征802816字节。权重零点非统一128，不能直接套用团队signed权重/简化右移量化。单算子输入输出不别名合计最大1204224字节不是实际arena或通用下界。

新增[静态盘点工具与后续路线](google_mobilenet_v1/README.md)，模型/inventory缓存仅在忽略目录。12项本地检查通过，含实际模型及拒绝错误/动态/变量输入、报告不可覆盖。用户随后确认实际SoC外存尚未确定，单NPU阶段先用外部AXI行为存储；512KiB ITCM是上限而非已确定需求，待交叉编译ELF/map统计。完整主机参考、量化内核、固件、RTL包和整网性能全部未完成，不把静态盘点或本地测试标成推理PASS。

随后在项目忽略目录的独立主机环境安装固定`ai-edge-litert==2.1.4`，未更改系统Python/远程环境。`reference.py`用原模型、BUILTIN_REF、无外部delegate、单线程，neutral128/ramp/checker三组合成输入各invoke两次；31算子输出逐位稳定，1001维最终输出及各层golden落盘。六次invoke与保存约3.725秒，不是NPU性能，也不代表训练准确率。运行目录`.upstream-git/model-cache/mobilenet_v1_2018_08_02/reference_builtin_ref_v1`；模型、输入、逐层数据身份和输出SHA见专题README/manifest。此更新将主机参考标记完成，其他固件/量化/ITCM/RTL项目仍未完成。

<a id="section-28"></a>

## 28. 首个完整RTL模型改为预训练二分类MobileNetV1

用户担心大模型仿真成本，同意先用完整预训练Person Detection（有人／无人）。仍单NPU、DTCM512KiB、ITCM<=512KiB、优先Verilator，允许外部AXI行为存储；不修改上一阶段结果。

选择Coral固定依赖的TFLM `b75c6ff4e2270047f2b48fa01f833c8101c31f43`原模型`person_detect.tflite`，SHA `808cfdfc0cf3a6fa6f6fa26bfa379ea97c16d5db7334637766e39c3408502e9d`、300568字节。静态确认INT8 `[1,96,96,1]`→`[1,2]`，31算子（14Conv、14Depthwise、pool/reshape/softmax各1），最大特征36864字节。首层depthwise倍率8、其他倍率1，不能直接套用团队小诊断图的通道一一对应实现。官方两个BMP亦固定SHA，按照原生成器直接使用解码字节作为INT8输入，不再次减128。

桌面LiteRT2.1.4加载失败：14个一维bias的quantized_dimension=3，入口校验拒绝，尚未invoke；主分支模型Git blob同原文件。未改模型/权重/量化轴，不伪造参考。新入口改为在VM运行配套固定TFLM的官方原生C++测试，并检查两张图分数/完成标记；当前未执行，不提前记PASS。

新增[二分类专题](google_person_detect/README.md)、固定资产获取/本地尝试路径、固件源、现有source增量安装器、ELF预算/原模型字节审计、安静的VM构建入口。固件先使用原始TFLM INT8五类注册，不是VME加速版。模型原字节拟放DTCM `.data.pd_model`，arena预留160KiB、输入9KiB、栈16KiB；ITCM先按512KiB链接上限测真实加载大小，再建议有余量的容量，不生成RTL或直接宣称需要512KiB。模型/输入/arena/栈均由真实ELF再次检查，未链接前不保证满足预算。主机预载输入非BSS，避免启动清零擦除。

本机15项静态/合成测试通过：固定资产/生成数组相同、样本字节、输出判据负向、ELF资源预算/模型hash/CRT擦除/错误架构与路径拒绝，以及安装器拒绝覆盖已有目录/改动。另有19项1001类工具回归通过。未在Windows编译NPU固件、未实际执行原生TFLM C++或NPU RTL。下一步用户在Ubuntu运行`verification/google_person_detect/build_firmware.sh`，只做原生主机测试和固件资源测量；得到报告后再准备选定ITCM/DTCM512KiB的Verilator模型，不直接启动未经评估的长标量仿真。

### 28.1 2026-10-20：VM原生主机参考与固件资源实际通过

资源下载初次在Python urllib TLS握手时被reset，尚未开始测试；指导VM使用Windows VMnet8主机`192.168.58.1:7908`的HTTP(S)代理重跑，不是服务器17908隧道，不关闭TLS/模型SHA检查。

随后用户回传`person_firmware.AD3nfw`完整成功摘要：固定TFLM官方person/no_person原生测试1/1通过，构建380.413秒、测试0.4秒；按模型输出顺序[no_person,person]，有人图[-113,113]、无人图[57,-57]。日志SHA `d04c93fb6c3a140cb5c38ee2dd96a0beb54828c3d6f4e9fccad303a56931e19e`。这与桌面LiteRT旧失败属于不同加载实现，不修改原模型，也不把两个样本通过外推数据集准确率。

固件交叉编译341.416秒，ELF检查通过但不是NPU执行。ITCM加载末地址136080字节（约132.89KiB），128KiB不足；25%余量规则推荐256KiB候选。DTCM静态474432字节（包含160KiB arena预留）、堆33472字节、栈16384字节，合计524288字节。原始模型字节一致；运行arena用量、栈水位、实际Invoke/输出/周期仍未完成，完整ELF SHA待从远程resources.json读取，不凭摘要猜填。

用户希望长任务在稳定服务器运行，采用VM仅生成RTL/固件、服务器独立Verilator路线，避免服务器原生Bazel兼容问题。新增`export_rtl.sh`/`export_person.py`/`portable.py`：复核已通过的原主机/ELF证据，新建256KiB ITCM/512KiB DTCM导出目标，不重编/修改原ELF；检查各实际段都放得下、公共参数/ZIP、固定资产字节、INT8 BMP解码和归档校验。保留原8KiB ITCM的旧TCM包，不沿用其新配置通过资格。新包明确标NOT_RUN，尚无完整模型仿真runner，不运行旧workset bench。

新增7项合成导出测试，与原有15项合计22项通过；官方两BMP的标准库解码与Pillow逐字相同，Bash语法检查通过。真实新RTL生成尚待用户在VM执行，服务器编译/单图耗时采样为后续步骤；完整NPU推理/VME加速/性能仍不记PASS。专题结果见`google_person_detect/FIRMWARE-results.md`。

### 28.2 2026-10-20：真实RTL导出及服务器单图试运行入口

用户回传VM RTL构建34.698秒，新参数/导出校验通过，原ELF和模型字节一致。目录`/home/lqq/coral_tcm_capacity_8e4_v1/person_rtl_export.r9bhUw`，包`coral_person_i256_d512.tar.gz`，SHA `a83bd98bd92157163223b75d74a25e5f426a59937354fb3784d830be4f130726`。256KiB ITCM/512KiB DTCM的实际SV已经生成；仍没有NPU推理通过记录。

新增包外`person_runner.py`/`person_bench.py`/`server_pilot.sh`，固定SHA复用旧独立Verilator构建器通用编译函数，重新编新顶层，不复用其他容量可执行文件。核验包中原ELF/资源、原模型、依赖版本/C++17/动态库；输出和锁放包外，不覆盖原包；环境清除WAVES/GUI/profiling，包括字符串0。

服务器先校验/编译，然后前门完整装载/模型读回、官方有人图输入读回及20万周期有界观察。0/1/2阶段、fault、自然halt、arena、invoke周期、两分数、栈底64字节canary及执行/装载墙钟分开记录。预算到达后以原CSR halt接口停止一次性实例，非恢复checkpoint。仅窗口观察时输出OBSERVED_NOT_INFERENCE，cocotb完成不等于模型通过；自然halt/status3/实际arena/原生两分数精确一致才可INFERENCE_PASS。栈底检查不是完整水位证明，status0不宣称有效程序进展。

新增7项本地入口/结果判据测试，与旧22项合计29项通过，含原模型合成ELF重审计、失败XML/JSON/窗口/状态/栈/模型身份拒绝、环境清理和固定构建器命令。无本地RTL编译/运行。下一步[SERVER.md](google_person_detect/SERVER.md)先传包再服务器前台pilot，各阶段超时1800秒，不自动启动完整标量整网或其他用户任务。根据pilot再定完整单图预算；旧模型/TCM结果不变。

### 28.3 服务器模型编译及20万周期观察完成，尚未完成推理

用户回传`/data/home2/lqq/Desktop/coral_person_packages/person_pilot.dJfrJn`核验/环境检查通过，新Verilator模型`builds/a5d0fd5aca9a.g9pa3q0w`编译439.989秒。`runs/smoke_person.8xymkq4w`完整有界观察200000周期，执行67.977322秒，装载/原模型与输入读回17.818258秒，测试总87.178秒。

ITCM256KiB/DTCM512KiB，ELF SHA `e3078c156fd03315be2796c95044558cc3722854c077d6d8702100c18dd2b877`，模型原SHA不变，输入SHA `d4ebdafe351a7b7851c3d087fb7ec798c739badcd7e248dcb81fa92dd572aaed`。读回一致、无fault、栈底64字节canary未变；状态1证明已到main准备/分配阶段，但arena_used=0/invoke_cycles=0，输出[37,53]仍是哨兵，未自然halt，验收仅OBSERVED_NOT_INFERENCE，不能宣称模型跑通，也不能仅凭无fault排除死循环。

下一步保留当前runner/bench/模型身份，不重跑会解新包/重编的pilot脚本；在同环境直接重新初始化并观察200万周期，粗按已测窗口预算约12分钟，非完整模型时间预测/性能结论。若仍状态1，再定位初始化/分配进展。当前只更新文档，未执行该200万周期任务或修改任何RTL/固件/脚本。

### 28.4 200万周期仍未进入Invoke，独立DM诊断准备

用户回传`runs/smoke_person.ttnd8y5g`2000000周期结果，执行698.728060秒、装载/读回18.492447秒，总718.555秒。原ELF/模型/输入身份相同；无fault、栈底64字节canary完好，但status1、arena_used/invoke均0、[37,53]哨兵、未自然halt。记录NOT_INFERENCE，不据此宣称卡死或硬件错误。状态1横跨多个准备步骤，仅靠摘要无法精确归因AllocateTensors。

不盲目扩大预算，新增`diagnose_person.py`/`person_diag_bench.py`：固定原runner和bench SHA、复核同一build身份/模型hash/包/环境，只读复用已有Verilator可执行文件，不修改原脚本或原包，不构建RTL。新进程前门初始化后先20万周期，在原CSR halt/reset之前通过官方DM halt/读取DPC、DCSR、GPR/异常CSR与可选计数器，映射原ELF函数；恢复4096周期再取样，共最多3次。ra/栈代码地址只标候选，不伪造完整回溯。可选CSR失败显式保留，核心寄存器失败停止；无reset兜底掩盖现场。

该侵入式调试不作性能测试，不把CAPTURED/cocotb PASS当作模型通过。旧smoke进程已复位退出，不能从旧日志恢复PC，需重新运行短诊断。新增5项软件契约检查，合计34项本地测试通过，语法通过；服务器DM诊断未执行/未回传，后续命令及范围见[DIAGNOSTIC.md](google_person_detect/DIAGNOSTIC.md)。

### 28.5 首次实际DM诊断：20万附近确有进展，200万现场待采

用户附件回传`diagnostics/pc.ts77oz3y`3样本CAPTURED，无重编/固件变化，采样前无reset。DCSR cause=3、fault=false、全部可选寄存器读取成功、mepc/mcause/mtval均0。DPC59212/37024/49576分别由ELF函数范围明确包含于AlignPointerUp(+12)、InitializeTfLiteTensorFromFlatbuffer(+900)、PopulateConvolutionQuantizationParams(+932)，ra/栈候选与临时张量和卷积准备调用吻合，但不是完整栈回溯。

minstret192834→195037→197809，分别增加2203、2772，说明20万附近采样区间有真实CPU执行与准备流程变化，不是核心停机；仍status1、arena_used/invoke均0。mcycle包含调试握手/扰动，不据此算IPC或模型性能。此证据不覆盖200万现场，不能直接断言此前200万结果“只是正常慢”，也不排除晚些时候循环/错误。

下一步不改任何运行代码/模型身份、不重编，将同诊断首次采样点改2000000周期、3样本/4096间隔、timeout1800秒。粗按已测执行窗口预算约12分钟；是为了取得此前未完成时的PC/异常/指令进展，而非盲目加长无诊断运行。当前仅更新记录，200万DM诊断尚未执行/回传，完整模型仍未通过。

### 28.6 200万DM确认软件双精度量化准备仍在执行

用户回传`diagnostics/pc.tyngamx6`，3样本均CAPTURED，DCSR cause3、未复位/改固件，无fault，异常CSR均0。DPC89856/97220/89840分别落在`__divdf3`、`__fixdfdi`、`__divdf3`，ra调用点为PopulateConvolutionQuantizationParams/QuantizeMultiplier；minstret1509687→1513222→1516732（+3535/+3510），表明该窗口确在执行量化准备，不是核心停机。不能凭3点断言全程正常、占比或最终成功。

只读核对GCC运行库文档和固定TFLM b75的`tensorflow/lite/kernels/kernel_util.cc`/`internal/quantization_util.cc`：INT8准备阶段按通道用double计算scale乘除并生成整数乘数/移位，可调用软件double除法/转整数；当前编译目标有F/向量FP32无D。发现初始化慢的一个具体来源，不能泛称整个NPU无浮点，也不能把它当VME/Invoke性能。尚未做任何数值优化、TFLITE_EMULATE_FLOAT或精度替换。

下一步保留正确性基线，原模型/RTL/ELF/runner/bench身份不动，直接复用模型运行1000万周期窗口、timeout7200秒，粗按已测速度预算约1小时，不保证整网完成。检查是否从状态1进入Invoke/输出实际arena或提前完整结束；如异常停止，不直接加RAM。当前仅同步文档，1000万运行尚未回传，模型仍未记PASS。

### 28.7 1000万周期准备已完成，进入Invoke阶段

用户回传`runs/smoke_person.bzrml3j3`：10000000周期执行3475.519607秒，装载/读回18.676758秒，总3495.779秒。原模型/输入/ELF身份保持，fault=false、栈底64字节canary完好。status2，arena_used82300字节（约80.37KiB），证明AllocateTensors已返回、接口与输入复制完成并到达Invoke调用阶段；不再把状态1疑为永久卡住。但这不证明Invoke已结束/所有算子正确，未自然halt、输出仍[37,53]哨兵，invoke_cycles尚未回填。

82300仅是AllocateTensors后报告值，不是全DTCM用量/全程运行峰值；160KiB静态预留不自动缩减或释放给堆。当前不改RAM、精度、内核、RTL或固件，不重编。smoke退出时已停止并结束进程，不能从1000万处续跑。

下一步给原样完整有人图一次更完整预算：infer模式2亿周期、86400秒墙钟上限，完成可提前退出并核对两INT8分数；跑满周期按当前窗口速度粗约19小时，阶段负载可能变化，不承诺完成时间。建议nohup后台并记录PID/console.log，长任务不依赖Windows/VM持续在线，但服务器重启仍中断。启动命令仅提供用户执行，当前尚未启动/回传；不能提前标完整模型PASS。

### 28.8 默认任务已启动；落实此前遗漏的团队VME算子接入

用户回传完整默认任务启动PID309672、日志`/home2/lqq/coral_vcs_tools/person_full.wQGGQC/console.log`，随后要求确认内核。只读核对当前固件注册、固定TFLM头文件/实现、官方集成patch：本任务仍为默认reference整数算子，未接官方RVV内核或团队VME。不能说编译器绝不产生向量指令，但这不等于已优化算子。用户指出此前要求参考SoC手工优化库尚未落实；确认只做库审查而未集成的执行遗漏，转入实际实现，不要求等默认版长任务完成。

只读查询团队remote main仍为`fa4b83e43bb0b1d58b18eb5f4c31d98ee4054123`。新增`verification/google_person_vme`，参考其h4-resnet8预打包/空间tile/Tk4策略；原模型14个Conv2D经静态实际读取均为1×1、步长1、最大Cin256，首版覆盖这些层，Depthwise/池化/Softmax仍默认。新路径明确处理VME B无符号与INT8激活的差别：x+128并修正bias，沿用固定TFLM逐通道量化和激活边界，非团队诊断图的简单右移。固定9KiB左右workspace非重入，ITCM256/DTCM512/栈16KiB，实际资源待交叉链接审计。

新增主机emulated全模型两图/28层全输出字节比较目标、真实VME validate固件和不重复reference计算的fast固件，三者身份分开；fallback与软件矩阵发射计数显式记录，主机模拟计数不冒充硬件。validate使用arena scratch保存优化输出后再调用原卷积全字节比较。主机PASS不等于硬件PASS，validate周期不能用作加速结果。新增VM脚本先主机验证后交叉链接审计，不运行RTL、不改旧包。

实际本地验证：共享C++核心336组raw累加逐项一致（含负数/极值/零点/通道与空间尾块/无bias/输出guard/拒绝溢出），MinGW GCC6.2编译执行；本地玄铁GCC14.3真实编译VME汇编probe为RISC-V ELF目标文件，非固定官方工具链完整链接。7项新工具/资源审计测试、34项原测试及脚本语法通过；固定模型与两样本生成12份候选文件并核SHA。完整TFLM候选主机测试、候选完整链接、资源测量、真实VME RTL及性能均未执行，不标通过。服务器任务原封不动继续，原runner/bench/program及不可变包不改；接下来用户在VM运行新build.sh，回传主机/ELF结果后再做独立优化包。

### 28.9 VME候选主机逐层匹配及链接通过，修复测速版符号审计

用户回传VM `person_vme_v1.acWcT3`：核心336组PASS，固定TFLM主机完整原模型两图PASS，有人[-113,113]、无人[57,-57]，每图14层候选卷积全输出逐字节匹配reference，共28层；host arena_used122000，非NPU实测。validate真实交叉链接及审计PASS，ELF SHA `980b3373ad9a0ad8ab00e820eaa3dd10d6bae9eaf6612d832276eb03cb8b0cb7`，ITCM139760、DTCM静态483760、heap24144字节，栈16KiB，适配256/512配置。fast也实际链接成功，但审计报Missing/out-of-range后停止，因此该次整体脚本不标PASS，fast资源尚未回传。

源码核对发现audit错误地对fast要求六个符号，而PD_VME_VALIDATE=0移除了validated_layers及first_bad_index的全部引用，链接垃圾回收可正常移除其定义。仅修改audit按模式设必需集合：校验版六个、测速版main门限实际使用的四个；可选项若保留仍严格检查，缺必需项/越界/错误大小/未定义符号继续失败，并输出具体名称。未改生成器/固件/模型/RTL/安装manifest，不强行保留死变量或跳过检查。新增4项回归，11项候选工具测试与原34项通过；下一步用户拉取后重跑原build.sh命中链接缓存并重新审计，新结果目录不覆盖旧失败证据。实际优化VME RTL运行及整网性能仍未执行。

### 28.10 两份候选审计通过；准备独立导出及短VME硬件probe

2026-10-21用户回传 `person_vme_v1.zFvRgl`，两项主机测试PASS、validate及fast交叉链接/资源审计均PASS，最终 `[PERSON_VME_HOST_AND_LINK_PASS] NPU_RTL=NOT_RUN`。validate SHA及资源同上；fast SHA `c07d3039e66e0422e688abc2f8c281b110cd3ba7a1b40872ea94df86430821fd`，ITCM139136、DTCM静态483744、heap24160字节。确认两者装进原256/512KiB配置，非RTL通过，不再重新进行同一构建。

新增独立export入口：严格核验实际host日志两图/28层全字节与最终分数、两份ELF/report/source manifest，再核对原默认导出包；复制其字节不变的RTL/DPI/fixture/资产，不重新生成RTL。新包包含probe/validate/fast三份ELF及证据、SHA清单；不覆盖原包，不绕过原runner。新probe源码安装在不同目录，只链接小固件，v1原安装源码/manifest均不改。

短硬件probe采用与候选相同的打包核心和真实矩阵backend：8组负数/极值/零点/尾块，840个原始INT32结果逐项对比独立标量参考，预期233条矩阵发射及签名3016346044，跳过TFLM分配和double准备。实际本地主机模拟分支已编译执行通过；实际本地玄铁GCC14.3编译真实分支为RISC-V目标文件，非官方完整链接/RTL。新的独立server_probe只支持短算术probe，自然halt/故障/结果/栈底检查严格区分，任何预算耗尽不标PASS，不输出模型推理PASS。默认服务器长任务不操作；新包构建/状态结果独立。

新增包验证、导出、结果验收、堆栈资源检查回归及完整合成导出；18项候选工具/34项原路径测试、脚本语法和命令行入口检查全部通过。这类测试使用明确synthetic文件，不代表实际包/硬件通过。下一步用户在VM执行export.sh，生成归档/SHA后再传服务器；实际VM probe完整链接/导出、新server模型编译/RTL probe、validate/fast整网RTL与性能均未执行。操作入口在google_person_vme/README.md。

### 28.11 VME包实际导出；用户指定Depthwise暂不改，转向未优化算子

用户回传实际VM `person_vme_export.F6GOKR`，probe_program.elf官方完整交叉链接PASS，独立包导出PASS、原RTL/模型不变；归档 `coral_person_vme_i256_d512_v1.tar.gz` SHA `f4dea9fdb5a329955ab68905a254ab9414aeb6f5b0b3d551f2f182e946aa03ea`。已给出VM传输和server独立编译/短probe命令；尚无真实服务器probe结果。前台/后台可并行但墙钟会竞争，NPU确定性周期应区分；之前的时间估计不是测试已完成证据。

用户询问官方RVV覆盖，重新只读核对固定8e4：官方已有Conv、Depthwise、FullyConnected、MaxPool及Logistic库，通用tflite_runner条件注册部分RVV，而当前自建Person固件未接；未发现AveragePool、Softmax、Reshape对应专用RVV内核。官方Depthwise源码有depth_multiplier循环，也有完整输出INT32 scratch和权重/bias复制，不能说缺少该实现，亦不直接保证其适配内存。用户明确先不改Depthwise、从其他无优化算子入手；本轮保持当前官方默认注册，不新增自定义Depthwise或偷偷切到RVV。

### 28.12 RVV AveragePool第一版实现与独立验证入口

原模型Pool实际形状[1,3,3,256]到[1,1,1,256]，3×3/stride2/VALID，无融合激活，输入输出scale相同0.01860933005809784、zp=-128；Softmax仅2输出、Reshape2个INT8元素，优先Pool但不承诺整网大幅提速。新增google_person_pool：共享窗口调度每空间输出只算一次边界/有效count；真实RVV连续通道加载、符号扩展到INT32累加、有符号整数vdiv精确复现TFLM正负舍入与截断，无浮点近似，无完整INT32输出scratch。沿用原PoolingPrepare及激活范围；校验版arena保存INT8输出后运行原Pool全字节比对，本模型额外scratch256字节，测速版不重复reference。

独立安装person_detect_vme_pool_v1：VME Conv原源码字节保留，模型/样本/Depthwise/Softmax/Reshape/RTL/RAM不改；新主机全模型入口比较两图×(14Conv+1Pool)=30层及原始分数，再交叉链接256/512KiB校验/测速ELF和计数器资源审计。旧父manifest/目录及已导出包不覆盖。候选仍非重入单NPU流程，新增计数器区分RVV与主机模拟。

实际本地MinGW GCC6.2严格编译执行2160组/1291923输出元素和count1..49舍入边界通过，涵盖负数/极值、SAME/VALID、stride、通道尾块、batch、activation及拒绝溢出/空窗口；玄铁GCC14.3真实编译RVV probe并反汇编见vle8/vsext/vadd/vmerge/vdiv/vmax/vmin/vse8，非硬件执行。7项新工具测试、旧VME18项与默认路径34项回归及脚本语法、实际模型17文件生成检查均通过，模型源码与父候选一致。固定TFLM参考native差分、完整两图新候选、官方完整交叉链接/资源审计、RVV硬件及整网性能均待执行；下一步用户在VM运行google_person_pool/build.sh。

### 28.13 真实VME短probe通过，Pool主机与真实交叉链接通过

2026-10-21用户回传服务器 `person_vme_probe.ecTtR9`：verify/check通过，独立Verilator编译464.673秒；`coral_person_vme_i256_d512_v1_verilator_runtime/runs/probe.1hyg7w53` 实际8组/840个原始累加值/0错误，233软件发射计数、签名3016346044，825634周期自然halt、status3、fault=false、栈底64字节canary完好。执行286.476705秒，总298.252秒；ELF `a38ce47a015b8e4810d01e9724b0333b98eaf58c48cc22dab857f4bebd293522`，原RTL `477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2`。标记 `[PERSON_VME_HARDWARE_PROBE_PASS] full_model_inference=NOT_RUN`，正式补全真实VME硬件短测证据，不能称完整模型推理或速度比。

随后用户回传VM `person_pool_v1.0u8RTz`：固定TFLM参考池化差分和完整两图主机测试均PASS，两图共30层（14Conv+1Pool每图）逐字节参考对照由工具门限验收；主机backend仍模拟，不是RVV执行。两版完整交叉链接及资源审计均PASS，最终 `[PERSON_POOL_HOST_AND_LINK_PASS] depthwise_unchanged=true NPU_RTL=NOT_RUN`。validate SHA `8137e2bf8777f5e0976a49887302724c64f27d491c886f14ec673d535eac0951`，ITCM143296/DTCM静态483776/heap24128字节；fast SHA `81f596bd9eb0fa94ef3fcdfb0cb33719e5e00cad949207b7600b91f7481253f8`，ITCM142112/DTCM静态483760/heap24144字节。两者256/512KiB、栈16KiB，Depthwise官方默认注册不变。无需重新跑同一构建。

### 28.14 新Pool包导出和短RVV验证工具准备，尚待VM/服务器执行

新增 `google_person_pool/export.sh` / `export_pool.py`，核验实际候选manifest、两图全层日志/原生池化测试标记、两份ELF/report和旧不可变VME包；复制相同原RTL/DPI/fixture/模型/输入，新版validate/fast ELF只复制不改。另独立目录person_pool_probe_v1链接短RVV固件，输出新 `coral_person_vme_pool_i256_d512_v1` 包及SHA清单，不覆盖父候选/旧包/默认长任务。audit_pool只增加便携导入旧VME资源审计的路径，不改数值审计规则、生成器、算子源码或已测ELF。

短probe真实RVV backend与候选头文件字节一致；8组/659个INT8输出，实际3×3×256池化、尾通道、padding、batch、正/负半整数舍入、激活与guard，独立标量窗口参考逐项比对，预期62向量循环块/签名642806987。复用诊断字段commands在此表示向量循环块数，不是矩阵指令或独立退休。跳过TFLM分配/量化初始化，只能验收Pool硬件算术。新包server_probe.py/probe_bench.py由已通过旧入口的哈希固定模板严格替换生成，有独立包/构建身份、严格自然halt/fault/栈底/结果门限，不写旧目录，成功仍明确full_model_inference=NOT_RUN；当前不支持完整模型infer。

实际本地MinGW严格编译执行新probe为8/659/62/签名匹配；玄铁GCC14.3真实RVV分支目标文件编译通过，反汇编见vle8/vsext/vmerge/vdiv/vse8，但不是官方完整链接或RTL。新增5项合成完整导出/拒绝错误或重复结果/防覆盖测试，合计12项Pool、18项旧VME、34项原默认工具回归通过，shell语法通过；原默认runner/bench与旧VME运行入口/Pool生成器未改。实际VM新probe链接/归档、服务器Pool RTL、两图优化整网RTL和性能仍未执行/未回传，不提前标PASS。下一步使用person_pool_v1.0u8RTz及person_vme_export.F6GOKR执行新export.sh，回传归档路径/SHA后传服务器，详见Pool README及SERVER.md。

### 28.15 默认完整模型单图通过；真实RVV Pool短probe通过

用户实际回传VM `person_pool_export.nhXtY2`：官方完整交叉链接新短probe成功、原RTL/模型和Depthwise未改，归档`coral_person_vme_pool_i256_d512_v1.tar.gz` SHA `7c8e0fe5121c0aeb37d9e8a54983dd7fe64603bf5de964b718aac4cd4b3076eb`。已给出独立目录传输与前台服务器校验/编译/probe命令，不覆盖旧包。

用户随后查看此前后台默认完整模型任务，实际`person_pilot.dJfrJn/coral_person_i256_d512_verilator_runtime/runs/infer_person.r6a1thwb`返回`PERSON_NPU_INFERENCE_PASS`。ITCM256/DTCM512KiB，原ELF e3078c...和原模型808cfdfc...不变，case=person，status3、inference_complete/natural_halt=true、fault=false，模型/输入读回一致，有人输出[-113,113]完全匹配固定TFLM主机参考。Invoke190673191周期、观察194501581周期；执行65877.175261秒、总65897.933秒（18小时18分17.933秒），装载/读回19.157962秒，arena_used82300/预留163840字节，栈底64字节canary通过。正式形成真实默认全模型单图周期基线，旧后台任务已完成。不能扩大成无人图/数据集正确率或完整栈/内存峰值通过；arena不是DTCM总用量。

用户回传新Pool服务器控制台`person_pool_probe.Wa8Udc/console.log`，包路径`/data/home2/lqq/Desktop/coral_person_packages/pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1`，编译`..._verilator_runtime/builds/7a54106b3148.z558xni8` 450.453秒；实际`runs/probe.46bl5uqr` 8组/659项/0错误/62向量循环块/签名642806987，256826周期自然halt/status3，无fault且栈底canary完好，执行85.613674秒、总97.463秒。probe ELF `031cf12303fb5fe8d75a88d72f0aee2a3453c54d0ba70446f95f35cba3a009cb`，原RTL477aa4d...不变。标记`PERSON_POOL_HARDWARE_PROBE_PASS full_model_inference=NOT_RUN`，正式证明短RVV后端数值，不能与整网PASS混同。

### 28.16 包外完整VME+Pool模型入口：复用构建、先校验后测速

新增model_runner.py/model_bench.py/run_model.sh，不修改原包、旧runner/bench、候选生成器/算子或已链接固件。入口哈希固定已封包producer，严格验证三份实测ELF、原模型/包清单、producer原构建身份/环境/配方/可见性/二进制；核验同build短probe result/raw/XML。复用原编译模型仅作为RTL/DPI/fixture可执行程序，ELF仍前门加载；不将旧模型重新标成新入口构建、不复制/覆盖current_build。持原state锁避免并发覆盖，新模型证据写到独立同级`..._model_runtime/runs/*`，每次从完整固件入口重启，不当checkpoint。

先执行一张有人图validate，要求14个VME Conv、1个RVV Pool、0fallback/0mismatch、14+1全部逐字节reference验证、原始分数、自然halt/无fault/arena/canary及周期条件全部满足。软件发射和向量循环计数不当硬件退休，校验版performance_eligible=false。fast须提供同图/同包/同producer build的完整validate原始证据，且验证调用不得执行；不自动排队更多长任务或直接输出加速倍数。原默认Invoke190673191周期才是后续同图fast的比较基线。为避免扰动执行周期，运行中不从AXI轮询计数器。

脚本先前台check，再nohup只启动一个validate person任务，日志/PID明确输出。4亿周期/48小时是上限而非耗时估计；校验版增加reference计算且Depthwise仍默认，不能保证比18小时基线快。耗尽任何上限都保留日志、不标PASS，不能续跑。完整模型两图、fast和整网加速依然待执行/回传。

实际本地7项新合成检查通过，覆盖构建只读复用/环境JSON元组规范化、XML与重复或ANSI日志、错误输出/故障/部分层/错误计数拒绝、fast校验隔离、同图同build前提及原始证据变更拒绝；Pool合计19项，旧VME18项和默认34项回归通过，语法/命令行检查通过。不代表已在服务器执行新入口或跑合并版整网。操作见google_person_pool/MODEL.md。

### 28.17 用户暂缓大模型：新增独立Conv单算子周期实验

用户询问Conv矩阵优化实测加速倍数；明确此前只有默认整网周期与短VME正确性，825634周期包含生成/参考/检查，不能作Conv时间。用户同意先小规模Conv对比，不启动上轮完整模型长任务；当前没有用户回传上轮run_model.sh已经启动，不擅自停止服务器任何进程。

新增google_person_conv独立目录/生成器/benchmark/build/audit/test。从原Person模型operator2/8/24/26/28提取原权重/bias、所有量化字段、激活和Conv选项，构造5个只有一个Conv的派生诊断FlatBuffer；空间布局展平为[1,1,M,K]，M分别16/16/9/1/1，K8/32/128/256/256，N16/64/256/256/2，MAC2048/32768/294912/65536/512。输入为seed137+operator的固定合成有符号INT8，不是实际图片中间激活；派生模型不是原完整预训练模型，op2/op8/op26裁剪了空间范围，不能当完整原层性能。常量/输入/派生数据均记录SHA，原模型文件不变。

同一个ELF中两个单算子MicroInterpreter分别注册默认Conv和原样复制VME Conv，原TFLM依赖构建路线不变；自定义源码/benchmark -O2禁自动向量化/LTO，PD_VME_VALIDATE=0。单独fence+mcycle窗口只含各自Invoke，包含实际VME打包/零点bias修正/tile搬运/矩阵/重定量化/写回，Allocate/Prepare、输入装载、参考输出逐字节对照均在窗口外。首次调用单列，后三次steady交替先后，空时间边界单列不静默扣除。不先保证加速，窄层和小M可能被搬运成本主导；软件矩阵计数仍不是退休观测。

本地实际生成五份派生模型，常量/量化/Conv选项逐项对原模型一致，LiteRT BUILTIN_REF五例实际推理及重复输出一致（不是VME/TFLM native实测）；7项新工具检查通过，覆盖裁剪拒绝/数据范围、独立安装/拒绝覆盖、完整五用例native证据、非零.data case selector和诊断几何、计时边界。新生成器依赖flatbuffers25.12.19/tflite2.18.0只在VM独立target目录安装，不覆盖Conda环境。Bazel包person_conv_bench_v1和manifest独立；准备先native原TFLM vs emulator比对，再完整链接256/512KiB ELF，尚无实际VM/RTL通过或加速数字。

当前下一步VM运行google_person_conv/build.sh，回传5例native签名与ELF资源审计后再做小固件包/读取入口，服务器先只跑id0（2048MAC/次），复用原RTL编译模型，不自动启动所有用例或完整网络，不改旧包及原Pool/VME生成器。默认整网190673191周期不直接与片段周期相除。

### 28.18 小卷积主机与实际链接PASS，准备不带RTL的小包和周期读取

用户回传`person_conv_v1.nTbcvy`：native单测试PASS，probe_program.elf真实完整链接/审计PASS；ELF SHA `b94e1da3b4f7f2693727395073e65f172344f15454bd01a7b7bb8c2832f259b2`，ITCM占用113536、DTCM静态265584、heap242320字节，保持ITCM256/DTCM512KiB。最终`PERSON_CONV_HOST_AND_LINK_PASS full_model=NOT_RUN NPU_RTL=NOT_RUN`，不当NPU周期或加速通过；5个native输出签名保存在实际run中，导出时重新解析原始日志并核验。

新增export_conv/export.sh，严格验证现有candidate manifest/源文件、实际ELF/report/五例native签名，从ELF的kConvCases RV32表解析派生模型/输入地址、长度与SHA，不改已测ELF。小包包含固件、证据、源码、许可证和独立服务器工具，不含大RTL/完整网络模型，不调用Bazel、不运行仿真。audit_conv只把命令行专用的export_bundle导入延迟到main，不改变审计输出或候选源/生成器/已测ELF身份。

新server_conv/conv_rtl_bench复用哈希固定model_runner构建检查器，只读核验原Pool不可变包、同producer构建身份/环境/配方/二进制和probe.46bl5uqr原始证据，持其锁但不改编译模型/current_build。前门加载小ELF，读回选中派生模型/输入SHA，写非零.data case selector、复核M/K/N/operator、自然halt/故障/canary/arena/逐项对照/host签名/4次VME调用与准确软件发射数。默认只跑id0，4次共8条矩阵发射，0fallback/0mismatch/0内部reference重复校验；读取first+3steady的两组mcycle及空边界。原始样本和ref/VME比值均保存，不把较慢实现判为失败，不扣除边界开销，不外推整网。

新增4项本地合成包完整导出、ELF数据表/fixture校验、正反性能结果验收及准确发射计数检查；Conv合计11项，旧Pool19/VME18/默认34项回归通过，语法/CLI检查通过。另实际用本地玄铁GCC14.3将生成fixtures编译成RV32目标文件，确认kConvCases符号180字节且无动态初始化；不当官方最终ELF/RTL运行证据。实际VM小包导出/服务器NPU周期仍待执行，下一步export.sh只读取person_conv_v1.nTbcvy，回传归档/SHA后传服务器，先id0/2百万周期/1800秒上限前台试跑，不启动完整网络或其他case队列。

### 28.19 真实Conv片段2.14倍结果；VME/RVV共同适用性核对

用户实际导出小包SHA fec8b002b6d886129e6bdc1d9d461fbb6bdab66643ab5a246863f8a7bd986ff2，大小2460577字节，并回传服务器conv_fec8b002/coral_person_conv_v1_runtime/runs/case0.gqdyx8ir的PERSON_CONV_RTL_PASS。原Pool编译模型7a54106b3148.z558xni8只读复用，原RTL/固件SHA与28.18一致。M16/K8/N16、2048MAC每调用，默认INT8 Conv首次及后三次均91475周期，VME均42713周期；空边界3周期未扣除，默认/VME=2.141619647414136。1024项输出全等、签名3882088669；4次VME调用、8条软件矩阵发射，fallback/内部reference验证/mismatch为0。自然halt/status3/无fault/栈底64字节canary通过，观察901968周期，执行306.975889秒、总322.72秒。仅同ELF单算子Invoke空间片段的实测，不代表完整原层、整网或VME对RVV加速。

2026-10-22用户要求继续VME/RVV比较，小仿真可在VM执行。只读核对固定官方8e4的sw/opt/litert-micro/conv.cc：ConvPerChannel五个优化分支1213/1220/1226/1230/1235行均要求filter高宽4；1242行fallback调用reference_integer_ops::ConvPerChannel。当前五例1×1全部会回退，且回退前仍有复制/分配等开销。现有conv_vme.cc则只接受1×1，4×4会回退。因此两者无共同优化适用形状，不能只切官方RVV注册就称为公平VME/RVV Conv测试；也不能将复制中可能用到的RVV指令当作RVV Conv MAC内核。结论仅针对固定源码，不表示硬件不支持1×1向量计算。

新增google_person_conv/RVV-COMPARISON.md记录上述证据和后续选择：新增项目自研1×1 RVV内核，或另做共同INT8 GEMM微基准（不能替代Conv速度）。尚未实现/运行新RVV比较、没有VME/RVV速度比；没有改动原候选、Depthwise、已测ELF/RTL包或运行中的服务器任务。README和当前交接入口增加最新覆盖，保留旧阶段说明为历史。

### 28.20 用户转向LLM算子：准备小规模resident INT8线性层性能入口

2026-10-22用户提出用NPU仿真LLM，随后明确先测Transformer/LLM算子性能，暂不做完整语言模型。只读核对固定官方8e4目录tests/cocotb/rvv/ml_ops/gemma_kernels：有RVV INT8/FP32/BF16 matmul、RMSNorm、Attention和残差/激活等实现及单算子测试；不是已具备完整文本生成流程。其官方runner使用1MiB/1MiB/RvvCoreMiniHighmemAxi，不适合直接冒充当前256/512KiB硬件；Attention测试为unmasked、实权重缺失时允许合成数据，不能直接当自回归模型验证。

新增google_llm_ops独立目录。第一轮只比较朴素标量与官方rvv_int8_matmul.cc原样复制的INT8 GEMV/GEMM。四形状M1/K32/N32、M16/K32/N32、M1/K64/N64、M16/K64/N64，对应decode/prefill的线性层矩阵形状而非完整过程。官方matmul本身逐行调用gemv，不改写不宣称最佳RVV实现。固定xorshift seed137+case；X[-128,127]、W[-127,127]，遵守官方禁止两侧同时-128的限制。raw INT32结果，不含模型/量化框架、外存或KV cache，不输出tokens/s。VME本轮不参与，RMSNorm/因果Attention后续再加。

新同ELF/ITCM256KiB/DTCM512KiB，四次调用首次+三次steady，交替标量/RVV先后。-O2禁自动向量化/LTO，保留显式RVV；fence+mcycle只包围内核调用，空边界记录不扣，输入生成和逐项检查在窗外。每次比较两路径，最后前门读回实际输入和两个完整INT32输出对独立Python整数golden；检查输出前后/尾区guard、4次调用、自然halt/无fault/status3/签名/栈底64字节canary。工具拒绝不完整/重复/失败日志、不同ELF或RTL身份及错误周期；较慢的RVV同样是有效结果，不强制加速。

run.sh是VM前台单例流水：验证原capacity实验完整性，独立安装llm_linear_v1包，native只运行标量参考并核对Python签名，真实官方工具链链接新ELF和生成同配置RTL、严格参数/内存审计后，显式运行所选单个Verilator测试；默认只case0，不下载模型，不运行后台或其他队列，Bazel进度刷屏关闭。首次新仿真模型编译另计，5400秒测试超时/2百万case0周期是上限非ETA；其余case需另行调用同脚本，可复用模型。旧TCM/Person/VME/Pool/Conv源码、固件和包不改。

本地10项工具检查通过，包括真正MinGW标量运行对独立Python四例签名、错误日志与内存/参数负例、独立安装/拒绝覆盖。使用本地玄铁GCC14.3实际编译新bench及原官方RVV源为RV32目标文件，反汇编确认Scalar无向量指令、官方对象有vwmul/vwmacc；Bash语法检查通过。这些不是官方完整链接、NPU执行或速度证据。真实VM链接/RTL仍待用户运行run.sh 0并回传LLM_LINEAR_ELF_AUDIT和LLM_LINEAR_SUMMARY，不能提前标PASS或声称已获得LLM性能。

旧Conv11、Pool19、VME18、默认Person34项工具回归（合计82项）通过；与新增10项合计92项。仅工具回归，不是92个真实硬件用例；合成打包测试产生的临时archive哈希不作为实际VM/服务器包身份。

### 28.21 LLM线性层case0真实RTL通过：官方RVV相对标量40.16倍

用户回传VM `/home/lqq/coral_tcm_capacity_8e4_v1/llm_linear_c0.brMbDF`：Cocotb一个测试通过、LLM_LINEAR_SUMMARY及最终LLM_LINEAR_PASS。case=decode_tiny，M1/K32/N32、1024 useful MAC/调用；scalar_cycles=[10563,10563,10563,10563]，rvv_cycles=[263,263,263,263]，首次和后三次steady的标量/RVV比均40.163498098859314。空边界3周期，原始计时未扣除。接受流程要求数值/输入输出独立golden、guard、自然halt/无fault/status3/4次调用及身份门限通过；本地没有读取该服务器/VM目录的原始证据，不把用户没提供的ELF审计哈希或wall time补成已知。

这一结果仅针对两种具体实现的resident合成INT8线性层，对decode矩阵形状做微基准；不是执行完整decode、预训练LLM、tokens/s或VME比较。官方RVV源码未改。末尾LLM_LINEAR_PREPARED中RTL=NOT_RUN指生成器复核自身不仿真，不能覆盖同run实际的SUMMARY/RTL PASS。下一步在VM单独执行run.sh 1，使用M16/K32/N32、相同规模K/N的prefill形状，复用相同编译模型，不自动启动其他case或完整网络。

### 28.22 LLM线性层case1真实RTL通过：prefill形状相对标量41.03倍

用户回传VM `/home/lqq/coral_tcm_capacity_8e4_v1/llm_linear_c1.Ye75FC`：Cocotb单测试PASS、LLM_LINEAR_SUMMARY及最终LLM_LINEAR_PASS。prefill_tiny M16/K32/N32、16384 useful MAC/调用；scalar_cycles=[168618,168618,168618,168618]，rvv_cycles=[4110,4110,4110,4110]，首次与steady标量/RVV比均41.026277372262776。空边界3周期未扣。VME/完整模型仍NOT_RUN，实际ELF审计哈希和wall time未回传，不补造。

与case0相比M增16倍，RVV总周期4110/263约15.63倍，基本线性，符合官方matmul逐行调用gemv的源码路线；不是额外跨token复用、完整prefill性能或架构峰值证明。下一步复用同编译模型，显式分别跑case2 M1/K64/N64与case3 M16/K64/N64；脚本本身仍每次只跑一个所选case，不自动切完整模型。此次只更新记录，不修改已测源码或固件身份。

### 28.23 明日集中验证准备：21例算子套件，不启动远程长任务

用户准备睡觉，要求将LLM相关准备工作做好、明天集中测试验证。按其已选定的“先测算子”范围执行，不下载/启动预训练大模型，不擅自运行远程仿真或改动已通过的INT8固件。新增google_llm_ops/transformer独立包llm_transformer_v1，引用原公开llm_linear_v1:model及其同一256/512KiB RTL/参数；原INT8生成器与源码身份保持不变。新增新固件的主机参考、交叉链接、诊断符号/资源审计与前门Cocotb短测。

新增17个FP32用例：官方rvv_matmul.cc原样复制的decode/prefill矩阵乘2例，Gemma式RMSNorm含37维尾部3例，稳定Softmax含±1000输入/尾部2例，split-half RoPE预计算sin/cos2例，SwiGLU/近似tanh式GEGLU各1例，残差1例，KV-cache追加1例，因果GQA Attention的prefill/decode/首token/未来K/V毒化对照4例。两Q头共享一KV头，按绝对query位置限制可见K/V；首token毒化对照确保未来数据不能影响输出。不是官方unmasked测试改名。除矩阵乘外明确为项目FP32基线；Softmax/门控的exp/tanh保持标量libm、完整计入，非全面向量化优化，不承诺提速。RoPE三角表和旧cache初始化在计时外，所有口径明示。

独立Python FP64参考生成并舍入为FP32，C++使用精确十六进制float常量而非uint32类型双关。标量/RVV各首次+3次steady、交替顺序、fence+mcycle，空边界单列不扣。每调用对gold按固定atol2e-5/rtol2e-4核对并检查NaN/Inf/guard，最终前门核对全部实际输入、两份完整输出、自然halt/无fault/status3/4次调用及栈底64字节canary。不是完整栈水位、完整block/多层LLM或持续KV生成；VME、BF16/INT4/模型量化、tokenizer、权重导入、外部AXI流式内存和真实tokens/s均未覆盖。

新增run_all.sh和suite.py：一条明日命令前台串行跑4个INT8+17个FP32，共21例；先prepare_vm.sh进行native资格检查、真实链接与资源/参数审计、缓存模型构建，再逐例运行，保留命令/日志/ELF身份。失败立即停止，部分通过报告INCOMPLETE，不强行继续。支持prepare-only、指定job续测和终止后重新汇总；续测校验工具身份、原始日志哈希、完整结果和FP32 ELF/RTL一致，只有真实未变的PASS才跳过，未完成case从入口重跑，不是CPU checkpoint；不杀其他用户或旧Bazel服务。生成summary.md/json和state.json，每例进度有一次开始/结束，不刷屏。文档TOMORROW.md提供完整命令、恢复方法和证据边界。

本地已实际执行17例native与独立gold对照；本地玄铁GCC14.3将bench/kernels/fixtures及原官方FP32矩阵源编成真实RV32对象，确认RVV归约/乘加、fixtures表1020字节且没有动态初始化。尚未在VM完成此新固件的官方完整链接或任何FP32 RTL，准备脚本/主机/目标文件检查不能提前当硬件PASS；今晚不启动仿真，明天由用户明确执行统一入口。

最终新增16项工具测试通过，覆盖独立数值/因果mask毒化/稳定softmax/RoPE与cache语义、生成器拒绝覆盖、ELF/参数与错误结果拒绝、实际native和RV32编译、BUILD/Python语法及prepare-only→续测→21例汇总的合成控制流。旧INT8 10项、旧Conv/Pool/VME/默认Person共82项回归通过，合计108项工具检查；不是108次硬件测试。Bash语法与CLI帮助检查通过。用户已有.gitignore修改、RTL归档及其他未跟踪材料均保留，不纳入提交；只同步个人实验仓库，团队SoC库不改。

### 28.24 仿真迁移服务器：VM只构建导出，保留原测量函数和模型身份

用户不方便在VM仿真，明确仍可短时间在VM构建，故不要求CentOS7服务器运行当前Bazel。新增google_llm_ops/export_server.sh：复核原INT8/FP32候选源，native参考只在主机执行标量；实际链接两份ELF并发出同配置RTL以核对SHA/参数，不编译Verilator模型、不运行RTL。通过完整资源审计、原始host日志及源快照校验后生成coral_llm_ops_i256_d512_v1小包（无RTL/权重），归档SHA以用户实际输出为准。本轮不修改原已安装候选生成器/内核/bench或旧测量固件。

新增server/packet.py、server_ops.py、server_bench.py，封存并检查实际固件/审计/源文件/许可证/工具清单。使用原Pool的固定哈希model_runner校验器，核验原producer/环境/编译配方/二进制/短probe原始日志及XML证据；持其锁只读复用7a54106b3148.z558xni8模型，不改current_build或原包。用AST保留原run_case测量函数体，移除Bazel测试入口，仅用严格白名单替换文件定位，避免复制后悄悄改变计时范围；特别隔离Person和LLM同名spec模块，防止导入污染。清除WAVES/GUI/分析变量，沿用无trace模型。修正导出时INT8/FP32 rtl-identity一个带top、另一个不带top的元数据差异，只按相同RTL SHA和实际参数比较，不降低身份要求。

服务器先check和单例pilot，再all串行21例。每例独立frontdoor加载同ELF，从入口开始，不是checkpoint；原始XML、Cocotb summary、单条观测、process退出、数值/guard/halt/fault/四次mcycle及ELF/RTL身份全部需一致。失败即停，保留attempt；resume重新验证包/环境/模型/旧结果的原始证据，只跳过未变的完整PASS。summary.md/json逐例更新，只有完整计划通过才JOB_PASS；4+17套件通过也不是完整LLM/VME/真实tokens/s。不会自动启动后台或远程仿真。

本轮新增14项本地工具测试，含AST测量体逐字语义结构保持、路径白名单、同名模块异常恢复、实际原始验收逻辑覆盖21例、XML失败/跳过/超时/身份/预算/重复日志拒绝、部分报告/证据篡改拒绝、子进程去trace、合成完整导出往返及合成失败停止→续测→21例汇总。这些用合成ELF/运行记录检查控制流，不是新的官方ELF或RTL结果。真正VM两ELF链接、小包SHA和服务器FP32运行仍待用户执行；旧INT8 case0/1真实结果保持28.21/28.22。当前入口SERVER.md覆盖旧VM队列说明，不修改共享SoC仓库或未相关用户文件。

最终复跑新增14项、FP32 16项、INT8 10项及旧Conv11/Pool19/VME18/默认Person34项，合计122项工具测试通过；FP32/INT8的native与RV32对象检查均实际执行，无跳过。新导出脚本Git Bash语法检查通过，仍未运行Linux官方链接/服务器仿真。git只包含本轮新工具及入口/历史文档，未相关用户修改保留。

### 28.25 实际VM包分析失败：修复FP32 native cc_test头文件属性

用户回传FP32 host_reference_test在BUILD第10行分析失败：cc_test没有hdrs属性。该处为新增工具错误，不是NPU执行、算子数值或RAM容量失败；前一段test-size提示与本错误无关。原122项本地工具检查包含Python/BUILD语法与直接C++编译，但没有在Linux Bazel实际加载此规则，故未发现非法属性，不能继续将工具通过等同真实Bazel构建验证。

修改tx_prepare.build_text仅将native cc_test的kernels.h从hdrs移至srcs。只读核对固定上游rules/coralnpu_v2.bzl，自定义coralnpu_v2_binary明确接受hdrs，故固件规则保持不变，内核/bench/fixtures/RVV源/参数/计时逻辑也不改。将expected文件集合提取成函数，以供显式修复复核；生成器自身哈希因此有意变化，不能让用户直接重跑而撞上旧manifest拒绝覆盖。

新增repair_host_build.py，只允许旧生成器SHA 5fb56201aa51bd0b1020a32c8df386774247c6796e6ee2ca6d9c094ffcad4b4c的完整已知manifest和全部原始候选文件，核验为精确单行BUILD差异后，将旧BUILD/manifest及修复记录保存到study/llm_tx_host_hdrs_repair.*，再同目录原子替换BUILD和manifest。未知manifest、用户改过的源/BUILD或符号链接均拒绝，不删除缓存，不改旧实验或固件；重复运行只复核，若两次替换之间中断可安全补完。常规prepare仍拒绝未知修改，不放宽验收。

新增5项回归：native cc_test属性语义、备份/幂等、未知编辑不覆盖、部分升级恢复，以及从git读取真实7bb95c5旧生成器生成manifest后完成升级。下一步VM pull→显式repair→export_server.sh；只有用户实际链接和服务器结果才能验收，当前无新增FP32 RTL PASS。

本轮实际复跑FP32 21项、服务器适配14项、INT8 10项，合计45项工具检查通过，无跳过；native标量参考和RV32对象检查实际运行。仍未在本机执行Linux Bazel分析/官方链接，等待VM回传，不以此宣称所有构建问题已消除。

### 28.26 用户回传两ELF实际链接与小包导出；转入服务器pilot

用户实际完成VM导出，job `/home/lqq/coral_tcm_capacity_8e4_v1/llm_server_export.HJkCC5`。INT8 ELF SHA 17b3e2b6a5c208f638db2d7b85f4ddc5f8f64c336290093a9a11ce06a3dd072d，ITCM占用2976、DTCM静态13536、heap剩余494368字节；FP32 ELF SHA ab1c95f0398f1e1ee43a0bc7b94677daebe21fdb4ff359046ce7eecf2c81f312，ITCM占用10992、DTCM静态59808、heap剩余448096字节。两者均在256/512KiB配置内，日志NPU_RTL=NOT_RUN表示审计不执行硬件，不当仿真失败或运行PASS。

实际归档coral_llm_ops_i256_d512_v1.tar.gz，210545字节，SHA fab74b4ff7ff643474d10f6b5d6513100e11d66cc8b291c9aca5abe7d2805b25，LLM_SERVER_PACKET_READY RTL_included=false simulation=NOT_RUN。与本地合成测试生成的任何归档分开，此哈希仅来自用户实际VM输出。旧VM INT8两例未回传旧ELF哈希，不能将此次新链接SHA自动当其同字节证据；服务器将对新包重新执行pilot。

下一步提供VM传输到服务器coral_person_packages/llm_fab74b4f独立目录和服务器验SHA/解包/环境/check/INT8 case0前台命令；只读复用原Pool包及probe.46bl5uqr，check失败不改旧模型/环境记录，不重编大RTL。先pilot后再21例串行，不擅自启动完整LLM或长后台队列。目前尚无服务器新算子结果。

<a id="section-29"></a>

## 29. 服务器LLM算子进度：完整21例已通过（2026-10-22，第29.5节为最新）

### 29.1 新小包的服务器RTL pilot实际通过

用户回传LLM_SERVER_READY cases=21 simulation=NOT_RUN，以及随后真实执行LLM_SERVER_JOB_PASS cases=1。READY只表示核验完可复用模型，不代表21例运行。原模型路径为`/data/home2/lqq/Desktop/coral_person_packages/pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1_verilator_runtime/builds/7a54106b3148.z558xni8`，本次只读复用，不重编、不改原producer/current_build或封存包。

新小包与两ELF身份沿用28.26：归档fab74b4ff7ff643474d10f6b5d6513100e11d66cc8b291c9aca5abe7d2805b25（210545字节），INT8 ELF17b3e2b6a5c208f638db2d7b85f4ddc5f8f64c336290093a9a11ce06a3dd072d、FP32 ELFab1c95f0398f1e1ee43a0bc7b94677daebe21fdb4ff359046ce7eecf2c81f312，固定ITCM256KiB/DTCM512KiB。本地文档不是远程原始ELF/完整日志，身份依据用户导出及运行输出，不冒充直接读取服务器。

服务器最新单例job：

```text
/data/home2/lqq/Desktop/coral_person_packages/llm_fab74b4f/coral_llm_ops_i256_d512_v1_server_runtime/jobs/operators._jxei5s3
```

attempt为`attempts/int8_0.g3eqoi8b`，原始`_test.log`及XML/退出状态/result保存在该处；job保存job.json、completed和summary.md/json。用户回传的case=decode_tiny，M1/K32/N32、1024MAC/调用，标量=[10563,10563,10563,10563]、RVV=[263,263,263,263]，空边界3周期未扣，首次/steady标量/RVV=40.163498098859314，与旧VM case0相同。不是旧/新ELF逐字节等同证明（旧VM ELF哈希未回传），不是完整decode/LLM、VME或架构峰值速度。该pilot墙钟未回传，不能补造。

### 29.2 已提供21例前台串行命令，但尚未确认其启动/结果

随后给出server_ops.py all、每例timeout5400、tee到新llm_ops_all.*.log的服务器命令，将重新运行4例INT8+17例FP32，新建job。没有收到这套的LLM_CONSOLE_LOG、JOB_DIRECTORY、CASE_PASS或最终JOB_PASS，因此状态只能写“命令已提供，待确认启动和验证”，不能写“正在运行”“已跑完”或“21例全通过”。后续接手先问现有日志/路径，避免启动重复任务。

新增FP32包括官方matmul2例、项目RMSNorm3、Softmax2、RoPE2、SwiGLU/GEGLU2、残差1、KV追加1、因果GQA Attention4；除矩阵乘外不是原官方Gemma优化内核，exp/tanh仍标量libm且计入。FP32 native参考与正式交叉链接已完成，但尚无真实FP32硬件结果。单例cases=1不能resume成21例计划；整套只能以新job的完整计划及原始证据验收，旧失败日志不删除。

### 29.3 耗时预估约定：每次给命令必须先说明

用户要求以后每次仿真均先告诉预计实际等待多久。已答复本次完整21例粗估1～3小时、建议预留3小时，不含编译（模型复用）；4例INT8粗约20～30分钟。估计参考此前服务器Person等负载约2800～3000周期/秒及本轮规模，FP32首次、libm和共享负载使置信度低；不是本轮21例实测或完成承诺。5400秒是每例90分钟上限，周期预算是停止门限，都不是预计耗时。每例实际时间回传后应修正预测，超过粗估不直接判死锁。

### 29.4 本轮进度/交接文档重整，不改变实验身份

用户要求完善进度与交接。新增PROGRESS-current.md作为统一日期快照，按准备、实际链接、模型复用check、单例RTL、整套、完整模型分等级；列出已完成、尚未回传和范围限制。将原HANDOFF-current.md全文完整保留为HANDOFF-archive-before-llm-20261022.md，加历史警示，不删除阶段命令和故障记录；重建HANDOFF-current.md为当前接手指南，包含团队/个人职责、三机分工、RAM/地址/资源、精确包/模型/probe/pilot路径、只读查看、避免重复任务、前台all与证据恢复命令、材料清单、验收判据和耗时约定。旧TCM命令锚点保留指向历史，不再作为默认任务。

同步更新LLM README/SERVER/TOMORROW，纠正“FP32待完整链接”“服务器pilot未做”“明天默认VM跑”等过期现态。旧默认Person、Pool、Conv、TCM专题仅加当前范围覆盖提示，不重写原始结果、不重打包封存工具。当前真正未完成的是FP32硬件正确性/周期、21例完整报告以及后续完整block/模型、持续KV/tokenizer/权重、VME/低比特/AXI流式和SoC/PPA/门仿，不因旧Person单图或几何抽样PASS而升级。

本次只编辑文档，不启动/监控/停止远程仿真，不改RTL、ELF、内核、计时或验收工具，也不访问服务器完整日志；所有“运行状态”来自用户回传而非实时发现。未相关用户工作区修改保留，个人仓库同步不涉及团队SoC库。

完成后校验16份本轮文档的134个本地链接/显式历史锚点，确认原交接正文完整保留；当前交接和LLM操作页的Bash代码块通过bash -n语法检查（未执行）。核对最新pilot路径/两ELF/包SHA及周期，git diff --check通过。未重跑122/45项工具测试或任何RTL；本次只作文档链接、语法和证据一致性核对，不能标成新增仿真通过。

### 29.5 用户回传完整21例RTL PASS，首次FP32硬件结果成立

用户提供完整控制台`/home2/lqq/coral_vcs_tools/llm_ops_all.mXLd8a.log`，job为`/data/home2/lqq/Desktop/coral_person_packages/llm_fab74b4f/coral_llm_ops_i256_d512_v1_server_runtime/jobs/operators.cgtja4_x`。包含21个CASE_START、4例INT8+17例FP32的21条CASE_PASS，最终LLM_SERVER_JOB_PASS cases=21 full_model=NOT_RUN VME=NOT_RUN。原Pool模型7a54106b3148.z558xni8继续只读复用，小包/两ELF/RTL身份不变。不是旧pilot cases=1，前面29.2待回传状态已成为历史。

本机独立解析附件，核对所有名称/次序/ID/形状、四次样本、比值和FP32误差摘要，均一致且无遗漏/重复/STOP。附件字节SHA d4a5d8e5e20d69a95bfdd7147322cd6444fdd0961c63f8e9fae66f5d821669de；该哈希只标识用户提供的控制台，不替代服务器原始XML/test.log证据。本机没有登录服务器或独立复跑，不能将摘要核对描述为另一次完整数值/guard验收；工具打印PASS前已按其封存程序验收，原始材料需后续备份。

所有case每路径首次+3次steady的周期均相同，空边界3周期未扣。INT8四例：10563/263=40.163498倍、168618/4110=41.026277倍、41571/577=72.046794倍、664746/9134=72.777097倍，后两例现在有首次硬件结果。FP32矩阵乘6574/525=12.521905倍、26008/905=28.738122倍；RMSNorm2.259608～2.829279倍、RoPE4.972973～6.460094倍、残差5.956714倍、KV追加4.264706倍、因果GQA Attention1.674249～1.750141倍。Softmax1.120948～1.125964倍，SwiGLU1.010291、GEGLU1.008415倍。逐例完整数据见google_llm_ops/RESULTS-20261022.md。

FP32最大报告绝对误差4.76837158203125e-7，通过固定atol2e-5/rtol2e-4；部分误差0不推广到任意输入逐位一致。首token与future-poison因果对照均通过，仅限当前fixture/位置覆盖。矩阵乘是原样官方实现，其余项目基线仍含标量libm；Softmax/门控收益有限与该源码相符，但没有逐函数profiling，不虚构具体libm时间占比。不能平均21种不同比值称为LLM加速，更不能把72倍外推到整网、VME或tokens/s。

本次控制台没有逐case/总墙钟或起止时间，实际总耗时未知；此前1～3小时仍为粗估，不改写成“实测已用”。当前下一步只读回收summary.md/json、job.json、completed与attempts原始日志/XML/退出状态。summary每case timing.elapsed_seconds可求子进程墙钟和，但不含case间核验开销，不能当严格套件总时间。接手指南已改成先读取完成job，不重复启动all；不为测耗时再跑一遍。

同步更新进度/交接/LLM入口，保留旧阶段说明为历史。下一项实验由用户决定：代表性规模/尾部/数据范围、混合libm瓶颈优化或VME/RVV对照；完整block/预训练LLM、权重/tokenizer/持续KV、AXI流式/低比特、SoC/PPA/门仿仍未完成。本轮不改工具/内核/固件/RTL，不启动任何新仿真。
