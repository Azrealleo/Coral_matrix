# 阶段2b结果：固定输入优先调度下的权重驻留

依据用户回传的Ubuntu真实RTL仿真摘要整理；Windows侧没有直接读取完整原始test.log。本记录不替代Ubuntu目录内的原始日志、manifest、ELF和产物指纹。

最新回传：Ubuntu1/2MiB T384、VCS1MiB T384及2MiB T12已完成。Server Verilator1MiB T12/T384现均完整PASS，精确匹配VCS，429.077/13979.842秒，详见文末。当前准备2/4MiB T768、先各容量Verilator T12。前面首次TIMEOUT/trace失败保留；见[接手指南](../HANDOFF-current.md)，依据用户日志/摘要，不声称直接读取Linux完整目录。

## 32KiB、12权重块、外部附加读等待0：PASS

- 官方源码：`8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，保留团队两个生成补丁及实验统一地址图。
- 单NPU，ITCM8KiB、DTCM32KiB，一周期RAM行为模型；程序与判据见[实验说明](WORKSET.md)。
- 用户回传cocotb 1/1 PASS、`[TCM_WORKSET_VERIFIED]`及`[TCM_WORKSET_PASS]`。
- Ubuntu结果目录：`/home/lqq/coral_tcm_capacity_8e4_v1/workset_d32_t12_r0.QV8Sn5`。
- ELF SHA256：`a8aa2d6feaefd56a5901f8bcca4f8f6bbf5394932add092243aff8f5eb497192`。
- 输入+golden SHA256：`5f48b97cefb656ad1e4a96dc80a3f42804ed86d9c0553dade288d14519ebeb93`。
- M48、N192、K256，12个4KiB权重块共48KiB，三个不同输入轮次；每策略独立重置重复3次。
- 每次检查9216个INT32输出元素、执行2359296个有用MAC；两策略合计6次运行、55296个输出元素检查，重复周期/计数一致。

### 同容量下的策略对照

| 指标 | stream | prefix_cache |
| --- | ---: | ---: |
| DTCM权重槽总数 | 4 | 4 |
| 驻留权重块 | 0 | 3 |
| 实际使用槽数 | 1 | 4 |
| 外部权重读取字节 | 147456（144KiB） | 122880（120KiB） |
| 外部输入读取字节 | 12288 | 12288 |
| 外部输出写入字节 | 36864 | 36864 |
| AXI读请求/完成事务数 | 9984 / 9984 | 8448 / 8448 |
| AXI完成读字节 | 159744 | 135168 |
| AXI写请求/完成事务数 | 2304 / 2304 | 2304 / 2304 |
| AXI请求输出字节/有效写字节 | 36864 / 36864 | 36864 / 36864 |
| 输入搬运CSR周期 | 10002 | 10002 |
| 权重阶段CSR周期 | 120384 | 100362 |
| 计算及读出CSR周期 | 60336 | 60336 |
| 输出搬运CSR周期 | 32148 | 32148 |
| 内核CSR总周期 | 224975 | 204929 |
| 第0/1/2轮CSR周期 | 74978 / 74978 / 74978 | 74988 / 64950 / 64950 |
| fixture等待halt周期 | 225219 | 205177 |

本次AXI读/写各拍16字节、每事务一拍；读拍数等于读请求数，写拍数等于写请求数。软件搬运字节计数与实际AXI握手字节均与计划一致。这里的CPU向量复制循环及代理开销属于实验的一部分，不是DMA/突发访问最优带宽结果。

### 结果解释与限制

保留3个权重块后，后两轮不再重载这3块，共少读`3×4096×2=24576`字节（24KiB），权重读取减少16.67%。等待halt窗口少20042周期，由225219降至205177，周期减少8.90%，对应同频下约1.098倍速度。输入、计算及输出阶段周期相同；差异主要出现在权重阶段，符合预期。

**上述只是在同一32KiB DTCM下的软件驻留策略收益，不是DTCM扩容收益。** 跨容量对照见下节。固定输入优先顺序不代表最优调度；改为权重优先或缓存多个输入可能改善小DTCM表现。

## 128KiB、同12权重块、外部附加读等待0：PASS

用户回传cocotb 1/1 PASS、`[TCM_WORKSET_VERIFIED]`及`[TCM_WORKSET_PASS]`。Ubuntu结果目录为`/home/lqq/coral_tcm_capacity_8e4_v1/workset_d128_t12_r0.xbIwT1`。两策略各3次重复稳定；每次9216个输出元素，共55296个输出检查。ELF和向量SHA与32KiB摘要完全一致，ITCM仍为8KiB、同一周期RAM模型和相同延迟假设。

128KiB共有28个4KiB权重槽；prefix模式使用12槽、驻留全部48KiB权重，首轮读取后两轮不再读取权重。

| 指标 | stream | prefix_cache |
| --- | ---: | ---: |
| 外部权重读取字节 | 147456 | 49152 |
| 外部输入读取/输出写入字节 | 12288 / 36864 | 12288 / 36864 |
| AXI读拍/请求/完成事务数 | 9984 / 9984 / 9984 | 3840 / 3840 / 3840 |
| AXI完成读字节 | 159744 | 61440 |
| AXI写拍/请求/完成事务数 | 2304 / 2304 / 2304 | 2304 / 2304 / 2304 |
| AXI请求输出字节/有效写字节 | 36864 / 36864 | 36864 / 36864 |
| 输入搬运CSR周期 | 10002 | 10002 |
| 权重阶段CSR周期 | 120384 | 40296 |
| 计算及读出CSR周期 | 60336 | 60336 |
| 输出搬运CSR周期 | 32148 | 32148 |
| 内核CSR总周期 | 224975 | 144782 |
| 第0/1/2轮CSR周期 | 74978 / 74978 / 74978 | 75015 / 34863 / 34863 |
| fixture等待halt周期 | 225219 | 145026 |

软件字节计数与AXI实测字节均与计划一致。128KiB内部的stream与prefix对照少80193个等待halt周期，减少35.61%，约1.553倍；这是同容量策略收益，不能误称为32→128KiB扩容收益。

## 首次跨容量结果：32KiB与128KiB

| DTCM | stream周期 | prefix周期 | prefix权重读字节 | 驻留权重块 |
| --- | ---: | ---: | ---: | ---: |
| 32KiB | 225219 | 205177 | 122880 | 3 |
| 128KiB | 225219 | 145026 | 49152 | 12 |

按同一prefix策略比较，等待halt窗口减少60151周期（29.32%），同频约1.415倍；权重读取减少73728字节（72KiB，60%）。两档stream对照的全部周期和搬运计数相同；prefix的输入、计算及输出阶段周期也相同，差异主要来自额外保留9个权重块后，每块在后两轮都省去一次4096字节读取。该结果支持：**在这个固定调度与外部代理条件下，扩容允许更多权重驻留，从而缩短所测执行窗口**，不是提高阵列本身的计算速度。

两份完整test.log已由用户在Ubuntu执行跨容量比较器并通过，回传32/128KiB两条`[TCM_WORKSET_COMPARE]`，周期比为1和1.41476。比较器校验同ELF、符号/加载段、向量、延迟、三次重复、算术完成标记和搬运计数；Windows仍未直接取得完整日志。尚不能推导真实模型、真实SoC/DDR或物理时序结论，也不能证明需要2/4MiB。本工作集权重仅48KiB，128KiB已能全部驻留，继续只测更大容量不足以定位2/4MiB的价值。后续应使用跨更大容量阈值的工作集，同时评估备选调度和外部延迟敏感性。

### Ubuntu：只读复核两份完整日志，不重跑仿真

```bash
(
set -eo pipefail
cd "$HOME/桌面/Coral_matrix"
conda run -n coral-matrix python -B verification/google_tcm_capacity/prepare_workset.py compare \
  --logs \
  "$HOME/coral_tcm_capacity_8e4_v1/workset_d32_t12_r0.QV8Sn5/test.log" \
  "$HOME/coral_tcm_capacity_8e4_v1/workset_d128_t12_r0.xbIwT1/test.log"
)
```

上述命令已在Ubuntu通过；两条`[TCM_WORKSET_COMPARE]`分别报告32KiB的205177周期/122880权重字节、128KiB的145026周期/49152权重字节，两档stream均225219周期。

## 后补1MiB、同T12、外部附加读等待0：Verilator PASS

用户回传完整终端摘要：cocotb 1/1 PASS、两条严格汇总、`[TCM_WORKSET_VERIFIED]`及`[TCM_WORKSET_PASS]`。目录：`/home/lqq/coral_tcm_capacity_8e4_v1/workset_d1024_t12_r0.XMBL3O`。单NPU、ITCM8KiB、M48/N192/K256、T12，与32/128KiB相同ELF SHA及向量SHA。两策略各3次重复，每次9216元素，共55296个输出检查。Windows侧依据回传摘要整理，未直接读取原始test.log，也尚未收到三容量完整日志的联合比较器结果。

| 指标 | stream | prefix_cache |
| --- | ---: | ---: |
| DTCM总槽/使用槽/驻留块 | 252 / 1 / 0 | 252 / 12 / 12 |
| 外部权重读取字节 | 147456 | 49152 |
| 外部输入读取/输出写入字节 | 12288 / 36864 | 12288 / 36864 |
| AXI读拍/请求/完成事务数 | 9984 / 9984 / 9984 | 3840 / 3840 / 3840 |
| AXI完成读字节 | 159744 | 61440 |
| AXI写拍/请求/完成事务数 | 2304 / 2304 / 2304 | 2304 / 2304 / 2304 |
| 输入搬运CSR周期 | 10002 | 10002 |
| 权重阶段CSR周期 | 120384 | 40296 |
| 计算及读出CSR周期 | 60336 | 60336 |
| 输出搬运CSR周期 | 32148 | 32148 |
| 内核CSR总周期 | 224975 | 144782 |
| 第0/1/2轮CSR周期 | 74978 / 74978 / 74978 | 75015 / 34863 / 34863 |
| fixture等待halt周期 | 225222 | 145029 |

同容量stream/prefix周期比1.552945，少读取98304字节权重。相较128KiB，两个策略的内部CSR总周期、各阶段周期、轮次周期和AXI流量均一致；等待halt窗口都多3周期，窗口与CSR总周期差值从244变为247。只确认差异位于所测内部CSR窗口之外，不推断具体原因，也不把它作为阵列变慢或SRAM频率变化的证据。这个48KiB权重集在128KiB已能全部驻留，因此该负载没有支持1MiB额外收益的证据。

Bazel报告测试`PASSED in 292.4s`，test命令elapsed299.707秒；此前仅RTL/固件构建30.119秒。这些是主机软件墙钟数据，不是NPU周期或纯RTL吞吐率。

### 同配置VCS交叉验证：正式验收PASS

服务器VCS Q-2020.03-SP2-7使用同一RTL/ELF及原fixture/工作集，T12/等待0两策略各3次。起初SGR颜色复位码阻断JSON汇总，之后包外验收器又出现ELF段元组/列表表示误比较；均已修正工具，未修改RTL、固件、原日志或重跑原仿真。用户最终回传TCM_VCS_ACCEPT_PASS及两条完整汇总，所有汇总字段与上述Verilator结果相同：stream225222周期、prefix145029周期，CSR/轮次/AXI计数、ELF与向量SHA全部一致。

原运行目录：`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_runtime/runs/t12_r0.6xf7vakp`；修正版包外入口：`/home2/lqq/coral_vcs_tools/ansi_fix_v2.bzKDlm/vcs_workset.py`（760bda8）。验收严格检查原始进程退出码/超时状态、命令、模型/包/环境、XML和六条记录，并新建result.json；simulation_rerun=false、raw_files_unchanged=true。

VCS原流程墙钟1185.423秒，cocotb testcase时间1178.2477581501007秒，编译另计60.523秒。它们与Ubuntu/Verilator的Bazel测试292.4秒是不同机器、略有不同统计边界的数据，不能完全归因于仿真器；但目前没有换VCS加速的证据。建议大工作集主线回Ubuntu/Verilator，保留固定VCS模型用于交叉验证。1MiB小工作集PASS不代表2/4MiB VCS通过，也不代表T384/T768已通过。

## MiB级权重跨容量阈值：初始计划及首次INCOMPLETE（后续完整PASS见末节）

仍使用同一个workset ELF、ITCM8KiB、固定输入优先顺序、三轮输入及两策略各3次重复；先固定外部附加读等待0。只改变DTCM容量和选定权重块数；每一组内部块数相同，不跨组比较加速比。

| 工作集 | DTCM | prefix驻留块 | 预测prefix权重读取字节 |
| --- | ---: | ---: | ---: |
| T384，权重1.5MiB | 1MiB | 251 / 384 | 2662400 |
| T384，权重1.5MiB | 2MiB | 384 / 384 | 1572864 |
| T768，权重3MiB | 2MiB | 507 / 768 | 5283840 |
| T768，权重3MiB | 4MiB | 768 / 768 | 3145728 |

上表是最初制定的静态计划：T384后来已经完整实测PASS，T768仍只有计划，不预报其PASS或周期。保留16KiB软件区，装不下全部权重时另保留一槽流式周转，因此驻留块数不是容量直接除以4KiB。所有输入/权重/输出仍在既定16MiB外部代理范围内，权重池不越DTCM边界。

进入本轮前，新增MiB级阈值/外部地址边界检查，以及T384/T768中跨第256块及末块的独立Python整数点积校验，本地完整回归58项通过、Shell语法通过。未改变RTL、RISC-V程序或安装工具指纹；这些静态/合成检查不代表MiB级实际RTL已PASS。

先只运行`bash verification/google_tcm_capacity/run_workset.sh 1024 384 0`，通过后才以`2048 384 0`完成同组配对；T384的MAC和输出元素数均为T12的32倍，墙钟时间不能按小用例保证。先记录这档耗时和峰值资源表现，再决定T768测试安排，不并行启动多档仿真。2/4MiB的物理宏时序、面积、功耗和真实SoC配置仍不由本实验证明。

### 2026-10-17收到的首次1MiB/T384运行：INCOMPLETE

用户回传真实日志包含stream的repeat=0/1两条PASS，每次294912个输出元素均检查通过；两次计数和周期一致。没有repeat=2、prefix记录或最终检查完成标记，Bazel总体TIMEOUT，不能记录为该档PASS或拿去作正式跨容量比较。

| 已完成的两次stream共同指标 | 值 |
| --- | ---: |
| fixture等待halt周期 | 6885516 |
| 内核CSR总周期 | 6885263 |
| 输入/权重/计算及读出/输出CSR周期 | 10002 / 3852288 / 1930752 / 1028736 |
| 外部输入/权重/输出字节 | 12288 / 4718592 / 1179648 |
| AXI读请求/完成事务 | 295680 / 295680 |
| AXI完成读字节 | 4730880 |
| AXI写请求/完成事务 | 73728 / 73728 |
| 每次检查输出元素 | 294912 |

ELF仍为`a8aa2d6feaefd56a5901f8bcca4f8f6bbf5394932add092243aff8f5eb497192`；T384输入+golden SHA为`e32a9e3d4b09c5dae8706a34fbc35f061b60d78d146e49861c31f728ee08fe0d`。两条记录分别在8609006.25ns、17217993.75ns仿真时间输出；这不是实际墙钟耗时。

Bazel报告`TIMEOUT in 3600.1s`、总elapsed3793.264秒；外层`time`报告real63m52.923s、user1.905s、sys3.265s。后两项不能当作整个持久化Bazel服务器/仿真进程树的CPU或利用率数据；日志也没有提供峰值RSS。结束标记为2026-10-16 17:16:17 UTC，即香港时间2026-10-17 01:16:17。用户没有给出该次独立运行目录后缀，不猜测路径。

此次由Bazel一小时墙钟上限终止，不是已观察到的算术失败，也不能据此排除未执行部分潜在问题。修复只在运行器显式传`--test_timeout=21600`（6小时保护上限，非耗时预测），并改为失败时也保存原始test.log、时间和退出码。旧目录与缓存不删除，RTL/固件/安装工具指纹/六次运行及所有判据不变；实际仿真仍需重跑完整流程。

## 2026-10-18：Ubuntu的1/2MiB、T384完整运行与配对PASS

首次夜间VM任务又曾因宿主Windows自动关机重启而中断；该残缺日志仍不算PASS。新队列`/home/lqq/coral_tcm_capacity_8e4_v1/overnight_vm.Qy9tDJ`从12:59:01开始，先1MiB、再2MiB，不并行。实际运行目录：

```text
/home/lqq/coral_tcm_capacity_8e4_v1/workset_d1024_t384_r0.AMFGqg
/home/lqq/coral_tcm_capacity_8e4_v1/workset_d2048_t384_r0.xymg0S
```

1MiB在14:51:40完整通过；2MiB及比较队列17:20:45输出ALL_PASS。共同官方/团队补丁、ITCM8KiB、ELF和T384向量SHA与初始计划相同，固定输入优先、read_delay_cycles=0。每策略3次，完整一档6次；每次294912个输出元素、75497472个有用MAC，各重复计数稳定。

| 指标 | 1MiB stream | 1MiB prefix_cache | 2MiB stream | 2MiB prefix_cache |
| --- | ---: | ---: | ---: | ---: |
| pool_slots | 252 | 252 | 508 | 508 |
| resident_tiles | 0 | 251 | 0 | 384 |
| used_slots | 1 | 252 | 1 | 384 |
| wait_for_halt_cycles | 6885516 | 5208090 | 6885520 | 4319251 |
| ws_total_cycles | 6885263 | 5207833 | 6885263 | 4318994 |
| ws_input_cycles | 10002 | 10002 | 10002 | 10002 |
| ws_weight_cycles | 3852288 | 2177114 | 3852288 | 1289472 |
| ws_compute_cycles | 1930752 | 1930752 | 1930752 | 1930752 |
| ws_output_cycles | 1028736 | 1028736 | 1028736 | 1028736 |
| round_cycles[0] | 2295074 | 2295828 | 2295074 | 2296227 |
| round_cycles[1/2]各 | 2295074 | 1455982 | 2295074 | 1011363 |
| 外部输入读取字节 | 12288 | 12288 | 12288 | 12288 |
| 外部权重读取字节 | 4718592 | 2662400 | 4718592 | 1572864 |
| 输出写入字节 | 1179648 | 1179648 | 1179648 | 1179648 |
| AXI读请求/完成/拍数（各） | 295680 | 167168 | 295680 | 99072 |
| AXI完成读字节 | 4730880 | 2674688 | 4730880 | 1585152 |
| AXI写请求/完成/拍数（各） | 73728 | 73728 | 73728 | 73728 |

比较器两条`[TCM_WORKSET_COMPARE]`已回传：第一容量1024，prefix周期5208090；第二容量2048，prefix4319251，周期比1.205785。

- **容量收益**：同prefix策略1→2MiB，少888839周期，即17.0665%；权重少1089536字节，即40.9231%。输入、计算及输出阶段相同，主要差异在权重阶段。
- **热轮而非整次**：后两轮每轮少444619周期，即30.5374%，不能把这个比例当含首轮冷加载的总收益。
- **同容量策略对照**：1MiB stream/prefix少24.36%，2MiB stream/prefix少37.27%；这不是跨容量的17.07%。
- **保留小差异**：2MiB stream等待窗口比1MiB多4周期，内部CSR总周期/阶段及AXI全部相同。只确认是窗口外差异，不归因物理RAM速度、不扣减计数。

结论只覆盖该固定调度、原CPU向量搬运/一周期行为RAM/外部代理条件，不证明真实模型最优，更不证明4MiB必要。2MiB在T384已能全驻留，继续只增加容量跑T384不能替代T768的2/4MiB阈值比较。

### 主机墙钟与NPU周期分开记录

| 运行 | Bazel test时间 | command elapsed | 备注 |
| --- | ---: | ---: | --- |
| VM 1MiB/T384 | 6736.5秒 | 6739.349秒 | 约1h52m，完整PASS |
| VM 2MiB/T384 | 8789.0秒 | 8940.854秒 | 约2h26m，含不同新模型动作 |

2MiB的NPU执行更短，整项仿真墙钟却长约30.47%；大模型、主机和测试平台开销与NPU性能不是同一指标。Verilator转换报告62.048秒、1856.539MB内存、146份C++只是转换阶段，不是本测试仿真时间/峰值仿真RSS。

## 2026-10-18：服务器VCS1MiB/T384完整PASS

目录`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_runtime/runs/t384_r0.pyg9qm5e`。用户回传6条完整原始JSON、完整工作集CHECK、cocotb1/1 PASS、`[TCM_VCS_RUN_PASS]`和`[OVERNIGHT_ALL_PASS]`。两策略的等待周期/CSR/轮次/AXI/ELF及向量与上述Ubuntu1MiB摘要一致。

流程墙钟37619.46秒，cocotb37605.01秒，仿真逻辑时间45608321.25ns；02:21启动，12:47:53仿真结束、12:48:02外层ALL_PASS。约10h27m不是NPU实际执行时间。与VM1MiB Bazel test观察墙钟比约5.58，机器/编译环境/计时边界不同，不作为纯引擎加速比。

## 2026-10-18：服务器VCS2MiB/T12完整PASS及T384待回传

2MiB已传输核对原归档SHA，包根`/home2/lqq/Desktop/coral_tcm_vcs_packages/d2048_499a7c31/coral_tcm_vcs_d2048`。VCS编译54.893秒；T12目录为包同级`coral_tcm_vcs_d2048_runtime/runs/t12_r0.e0u9djj4`，流程1187.676秒，输出RUN_PASS及PILOT_ALL_PASS。

| 指标 | stream | prefix_cache |
| --- | ---: | ---: |
| wait_for_halt_cycles | 225226 | 145033 |
| ws_total_cycles | 224975 | 144782 |
| ws_weight_cycles | 120384 | 40296 |
| 权重外读字节 | 147456 | 49152 |
| 驻留权重块 | 0 | 12 |
| pool_slots | 508 | 508 |
| 三轮周期 | 74978 / 74978 / 74978 | 75015 / 34863 / 34863 |

全部输入/计算/输出阶段、AXI及数据身份与1MiB T12对应结果相同，等待窗口多4周期，原因未定位。每策略3次、每次9216输出，不能把小测试通过当T384已经通过。

2MiB/T384的历史队列为`/home2/lqq/coral_vcs_tools/overnight_vcs.TdW8Yk`，10月18日13:28:53启动；截至2026-10-19整理未收到最终日志，不推断现在是否仍在跑。先查原队列console及实际run目录再更新，不新建重复任务覆盖结果。

## 2026-10-19：服务器独立Verilator进展与仍待完成项目

Conda环境在glibc2.17上检查PASS，1MiB模型编译434.214秒PASS。首次T12位于`.../coral_tcm_vcs_d1024_svaext_v1_verilator_runtime/runs/t12_r0.zl1315rn`，因入口误置WAVES/GUI字符串0触发`--trace`、模型未编跟踪而exit255，1.777秒、未超时。不是完整RTL测试失败，也没有可接受的速度结果。

`c0b4b76`修正子进程环境并严格只读复用原模型，25项本地测试通过；当时实际运行未回传。后来用户分别提供T12和T384完整通过结果，按顺序记录在下面，不用新PASS覆盖早先失败。

剩余：VCS2MiB/T384最终证据；Server Verilator2/4MiB各自T12；T768的2/4MiB；延迟8；真实模型/备选调度/SoC外存条件；真实SRAM宏/200MHz/PPA。4MiB只有几何/小控制PASS及导出包，不已有T768收益。ITCM暂停，所有上述DTCM结果仍ITCM8KiB。

## 2026-10-19后续回传：Server Verilator1MiB/T12完整PASS且VCS参考EXACT

- 原模型`e6ab26657e58.xbhdmzuj`只读复用，BUILD_REUSED/RUNTIME_FIX均已回传；未重新编译、未更改包或构建记录。
- 入口`/home2/lqq/coral_vcs_tools/verilator_trace_fix.S7nNd7/verilator_workset.py`，同目录`console.log`。
- 结果：`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_verilator_runtime/runs/t12_r0.fmvgge7f`。
- ITCM8KiB、DTCM1MiB、T12/read_delay0，仍同ELF/T12向量身份，每策略3次、每次9216输出，合计55296元素。
- stream等待225222、CSR总224975、权重阶段120384周期、权重外读147456字节；prefix分别145029、144782、40296周期、49152字节。轮次、输入/计算/输出计数及全部AXI拍/事务/字节与原VCS参考完全相同。
- 正式标记：`TCM_VERILATOR_REFERENCE_MATCH cycles_counters_axi_elf_vectors=EXACT`及`TCM_VERILATOR_RUN_PASS simulation_wall_seconds=429.077`。严格外层过程已经通过，不是仅凭两条摘要或模型编译推定。

同服务器正常VCS T12 wrapper1178.5秒；本次Verilator429.077秒，当前配置/负载观察速度比2.74659、墙钟少63.5913%。编译434.214秒另计且本次没有重编；不外推到T384/T768，也不混用Ubuntu292.4秒作为同机速度。

此T12之后的1MiB/T384也已通过，见下一节；[原复现命令](../HANDOFF-current.md#server-verilator-t384)保留为历史，不再是默认下一步。其他容量仍需自己的T12。

## 后续回传：Server Verilator1MiB/T384完整PASS及跨后端精确比对

控制台`/home2/lqq/coral_vcs_tools/verilator_t384.ydMKyr.log`；结果：

```text
/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_verilator_runtime/runs/t384_r0._66rc55e
```

原模型只读复用、包和构建记录不变，仍ITCM8KiB/DTCM1MiB、K256、M48、N6144、T384、额外读等待0。两策略各3次，每次294912输出、75497472有用MAC，总1769472输出检查。ELF/T384向量仍是本页已锁定的相同SHA。

| 指标 | stream | prefix_cache |
| --- | ---: | ---: |
| wait_for_halt_cycles | 6885516 | 5208090 |
| ws_total_cycles | 6885263 | 5207833 |
| ws_input_cycles | 10002 | 10002 |
| ws_weight_cycles | 3852288 | 2177114 |
| ws_compute_cycles | 1930752 | 1930752 |
| ws_output_cycles | 1028736 | 1028736 |
| 三轮周期 | 2295074 / 2295074 / 2295074 | 2295828 / 1455982 / 1455982 |
| 驻留块/使用槽 | 0 / 1 | 251 / 252 |
| 权重读取字节 | 4718592 | 2662400 |
| 输入读取/输出写字节 | 12288 / 1179648 | 12288 / 1179648 |
| AXI读拍/请求/完成（各） | 295680 | 167168 |
| AXI完成读字节 | 4730880 | 2674688 |
| AXI写拍/请求/完成（各） | 73728 | 73728 |

REFERENCE_MATCH=EXACT、RUN_PASS=13979.842秒均已回传，说明完整严格汇总和VCS1MiB T384相同，而不仅是两条输出摘要。编译未重跑，墙钟约3h53m；同机VCS原wrapper37619.46秒，当前观察快2.69098倍、墙钟少62.8388%。VM同档Bazel test6736.5秒，当前VM流程观察比服务器Verilator快2.07524倍；统计边界/主机/负载不同，不作为纯CPU/引擎基准。

此为后端一致性和主机成本验证，不新增扩容收益。下一步回到2/4MiB T768，先为已落地2MiB包完成独立Verilator编译/T12，4MiB仍先核对传输和自己的T12；[当前入口](../HANDOFF-current.md#server-verilator-2m-pilot)。VCS2MiB/T384最终回传仍缺，不推定当前进程状态。
