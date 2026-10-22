# 阶段2b：固定调度下的数据驻留与外部搬运

**2026-10-22范围覆盖：** 下方为历史容量实验设计/待办，原结果保留；2/4MiB和T768不自动继续。当前单NPU固定ITCM256KiB/DTCM512KiB，已转LLM算子，见[最新进度](../PROGRESS-current.md)。旧工作集固定ITCM8KiB不能直接代表当前固件需求。

## 当前状态

最新回传：Ubuntu1/2MiB T384完整配对PASS，同prefix策略少17.07%周期/40.92%权重外读；VCS1MiB/T384及2MiB/T12亦PASS。服务器独立Verilator1MiB/T12、T384均正式PASS、精确匹配VCS，耗时429.077/13979.842秒。VCS2MiB/T384最终状态仍待回传，下一步准备2/4MiB T768及各自的Verilator T12。ITCM仍8KiB，延迟8和真实模型没有完整结果。早期失败保留，最新数字见[结果记录](WORKSET-results.md)，续接见[交接指南](../HANDOFF-current.md)。

阶段1容量检查与阶段2a计算控制组六档均收到Ubuntu实际RTL PASS，六份完整控制日志也已由用户在Ubuntu比较通过，结果日志为`/home/lqq/coral_tcm_capacity_8e4_v1/control_compare.L0Pxte.log`。

**早期T12结果**：Ubuntu32/128KiB均完整PASS并通过跨容量比较；每档两策略各重复3次、输出及软件/AXI计数通过。两档stream均225219周期；同prefix策略由205177降到145026周期，少29.32%，权重读取由120KiB降到48KiB。后来1/2MiB T384亦完整PASS，见[工作集结果](WORKSET-results.md)；没有4MiB工作集或整模型结论。

仍只测一个官方NPU，ITCM固定8KiB，DTCM保持32/128/512/1024/2048/4096KiB，一周期RAM行为模型。准备器验证两个旧阶段及六档完整控制日志身份后，在单独`tests/cocotb/tcm_workset/`增加包和独立manifest，不改已通过的源码或两个旧manifest。新测试目标需要emit同参数RTL/编译模型，复用下载和编译依赖缓存，不用旧870版本产物替代。通常任何残缺安装/文件指纹变化都会停止；下面仅为已知超时笔误提供严格、带备份的一次性升级，不清缓存。

### 2026-10-16：0ns超时单位错误修复

cocotb 2.0的秒单位是`"sec"`而不是`"s"`；本次选择通用的`timeout_time=2000, timeout_unit="ms"`。错误出在测试框架参数，不能据此判定NPU算术失败。

`run_workset.sh`在普通安装校验前调用`upgrade_workset_timeout.py`：无旧安装时不迁移；已有正确版本时严格验证后不改动。只有旧benchmark SHA为`032faeff95adc4080c117f332c8f15ef664288e86bfa5c1cc6218944a91cd992`、全部33个安装文件、5个工具指纹以及旧容量/控制基线均匹配时才升级。先在实验目录下建立`workset_timeout_upgrade.XXXXXX`，保存原manifest、原benchmark和迁移记录，再仅替换六档生成benchmark中的这一行、更新工作集manifest指纹并记录迁移历史。RTL、固件、BUILD、两个旧manifest、旧运行目录及Bazel缓存不改动；任何未知修改或部分升级均停止。若升级被中断，请保留备份和报错，勿手动重建manifest绕过验证。

本次本地完整回归56项通过，新增超时单位、精确旧版本迁移、备份一致、幂等、缺文件/篡改/部分升级/错误基线及混入其他benchmark改动的拒绝检查；另通过Shell语法检查。这些检查本身是静态/合成验证；用户随后重跑32KiB/T12/等待0已回传实际RTL PASS，详见上述结果记录。

### 2026-10-17：MiB级测试触发Bazel一小时墙钟上限

1MiB DTCM、T384、额外读等待0的首次实际运行被Bazel在3600.1秒终止，并非cocotb的2秒仿真时间上限。日志已完成stream的repeat=0/1，均逐项检查294912个输出，等待halt均6885516周期；尚无第3次重复、prefix策略或完整PASS。该组状态为INCOMPLETE，不能参与跨容量性能比较。

