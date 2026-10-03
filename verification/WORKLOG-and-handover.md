# CoralNPU 选型、验证、性能比较与 RTL 交接全程工作记录

记录日期：2026-10-04。对象：接替 NPU 工作的同学、SoC 集成人员、综合及验证人员。

本记录汇总从两套工程下载、跨平台同步、网络与工具环境搭建，到矩阵功能测试、整核性能比较、团队候选仓库和 RTL 综合交付的工作。目标是让接手人不依赖聊天上下文也能继续。它不是流片签核报告，也不把未执行的工作写成已完成。

本次整理开始时，比较仓库 `main` 与本地 `origin/main` 均为 `e3046dc`。文中的固定提交和压缩包哈希是历史基线；以后更新仓库时不要把它们自动替换为新版本。

### 目录

- [1. 当前状态与接手路线](#section-1)
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

<a id="section-1"></a>

## 1. 接手人先读：当前已经到哪里

### 1.1 项目目标及已经确定的方向

团队处于 SoC 前端设计早期，准备流片。NPU 工作最初是比较官方 CoralNPU 与 Yangg152 分支的矩阵单元，判断是否能跑通、性能如何、后续需要什么验证。

后来已经明确：**最终要集成整个 CoralNPU 核到 SoC，不是只拿一个独立矩阵阵列。** 因此选型不能只看 PE 的乘加周期，还要看整核指令、装载、结果读回、软件支持、RAM、AXI 和 SoC 集成成本。

目前官方工程作为候选版本单独保存在团队组织中，并已准备保留原仿真配置的整核 RTL 给组员综合。它是候选基线，不是已经完成最终选型或签核的 IP。

已经明确或暂定的事项：

- Windows 修改代码，通过 Git 同步到 Linux，Linux 运行验证。
- 实验室 CentOS 7 服务器主要用于 VCS 独立 MXU 测试；较新的 Ubuntu 虚拟机用于 Bazel、Chisel 生成及两套整核 Verilator/cocotb 仿真。
- 本轮性能比较以 signed INT8 输入、INT32 累加/输出为主。真实 uint8 需求暂缓，不能据此说 uint8 问题已经解决。
- 目标频率暂定 200 MHz，后续用 DC/实际工艺库评估；目前没有频率达标证据。
- 综合组员先接收官方整核 RTL，再回传网表、库模型、约束等，之后准备门级仿真。

### 1.2 当前结论一页表

| 项目 | 当前状态 | 结论边界 |
| --- | --- | --- |
| 官方整核 RTL 生成 | 已成功 | `VmeCoreMiniAxi`，外部 AXI 取指开启，ITCM 8 KiB / DTCM 32 KiB |
| 官方原有 VME 基础回归 | 用户报告 12 个目标通过 | 不是仓库所有测试或所有 ISA 模式都已验证 |
| 两套 signed INT8 正负数压力测试 | 同向量 32 个用例均通过，每套 8192 元素 | 已覆盖选定四符号组合、极值、随机模式；不是穷尽证明 |
| 官方 K 边界 | Tk=1 路径，21 个 K 值通过 | 不是逐个验证全部 1～256，也不是优化尾部模式的性能测试 |
| Yangg152 K 边界 | 43 次运行：24 PASS / 19 FAIL | 18 次非 16 对齐 K>16 算术失败，另一次输出停顿测试失败；未修复 |
| Yangg152 true uint8 | 明确失败 | `cfg_signed` 未驱动 unsigned 运算路径；未修复 |
| 非满 M/N、非对齐 K | 补零驱动的模型形状测试通过 | 补零是软件适配，不代表原生任意形状或没有效率损失 |
| K>256 和多输出 tile | 2 个逻辑形状、5 个输出 tile 的分块/分段测试通过 | 不是完整模型，也不是两边同口径速度测试 |
| 同端点整核 7 用例、22 用例扫描 | 用户返回完整比较结果 | 官方 Tk=4 在这些任务中周期更少；不同核和驱动，不是纯阵列/PPA 结论 |
| 单次启动共享 B 的 9 组批处理 | 双方通过并返回比较 | 两边 B 复用策略不同，官方每 tile 重载 B，fork 复用权重 SRAM |
| fork 权重每 tile 重载对照 | 代码和命令已准备 | 紧急 RTL 交付打断后，尚未收到执行结果，接下来可继续这里 |
| 官方候选仓库 | 已建立团队私有候选仓库 | 没有把 NPU 集成到 Cheshire 主仓库的 RTL/互连 |
| 当前推荐 RTL 包 | 已接收、核对哈希和 262 个包内文件 | 原始 RTL 未改；只保留已有通过日志，没有新跑功能仿真 |
| DC、STA、LEC、门仿、完整 AI 模型 | 尚未完成 | 不得把 RTL 打包成功或功能仿真 PASS 当作这些工作的结果 |

### 1.3 最短接手路线

1. 拿到个人比较仓库及 Ubuntu 工作目录，不要先清理 Bazel 缓存。
2. 阅读本记录第 8～11 节理解测试结论，尤其不要继续用早期“独立单元 vs 整核”的数字排名。
3. 综合交接使用第 13 节的 `docs_v2` 仿真包，不能拿旧 `prod` 包替代。
4. 保存 Ubuntu 和 EDA152 原始日志及当前提交，再执行第 16.5 节尚未完成的权重复用对照。
5. 与团队确认模型、量化、RAM 工艺、SoC 地址映射等决策；网表回传后按第 15 节进入门仿。

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
| 团队 SoC 仓库 | https://github.com/cheshire-coral-soc/cheshire-coral-soc | 后续 SoC 主工程；本轮没有完成 NPU 接线集成 |
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

## 13. RTL 交付：必须明确旧包、原始仿真包、文档版三个身份

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

### 13.3 当前推荐文档更新版：给综合组员这一包

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

## 15. 尚未完成的工作、团队决策和验证路线

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

## 16. 接手后的执行命令

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

## 19. 交接验收清单与更新约定

接手时逐项确认，不要求现在就把所有后续工程做完：

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