原因是Bazel的`timeout="eternal"`默认仍为60分钟，并非无限，见[Bazel9.1测试超时定义](https://bazel.build/versions/9.1.0/reference/be/common-definitions#test.timeout)。运行器现在在真实test命令和保存的命令中均显式传入`--test_timeout=21600`，将整项测试的墙钟上限设为6小时；可用`TCM_WORKSET_TEST_TIMEOUT_SECONDS`设置1～86400秒的正十进制整数。它不包括构建时间，不是预计耗时，也不保证6小时内通过。

此次只改运行器：不改生成BUILD、RTL、固件、两策略各3次重复、golden、AXI判据、2秒仿真时间限制或每次内核一亿周期保护，也不修改安装manifest。Bazel模型/编译缓存和旧运行目录保留，但没有仿真checkpoint，需从头重跑六次，不能把本次两条PASS拼成完整通过。原始计算耗时瓶颈尚未profile，本日志只能确认墙钟限制被触发。

运行器现在会保存测试开始/结束UTC时间、墙钟耗时、配置上限、Bazel/tee退出码；即使test失败/超时也尝试复制原始test.log，打印`[TCM_WORKSET_INCOMPLETE]`后保留非零退出，不执行摘要/PASS。没有test.log、tee写入失败、残缺重复均拒绝通过。继续使用`--noshow_progress`和`--test_output=errors`，不增加每几秒输出。

本次完整本地回归64项通过，新增真实Bash+假Bazel的墙钟参数校验、超时退出/原始日志保存、日志缺失及tee失败拒绝、正常退出仍进入严格日志检查，以及两条已完成记录不能冒充整组PASS的测试；Shell语法通过。这不等同于MiB级RTL重跑通过。

## 工作负载及策略边界

2026-10-17：为避免CentOS7的Bazel/glibc限制，新增[Ubuntu导出、服务器独立VCS运行](../google_tcm_vcs/README.md)工具。原始单文件RTL必须与对应容量控制组PASS的SHA一致；同一ELF、SRAM C++源码、cocotb fixture/观察器与严格判据均保留。服务器本地编译DPI和VCS，先小工作集完整通过再允许大工作集；不是纯SV测试平台，也不承诺加速。导出建立时未完成VCS验证；后续实际导出、编译和运行状态见[导出记录](../google_tcm_vcs/EXPORT-results.md)，本轮旧Verilator结果及manifest不因此改写。

权重由T个4096字节块组成，每块K256×N16；三个不同输入块各M16×K256，对每个权重块产生16×16 INT32输出。整体相当于M48、N16T、K256的分块GEMM，输出按`输入轮次,权重块,行,列`排列。所有输出均用先扩展INT64的NumPy golden逐元素校验，输入+golden SHA跨容量不变。

固定顺序为**输入轮次在外、权重块在内**。这可作为顺序输入复用权重的受控实验，但没有模拟真实输入到达时间、deadline、算子图或编译器最优调度。

- `stream`：每次使用权重都由NPU从外部重载，同容量下的无驻留对照。
- `prefix_cache`：保留固定前缀权重；超出容量的权重使用一个流式槽。首轮所有权重都必须加载，后续轮次只重载非驻留部分。

**这里比较的是指定软件调度/驻留策略的周期，不是大SRAM必然必要或所有模型的最优加速。** 改为权重优先、缓存多个输入或重排计算，可以在小DTCM下改变权重重载量，并可能改变结论。尤其当前三个输入总共12KiB，另一种程序可能保留多个输入后调换循环；本阶段有意固定输入优先顺序，不能把此合成结果直接变成选2/4MiB的结论。后续实际模型及备选调度仍需评估。

## 存储布局与容量利用

同一ELF使用ITCM8KiB、DTCM16KiB链接配置、1KiB栈，代码/状态/4096字节输入/1024字节输出及堆栈均限制在低16KiB。链接器脚本保持实验映射，不为不同容量重链接不同ELF。

| 区域 | 地址 | 用途 |
| --- | --- | --- |
| ITCM | `0x00000000`，8KiB | 程序及其只读段，装载前完整NOP填充 |
| DTCM软件保留区 | `0x01000000`，16KiB | 输入暂存、输出暂存、参数/计数器、堆栈 |
| DTCM权重池 | `0x01004000`起，到DTCM末尾 | 4096字节/槽 |
| 外部输入 | `0x20000000`起，12KiB | 三个输入块 |
| 外部权重 | `0x20010000`起 | 最大3MiB权重 |
| 外部输出 | `0x20400000`起 | 三轮全部输出 |

外部代理backing memory扩大到16MiB只是仿真容纳数据，不是RTL片上RAM，不是当前Cheshire窗口或真实DDR容量修改。所有ELF加载段必须局限ITCM8KiB和DTCM低16KiB；权重池与栈不重叠。主机只在测量前初始化外部内存/ELF/毒值，**不预先把正式权重放进DTCM**。正式数据搬运由NPU的128bit向量load/store循环执行，不调用DMA或libc memcpy。

令`S=floor((DTCM字节数-16384)/4096)`。stream的驻留数R=0；prefix模式若T≤S，R=T，否则R=S-1，余下一槽用于流式权重。

三轮的预期权重读取量：`4096 × (T + 2 × (T-R))`。此外，两策略都读取12KiB输入、写回`3×T×1024`字节输出。这些是**计划预测，不是实测性能**；软件计数和实际AXI握手字节必须分别与之吻合。

首个T12、48KiB权重用例：

| DTCM | stream权重读取 | prefix驻留块 | prefix权重读取 |
| --- | ---: | ---: | ---: |
| 32KiB | 144KiB | 3 | 120KiB |
| 128KiB及以上 | 144KiB | 12 | 48KiB |

后续可选T：2、12、120、192、384、768，分别为8KiB、48KiB、480KiB、768KiB、1.5MiB、3MiB权重。先跑通小用例并记录真实耗时，再决定MiB级测试规模，不一次性启动全组合。

## 计时、统计与判据

- 每个策略独立复位后跑3次；每次输入、输出缓冲和实际使用的权重槽毒值初始化。需要算术、软件完成状态、计时和全部AXI计数一致且重复稳定。
- `wait_for_halt_cycles`沿用固定fixture口径：启动CSR操作后等待halt的周期，包含计数窗口内CRT、冷启动搬运、计算、输出写回和结束；不包含主机装载和结果检查，也不覆盖全部启动CSR事务。
- 程序读机器态`mcycle`低32位（`0xb00`）记录总内核、每轮、输入搬运、权重阶段、矩阵计算+读出、输出搬运窗口。各计时点含fence/CSR开销，**不是纯阵列或纯总线延迟**。命中与未命中的权重阶段使用相同次数的计时读取/屏障，不因少测计时点而制造加速。
- `ws_total_cycles`须不超过fixture等待周期；各阶段之和和三轮之和须不超过内核总窗口。计数循环最多一亿周期，避免32位计数差溢出。
- 只读观察NPU master AXI，不修改原代理：捕捉下降沿稳定状态，在随后的上升沿按valid&&ready接受统计AR/AW/W/R/B，处理事务ID、RLAST、响应错误、未完成请求及WSTRB有效字节。未知地址、跨4KiB非法请求、漏响应、读写字节与计划不符都拒绝通过。
- 外部读请求必须只落在输入/权重区域，写请求只落在输出区域。若意外发生外部取指，观察器会拒绝，不把取指流量混入数据读取。
- 外部读服务前附加等待可选0/8周期，通过原官方fixture的`read_delay_cycles`实现。0仍有代理握手和服务开销；8是每个读请求附加等待假设，**不是测得的SoC SRAM/DDR参数**。比较时必须保持相同延迟设置；两种延迟分开比较。

## Ubuntu：先32KiB、T12、额外读等待0

本目录的局部`.gitignore`仅忽略Python的`__pycache__/`、`.pyc`、`.pyo`，不隐藏源码或其他修改，也不删除缓存。若旧版本在pull前被唯一的`?? verification/google_tcm_capacity/__pycache__/`拦住，可在确认只有这一项时先pull新规则；任何其他改动仍应停下核查。普通Python运行可能产生缓存，正式脚本继续使用`python3 -B`。

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
if [ -n "$(git status --porcelain)" ]; then
    git status --short
    echo '存在未提交修改，停止，不自动覆盖。'
    exit 1
fi
git pull --ff-only origin main
python -B -m unittest discover -s verification/google_tcm_capacity -p 'test_*.py' -v
bash verification/google_tcm_capacity/run_workset.sh 32 12 0
)
```

脚本参数依次是DTCM KiB、权重块数、额外读等待周期，第四个可选参数是实验目录。默认仍沿用`$HOME/coral_tcm_capacity_8e4_v1`；源码/缓存/旧结果均保留。Bazel和make并行2、内存预算4096MiB，关闭频繁进度刷新；运行器显式覆盖测试墙钟上限为21600秒（6小时，可用上述环境变量调整），不再依赖eternal的默认一小时，也不是运行时长承诺。ELF通过cquery取准确配置路径并检查RISC-V ELF32，不再猜`bazel-bin`的固件路径。

完成后回传两行`[TCM_WORKSET_SUMMARY]`、`[TCM_WORKSET_PAIR]`和`[TCM_WORKSET_PASS]`；失败则回传首个错误和`[TCM_WORKSET_RUN_DIRECTORY]`。新目录为`workset_d32_t12_r0.XXXXXX`，含manifest、构建/测试命令和日志、参数头、ELF、hash、原始test.log及摘要。

先确认本用例PASS，再用同样T12/等待0测128KiB。两档实测后再用`prepare_workset.py compare --logs <两份真实test.log路径>`比较相同ELF、布局、输入和延迟假设。不要混合不同T或不同延迟的日志；比较器会拒绝。此处尖括号为占位符，不要原样执行。
