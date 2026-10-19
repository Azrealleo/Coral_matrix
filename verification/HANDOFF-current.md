# CoralNPU当前项目交接：单核TCM与预训练MobileNetV1

更新：2026-10-19。本次核对的工具基线：`c0b4b76098a88d5bace3c3fbdcef318c10e924f7`。本文是**当前接手入口**；完整历史见[全程工作记录](WORKLOG-and-handover.md)，10月4日8/32KiB综合交付另见[历史RTL交接](HANDOFF-simulated-rtl.md)。本文不修改原交付包，不声称已经执行新的Linux仿真。

## 最新任务覆盖说明：2026-10-19

**后续用户已将首个完整模型改为预训练“有人／无人”二分类MobileNetV1，1001类暂缓。** DTCM仍512KiB，ITCM评估后<=512KiB、优先Verilator，外部行为存储获准。当前入口是[二分类模型及VM固件资源步骤](google_person_detect/README.md)：固定原模型300568字节，31算子、最大特征36KiB；LiteRT2.1.4拒绝其14个一维bias量化轴3元数据，原模型未修改，不记主机参考PASS。下一步VM执行配套固定TFLM官方有人/无人原生C++测试，再只编译固件并审计ITCM/DTCM，暂不启动服务器RTL。新增15项本地工具/合成检查通过，不等于C++/固件或RTL通过。

以下1001类是本日稍早阶段记录，模型与golden保留，不是当前默认执行目标：

用户根据团队面积评估将本轮DTCM暂定为**512KiB**，接下来运行单NPU完整预训练MobileNetV1、1001分类；ITCM评估后选择、不得超过512KiB，优先Verilator。下文2/4MiB T768及固定ITCM8KiB是上一阶段的历史计划，不再自动启动；旧结果/包仍保留。

已下载官方V1 1.0/224量化候选并核对归档/模型SHA，静态确认UINT8、31算子、1001输出；最大特征张量784KiB、模型约4.078MiB，必须分块/外部存储，不能直接套用团队简化量化/固定小缓冲。用户已确认单核阶段先用外部AXI行为存储，实际SoC外存尚未确定。模型盘点12项检查通过，随后LiteRT BUILTIN_REF完整主机推理三组合成输入各两次、31节点输出逐位稳定，golden已生成；不是识别准确率或NPU PASS。交叉编译、ITCM测量和RTL均未完成，入口见[新任务与静态盘点](google_mobilenet_v1/README.md)。

同时已只读审查团队main `fa4b83e43bb0b1d58b18eb5f4c31d98ee4054123`：其固定诊断图已有真实矩阵算子和三轮软件优化，不能再用“官方原树无矩阵算子集成”概括团队版本；报告已阅读但本机未独立复跑团队SoC仿真。

## 1. 上一阶段状态与证据（新任务以前节为准）

- 团队已选官方CoralNPU，**不再继续Yangg152选型/修复**。旧源码和失败记录保留。
- 用户告知团队单NPU已经集成SoC并跑通测试，之后计划4核。本人当前只做**一个官方NPU**的TCM研究，不负责本轮四核性能或SoC接线验证。
- 当前ITCM固定8KiB；DTCM候选32/128/512KiB和1/2/4MiB。“2M/4M”指每个DTCM的MiB，不是Mbit。
- 六档DTCM几何和同ELF小计算控制均Ubuntu PASS。T384的1/2MiB在Ubuntu完整PASS并配对：同prefix策略2MiB少17.07%周期、少40.92%权重外读。
- 服务器VCS的1MiB/T384、1/2MiB T12均PASS；服务器2MiB/T384只有启动回传，须取最后日志，不能推定仍在运行或已通过。
- 服务器独立Verilator1MiB的T12/T384现均完整PASS且精确匹配VCS，429.077/13979.842秒，复用原模型；首次trace失败另存。**当前准备2/4MiB T768，先为2MiB建立自己的Verilator模型并验收T12**，4MiB服务器传输/模型/运行仍待确认。
- ITCM8～128KiB几何工具已写并本地自测，用户要求暂缓，实际RTL运行未回传；T768、读延迟8、完整模型、DC/200MHz、门仿都没有本轮完成结果。

先接手现有环境和证据，不重新clone上游最新版、不清Bazel cache、不删除失败目录、不修改包内manifest/hash、不停止其他人的仿真。

## 2. 文档导航与证据边界

| 要解决的事 | 入口 |
| --- | --- |
| 从项目开始的全部经过及最新补充 | [WORKLOG-and-handover.md](WORKLOG-and-handover.md)，第1、20～26节是当前状态 |
| 六档RAM抽样几何 | [STAGE1-results.md](google_tcm_capacity/STAGE1-results.md) |
| 同ELF小计算控制、六档日志比较 | [CONTROL-results.md](google_tcm_capacity/CONTROL-results.md) |
| 数据驻留设计、round/repeat、计数与AXI判据 | [WORKSET.md](google_tcm_capacity/WORKSET.md) |
| T12、T384实际结果、比例与原始路径 | [WORKSET-results.md](google_tcm_capacity/WORKSET-results.md) |
| 包导出、VCS环境/已知修复 | [VCS说明](google_tcm_vcs/README.md)、[导出及服务器记录](google_tcm_vcs/EXPORT-results.md) |
| 当前Verilator接口、模型复用、trace修复 | [Verilator说明](google_tcm_verilator/README.md) |
| 已暂停ITCM工具 | [ITCM说明](google_itcm_capacity/README.md) |
| 历史已仿真的8/32KiB RTL给综合组员 | [HANDOFF-simulated-rtl.md](HANDOFF-simulated-rtl.md)，不是新的MiB级实验包 |

PASS依据是用户回传的运行标记、完整摘要/部分原始日志及既有工具严格校验；本机复查了保存的用户附件，但没有直接访问两台Linux完整目录。Git中的文档不是原始完整测试报告，`git clone`不会带来Bazel缓存、Linux运行日志或所有RTL包。对未知部分写“未回传”，不等同失败，也不等同没有跑过。

## 3. 五种版本身份与三个仓库

| 身份 | 固定值/用途 |
| --- | --- |
| 个人工具仓库 | [Azrealleo/Coral_matrix](https://github.com/Azrealleo/Coral_matrix)，Windows改工具/记录，Linux执行 |
| 团队SoC仓库 | [cheshire-coral-soc/cheshire-coral-soc](https://github.com/cheshire-coral-soc/cheshire-coral-soc)，私有，当前实验只提取固定补丁 |
| 团队历史候选仓库 | [cheshire-coral-soc/coralnpu-official-candidate](https://github.com/cheshire-coral-soc/coralnpu-official-candidate)，历史官方候选来源，不自动等同SoC当前生成物 |
| 当前实验官方源 | `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a` |
| 团队补丁来源 | `95e06e872bff13b3625721a837b4b739a93bed6f` |
| 个人最新运行修复 | `c0b4b76098a88d5bace3c3fbdcef318c10e924f7` |
| 工作集ELF SHA256 | `a8aa2d6feaefd56a5901f8bcca4f8f6bbf5394932add092243aff8f5eb497192` |
| T12向量/golden SHA256 | `5f48b97cefb656ad1e4a96dc80a3f42804ed86d9c0553dade288d14519ebeb93` |
| T384向量/golden SHA256 | `e32a9e3d4b09c5dae8706a34fbc35f061b60d78d146e49861c31f728ee08fe0d` |

原始生成SV、ZIP、参数头和ELF的具体哈希保存在各运行/包manifest。上游commit、团队commit、工具commit、RTL哈希、ELF哈希不能互相替代。10月4日综合包来自旧`870993f7425066037f300c52237c283821e75cbb`，不可冒充新`8e4df09b`实验结果。

保留两个团队补丁：CSR地址排序和cvfpu sticky位宽源头修正；路径及SHA见`google_tcm_capacity/capacity_spec.py`和全程记录第21节。不能因测试通过就抛弃这两个已锁定的补丁，也不要改为读取团队main当前内容来“复现”旧结果。

## 4. RAM、地址图和工作集：交接必须讲清

### 4.1 逻辑规格与真实芯片边界

| 项目 | 当前容量实验 |
| --- | --- |
| NPU数量 | 1 |
| ITCM | 8KiB，1个512×128bit逻辑bank |
| DTCM | 32/128/512/1024/2048/4096KiB，4/16/64/128/256/512个8KiB逻辑bank |
| 每bank接口 | 1RW，128bit数据，16bit字节mask，读响应一周期 |
| 总线/向量 | XLEN32、AXI数据128bit、ID6bit、VLEN128 |
| 功能开关 | RVV/VME/FP/BF16开启；AXI外部取指开启，FetchL0关闭，verification=false |
| ITCM地址 | `0x00000000`起，8KiB |
| DTCM地址 | `0x01000000`起，按容量延伸，4MiB末端`0x013FFFFF` |
| CSR地址 | `0x02000000`起 |
| 外部fixture memory | `0x20000000`起，16MiB主机backing；不是片上DTCM或真实DDR |

这是**实验统一地址图**，不是10月4日8/32包的`DTCM=0x10000, CSR=0x30000`，也不是团队SoC最终映射。SoC容量扩展还涉及主CPU/NPU双向窗口、互连路由、linker、启动软件和访问白名单，不能只增加一个SRAM参数就认为集成已验证。

VCS和Verilator都保留官方原SRAM C++ DPI源码/存储语义；VCS独立DPI使用VCS头，Verilator直接编译原C++且用Verilator头。RAM复位不保证全零，数据必须装载。纯行为模型不能体现新增bank mux/fanout、真实宏读延迟、面积功耗和200MHz时序风险。最终宏的深宽/端口/CE-WE-mask极性、read-during-write、输出保持、延迟、PVT、MBIST/DFT均需团队确认。

### 4.2 T、round和repeat

每个B权重块256×16 INT8=4096字节，K始终256。T12/T384/T768分别12/384/768个权重块，即48KiB/1.5MiB/3MiB权重。3个A输入块各16×256，共12KiB；输出总形状M48、N=16T。

- 一次程序执行有3个输入round，内层遍历T个权重块。
- `stream`每个round重新从外部读所有权重。
- `prefix_cache`首轮冷加载；固定前缀驻留，后续round只读未驻留部分。
- 每策略独立复位重复3次，完整一档共6次，不是只跑3个round即通过。
- 每次完整检查T12的9216/T384的294912/T768的589824个输出元素，以及软件状态、CSR计数和真实AXI流量。

低DTCM16KiB留给软件/输入/输出/栈，余下4KiB一槽；装不下全权重时另留一槽流式周转。1MiB/T384驻留251块，2MiB/T384驻留全部384块；预计2MiB/T768驻留507块、4MiB驻留768块，**后者尚未实测**。

### 4.3 该实验能说明什么

完整等待halt窗口包含正式输入/权重搬运、矩阵计算、外部结果写回及计数窗口中的软件开销，不包含主机前门装载与读回检查。CSR的compute阶段也不是纯阵列延迟。

0附加读等待仍有AXI握手/代理开销，不是零延迟DDR。固定输入优先调度不是最优模型算法；调换循环、缓存多输入或DMA可能改变小容量表现。本轮证明的是指定策略的容量收益，不证明真实模型必须2/4MiB，也没有优化到理论上限。

## 5. 机器与环境：不要混用两个编译器设置

### 5.1 Windows维护端

`E:\Projects\矩阵二选一`，Git和`E:\python\python.exe`可用。主要改工具/文档、核对文件与本地测试，不实际跑本轮Linux RTL。Clash Verge端口7908；VMnet8主机地址192.168.58.1。Git里要保留LF、Linux执行位和链接模式；不能把工具wrapper的符号链接正文改掉。源码中`SRAM.scala`/`Sram.scala`的Windows大小写兼容仍要保留。

以下用户材料仍未跟踪/或原有未提交修改，本次不顺手提交、覆盖或清理：`.gitignore`、根目录10月4日原始RTL归档、`verification/README-official-sram.md`、`verification/rtl_handoff/`；`handoff_output/`及`.upstream-git/`是本机辅助材料，不随clone自动获得。

### 5.2 Ubuntu虚拟机

| 项目 | 值 |
| --- | --- |
| 个人工具clone | `/home/lqq/桌面/Coral_matrix` |
| Miniforge/环境 | `/home/lqq/miniforge3` / `coral-matrix` |
| 实验根/source | `/home/lqq/coral_tcm_capacity_8e4_v1` / 其`source/` |
| Bazel/缓存 | 实验根`bazel-9.1.0` / `bazel-user/` |
| OS/资源快照 | Ubuntu26.04、x86_64、glibc2.43，8vCPU、7.2GiB RAM、4GiB swap |
| 磁盘最后快照 | 99G总量、67G已用、28G可用；不是当前实时余量 |
| 代理 | `http://192.168.58.1:7908`，宿主Clash需允许LAN，地址以后可能变 |

现有Bazel模型使用Verilator5.052/cocotb2.0.0；Python/编译器以每份原始日志为准，不把Conda的clang版本自动当实际Bazel C++编译器证明。Ubuntu曾因宿主Windows自动关机重启，旧夜间任务中断；需要保持宿主和VM不休眠/关机。一个source/cache一次只跑一档，不和导出或ITCM安装并行。

### 5.3 EDA152服务器

| 项目 | 值 |
| --- | --- |
| 登录 | `lqq@172.27.127.152`，SSH22；RDP3390不是SSH |
| 用户 | UID1037，无管理员权限；共享服务器 |
| 根路径 | `/home2/lqq`与`/data/home2/lqq`为同一数据盘路径 |
| 系统 | CentOS7、x86_64、glibc2.17、GCC4.8.5 |
| VCS | `/opt/Synopsys/vcs/Q-2020.03-SP2-7/bin/vcs` |
| Conda根 | `/home2/lqq/coral_vcs_tools/miniforge3` |
| `coral-vcs` | Python3.11.9；Conda GCC/G++15.3；cocotb2.0.0、NumPy1.26.4、pyelftools0.32、find-libpython0.5.1 |
| `coral-verilator` | Python3.11.17；Verilator5.052；Conda GCC/G++15.3；make4.4.1；同四个Python依赖 |
| 资源快照 | Xeon Gold6240，144在线逻辑CPU，251GiB内存；不是单个仿真自动用满144核 |

原生Bazel8.6因glibc/CXXABI不兼容不能跑；没有通过替换系统库修复，也没用上Docker。服务器独立VCS/Verilator流程**不依赖Bazel、Java或RISC-V工具链**，从Ubuntu接收源码RTL包后本地编译。不要传Ubuntu可执行文件来绕ABI问题。

VCS特殊要求：先保存Conda Python和DPI G++绝对路径，再让系统`/usr/bin:/bin`在PATH前，VCS内部生成C用系统GCC4.8；DPI另用Conda C++17。Verilator相反，应保持Conda GCC/G++优先。两种设置都只在各自子终端，不改系统默认工具，不升级系统glibc。

## 6. 已进行/未进行矩阵及最重要的结果

| 场景 | Ubuntu Verilator | EDA152 VCS | EDA152独立Verilator |
| --- | --- | --- | --- |
| 六档32KiB～4MiB几何 | 全PASS | 非本轮运行项目 | 非本轮运行项目 |
| 六档同ELF小控制 | 全PASS、完整日志比较PASS | 未做这一suite | 未做这一suite |
| T12/32、128KiB | PASS、配对PASS | 未做 | 未做 |
| T12/1MiB | PASS | 首次验收、正常复测、profile均PASS | 修复后完整PASS、VCS精确参考匹配；429.077秒 |
| T12/2MiB | 本轮未收到该容量T12独立结果 | PASS | 未做 |
| T384/1MiB | 新完整运行PASS | PASS | 完整PASS、VCS参考EXACT；13979.842秒 |
| T384/2MiB | PASS、与1MiB比较PASS | 已启动，最终结果未回传 | 未做 |
| T768/2、4MiB | 未做 | 未做 | 未做 |
| 读延迟8周期配对 | 无完整结果 | 无完整结果 | 无完整结果 |
| ITCM容量几何 | 工具已写、暂停，实际未回传 | 未做 | 未做 |

### 6.1 T12：48KiB权重已在128KiB中装下

| 容量/环境 | stream等待周期 | prefix等待周期 | prefix权重外读字节 |
| --- | ---: | ---: | ---: |
| 32KiB Ubuntu | 225219 | 205177 | 122880 |
| 128KiB Ubuntu | 225219 | 145026 | 49152 |
| 1MiB Ubuntu/VCS | 225222 | 145029 | 49152 |
| 2MiB VCS | 225226 | 145033 | 49152 |

32→128KiB同prefix策略少29.32%周期，stream不变；128KiB以上已全部驻留，不证明还需要1/2/4MiB。内部CSR/轮次/AXI在128KiB、1/2MiB对应小负载下相同，等待halt窗口的3/4周期差异尚未定位，不能擅自扣掉或归因物理时序。

### 6.2 T384：1→2MiB可观测驻留收益

| 指标 | 1MiB prefix | 2MiB prefix |
| --- | ---: | ---: |
| 驻留权重块 | 251 | 384 |
| 等待halt周期 | 5208090 | 4319251 |
| 内部总CSR周期 | 5207833 | 4318994 |
| 权重阶段周期 | 2177114 | 1289472 |
| 输入/计算及读出/输出周期 | 10002 / 1930752 / 1028736 | 同左 |
| 首轮周期 | 2295828 | 2296227 |
| 后两轮各周期 | 1455982 | 1011363 |
| 外部权重读取字节 | 2662400 | 1572864 |

同prefix策略减少888839周期（17.0665%），同频周期比1.205785；权重外读减少1089536字节（40.9231%）。两档stream均读取4718592权重字节、内部总周期均6885263；等待halt分别6885516/6885520，多4周期差异不作物理解释。阶段数据和AXI事务详情在结果文档中。

服务器VCS1MiB/T384与Ubuntu同容量摘要一致；2MiB的大运行尚未回传，不把它计入已证明的跨后端一致性。上述不是MobileNet、四核SoC、真实DDR或200MHz达标结论。

## 7. 原始材料位置：接手必须另行拿到

### 7.1 Ubuntu已知PASS目录

以下相对于`/home/lqq/coral_tcm_capacity_8e4_v1/`；在新机器只能当查找线索，需检查真实存在性，不据目录名直接认定文件完整。

| 材料 | 子路径 |
| --- | --- |
| 六档几何/控制 | 完整目录列表见STAGE1-results及CONTROL-results |
| 六控制日志配对 | `control_compare.L0Pxte.log` |
| T12/32KiB | `workset_d32_t12_r0.QV8Sn5/test.log` |
| T12/128KiB | `workset_d128_t12_r0.xbIwT1/test.log` |
| T12/1MiB | `workset_d1024_t12_r0.XMBL3O/test.log` |
| T384/1MiB | `workset_d1024_t384_r0.AMFGqg/test.log` |
| T384/2MiB | `workset_d2048_t384_r0.xymg0S/test.log` |
| 完整T384队列 | `overnight_vm.Qy9tDJ/console.log`，10月18日17:20:45 ALL_PASS |

早期1MiB/T384一小时超时和首轮VM关机中断都保留为失败/不完整证据，不能重命名成上述新PASS。Bazel testlogs可能被覆盖，优先保存每次独立运行目录内副本。

### 7.2 不可变包与归档身份

| 容量 | Ubuntu归档完整路径 | SHA256 |
| --- | --- | --- |
| 1MiB | `/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d1024.yzU5z6/coral_tcm_vcs_d1024.tar.gz` | `0e969183cd48d3f7a9eaa062e31aded9d89b011fa8fcddee58febd69823b8cb8` |
| 2MiB | `/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d2048.T5HEGi/coral_tcm_vcs_d2048.tar.gz` | `499a7c31d97d06cb39ff8dcebe1ac2c6232605943d044af5d2eaa83ebe27d768` |
| 4MiB | `/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d4096.W2JmMH/coral_tcm_vcs_d4096.tar.gz` | `272a4e81560856660801d9c7dbcf28b40d8d290b3d1886395aa5f0c46d5269a5` |

服务器1MiB父目录：`/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/`；使用其中`coral_tcm_vcs_d1024_svaext_v1`。原始`coral_tcm_vcs_d1024`保留，只为旧VCS增加svaext选项的新副本，不改变RTL/固件。

服务器2MiB父目录：`/home2/lqq/Desktop/coral_tcm_vcs_packages/d2048_499a7c31/`；包`coral_tcm_vcs_d2048`已含修复。4MiB只确认Ubuntu导出，先查服务器是否已有再决定传输，不声称已落盘。

### 7.3 服务器运行目录和故障断点

定义两个便于查找的前缀（只是路径别名）：

```bash
tcm_p1=/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1
tcm_p2=/home2/lqq/Desktop/coral_tcm_vcs_packages/d2048_499a7c31/coral_tcm_vcs_d2048
```

| 材料 | 路径 |
| --- | --- |
| VCS1MiB成功构建 | `${tcm_p1}_runtime/builds/754330b47408.u824wjiz` |
| VCS1MiB初次T12及ANSI验收 | `${tcm_p1}_runtime/runs/t12_r0.6xf7vakp` |
| VCS1MiB正常T12参考 | `${tcm_p1}_runtime/runs/t12_r0.mraudje0/_test.log` |
| VCS1MiB profiling | `${tcm_p1}_runtime/runs/t12_r0.xluxpvy5/cocotb.pstat` |
| VCS1MiB T384 PASS | `${tcm_p1}_runtime/runs/t384_r0.pyg9qm5e` |
| VCS2MiB成功构建 | `${tcm_p2}_runtime/builds/5f9c6915a993.06j4djj0` |
| VCS2MiB T12 PASS | `${tcm_p2}_runtime/runs/t12_r0.e0u9djj4` |
| VCS2MiB T384任务日志 | `/home2/lqq/coral_vcs_tools/overnight_vcs.TdW8Yk/console.log` |
| 独立Verilator1MiB构建PASS | `${tcm_p1}_verilator_runtime/builds/e6ab26657e58.xbhdmzuj` |
| 独立Verilator首次T12失败 | `${tcm_p1}_verilator_runtime/runs/t12_r0.zl1315rn/_test.log`及`_test-status.json` |
| 独立Verilator修复后T12 PASS | `${tcm_p1}_verilator_runtime/runs/t12_r0.fmvgge7f`；429.077秒 |
| 独立Verilator T384 PASS | `${tcm_p1}_verilator_runtime/runs/t384_r0._66rc55e`；13979.842秒 |
| 独立Verilator T384控制台 | `/home2/lqq/coral_vcs_tools/verilator_t384.ydMKyr.log` |
| 本次已通过修复入口/控制台 | `/home2/lqq/coral_vcs_tools/verilator_trace_fix.S7nNd7/verilator_workset.py`及同目录`console.log` |
| 旧Verilator外部入口 | `/home2/lqq/coral_vcs_tools/verilator_runner.JdVpsd/verilator_workset.py`，包含trace问题，不再作为新运行入口 |

VCS和Verilator后端拥有独立状态树，不能互换模型二进制/成功指针。旧包内导出时`vcs_simulation=NOT_RUN`保持原样，新的运行证明在包外`result.json`、进程状态、XML和原始日志中。

## 8. 第一项只读检查：知道谁在跑、日志在哪

服务器执行，**不终止任何进程，不启动新仿真**：

```bash
date -Is
pgrep -a -u "$(id -u)" -x simv || true

tcm_job=/home2/lqq/coral_vcs_tools/overnight_vcs.TdW8Yk
if [ -f "$tcm_job/console.log" ]; then
    tail -n 30 "$tcm_job/console.log"
    grep -E '^\[(TCM_VCS_RUN_PASS|OVERNIGHT_ALL_PASS|OVERNIGHT_STOP|TCM_VCS_STOP|TCM_VCS_ADAPTER_STOP)\]' \
        "$tcm_job/console.log" || true
else
    echo '历史队列日志不存在：先确认路径和备份，不猜测最终状态。'
fi
```

不要用`ps -u UID -C simv`认定全是自己的任务，它的选择器并非交集。不要停止早先看到的PID；PID会复用，任务可能属于其他用户。需要查看Verilator时用自己的进程列表结合完整模型路径，不仅按顶层短名猜测。

`tail -f`只观察日志，Ctrl+C退出不会杀仿真。nohup只帮助终端断开后继续，不防宿主/VM重启，也不代表已经有checkpoint。历史job路径可能存在多个，检查目录和T/DTCM，不只选最新目录冒充目标任务。

<a id="current-verilator-pilot"></a>

## 9. 已完成的1MiB Verilator交叉验证与当前2MiB pilot入口

后续回传：`t12_r0.fmvgge7f`和`t384_r0._66rc55e`均完整PASS、VCS参考EXACT。前者429.077秒，后者13979.842秒。T384两策略各3次、共1769472输出检查，stream6885516周期、prefix5208090周期，所有CSR/轮次/AXI/ELF/向量与原VCS大日志相同。不要再重复1MiB；当前下一步见9.5，先2MiB自己的T12。

### 9.1 为什么不重新编译

模型构建已经PASS。旧入口在子进程设`WAVES="0"`和`GUI="0"`，cocotb2.0把非空字符串视为真，追加`--trace`，而模型按无波形编译，因此启动1.777秒即exit255、不是超时。修复只移除两个环境变量，继续显式False，不改RTL、SRAM、固件或测试判据。

修复脚本SHA256：`9031f22eadbfc75d308f2bcd67bde9b943b06822ccbbe8da702b821112273855`。它严格校验旧模型生产者SHA、完整环境/包身份、二进制及编译命令/visibility、成功状态，满足才只读复用；失败就停止，不能手改当前构建指针/哈希。

### 9.2 已通过T12的复现命令（不是当前默认下一步）

下面是已通过T12的原复现入口，前台运行；没有必要为了续跑T384重复执行。新接手机器若缺文件，下载需要反向代理，实际仿真不依赖代理。正式续跑使用9.4已经存在且核过SHA的修复入口。

```bash
(
set -eo pipefail
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-verilator
export CC="$(command -v gcc)"
export CXX="$(command -v g++)"
unset COCOTB_ENABLE_PROFILING WAVES GUI

if pgrep -a -u "$(id -u)" -x simv; then
    echo '自己的VCS仍在运行，稍后再测速；未停止任何进程。'
    exit 1
fi

tcm_package=/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1
tcm_reference="${tcm_package}_runtime/runs/t12_r0.mraudje0/_test.log"
test -f "$tcm_reference"
tcm_fix_dir=$(mktemp -d "$HOME/coral_vcs_tools/verilator_trace_fix.XXXXXX")
tcm_adapter="$tcm_fix_dir/verilator_workset.py"
curl -fsSL --retry 2 --connect-timeout 15 --max-time 180 \
    -x http://127.0.0.1:17908 -o "$tcm_adapter" \
    'https://raw.githubusercontent.com/Azrealleo/Coral_matrix/c0b4b76098a88d5bace3c3fbdcef318c10e924f7/verification/google_tcm_verilator/verilator_workset.py'
printf '%s  %s\n' \
    9031f22eadbfc75d308f2bcd67bde9b943b06822ccbbe8da702b821112273855 \
    "$tcm_adapter" | sha256sum -c -
echo "[VERILATOR_ADAPTER] $tcm_adapter"
echo "[VERILATOR_CONSOLE_LOG] $tcm_fix_dir/console.log"
"$CONDA_PREFIX/bin/python" -B "$tcm_adapter" --package "$tcm_package" run \
    --tiles 12 --delay 0 --timeout 21600 --reference-log "$tcm_reference" \
    2>&1 | tee "$tcm_fix_dir/console.log"
)
```

### 9.3 T12验收要求与失败保留

复现时应先有`TCM_VERILATOR_BUILD_REUSED`。最终必须同时出现：

```text
[TCM_VERILATOR_REFERENCE_MATCH] cycles_counters_axi_elf_vectors=EXACT
[TCM_VERILATOR_RUN_PASS] simulation_wall_seconds=...
```

它要完整6次输出/CSR/AXI/ELF/向量与同容量VCS参考精确相同，外层还要求退出0、未超时、XML无失败/跳过、模型及包未变。**不得为“跨后端有差异”擅自容忍/扣除周期或改golden。** 只有该模型自己的T12证据通过，才解锁T384等大工作集；其他容量还要自己的T12。

若报错，保留新`TCM_VERILATOR_RUN_DIRECTORY`，先回传其`_test.log`末120行和`_test-status.json`。若是模型/环境不匹配，不自动加build；先核对环境变量和旧`environment.json`，判断是否只是启动环境变化。不要再次把旧trace错误理解成RTL编译失败。

<a id="server-verilator-t384"></a>

### 9.4 已通过的1MiB/T384复现入口（保留，不再作为默认下一步）

此命令已实际通过，控制台`verilator_t384.ydMKyr.log`，运行`t384_r0._66rc55e`，模型未改、13979.842秒、VCS精确比对EXACT。下方仅保留复现方法，当前不需要重跑；24小时是保护上限，不是耗时预测，也不代表其他容量已合格。

```bash
(
set -eo pipefail
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-verilator
export CC="$(command -v gcc)"
export CXX="$(command -v g++)"
unset COCOTB_ENABLE_PROFILING WAVES GUI

if pgrep -a -u "$(id -u)" -x simv; then
    echo '自己的VCS仍在运行，稍后再测速；未停止任何进程。'
    exit 1
fi

tcm_adapter=/home2/lqq/coral_vcs_tools/verilator_trace_fix.S7nNd7/verilator_workset.py
printf '%s  %s\n' \
    9031f22eadbfc75d308f2bcd67bde9b943b06822ccbbe8da702b821112273855 \
    "$tcm_adapter" | sha256sum -c -
tcm_package=/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1
tcm_reference="${tcm_package}_runtime/runs/t384_r0.pyg9qm5e/_test.log"
test -f "$tcm_reference"
tcm_console=$(mktemp "$HOME/coral_vcs_tools/verilator_t384.XXXXXX.log")
echo "[VERILATOR_T384_CONSOLE_LOG] $tcm_console"
"$CONDA_PREFIX/bin/python" -B "$tcm_adapter" --package "$tcm_package" run \
    --tiles 384 --delay 0 --timeout 86400 --reference-log "$tcm_reference" \
    2>&1 | tee "$tcm_console"
)
```

完成需回传两条SUMMARY、REFERENCE_MATCH、RUN_PASS及新目录；T384的NPU周期若与既有VCS记录不同，必须排查，不只凭输出PASS接受速度排名。其他容量仍需自己的独立模型和T12，不能用本次1MiB前置证明解锁2/4MiB。

<a id="server-verilator-2m-pilot"></a>

### 9.5 当前下一步：服务器2MiB独立Verilator模型及T12

2MiB包已传输且VCS T12已PASS，可使用其已保存的`.../t12_r0.e0u9djj4/_test.log`作参考；不要求先补跑2MiB T384。以下会**新建2MiB模型并前台跑T12**，不会覆盖1MiB模型或改变两档不可变包。仍只用已通过的固定入口，暂不在同一命令中自动接T768或4MiB。

```bash
(
set -eo pipefail
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-verilator
export CC="$(command -v gcc)"
export CXX="$(command -v g++)"
unset COCOTB_ENABLE_PROFILING WAVES GUI

if pgrep -a -u "$(id -u)" -x simv; then
    echo '自己的VCS仍在运行，先确认任务状态；未停止任何进程。'
    exit 1
fi

tcm_adapter=/home2/lqq/coral_vcs_tools/verilator_trace_fix.S7nNd7/verilator_workset.py
printf '%s  %s\n' \
    9031f22eadbfc75d308f2bcd67bde9b943b06822ccbbe8da702b821112273855 \
    "$tcm_adapter" | sha256sum -c -
tcm_package=/home2/lqq/Desktop/coral_tcm_vcs_packages/d2048_499a7c31/coral_tcm_vcs_d2048
tcm_reference="${tcm_package}_runtime/runs/t12_r0.e0u9djj4/_test.log"
test -f "$tcm_reference"
tcm_console=$(mktemp "$HOME/coral_vcs_tools/verilator_d2048_pilot.XXXXXX.log")
echo "[VERILATOR_2M_CONSOLE_LOG] $tcm_console"
for tcm_phase in verify check build; do
    echo "[VERILATOR_2M_STAGE] $tcm_phase"
    "$CONDA_PREFIX/bin/python" -B "$tcm_adapter" --package "$tcm_package" \
        "$tcm_phase" --jobs 2 2>&1 | tee -a "$tcm_console"
done
"$CONDA_PREFIX/bin/python" -B "$tcm_adapter" --package "$tcm_package" run \
    --tiles 12 --delay 0 --timeout 21600 --reference-log "$tcm_reference" \
    2>&1 | tee -a "$tcm_console"
)
```

只有2MiB自己的REFERENCE_MATCH/RUN_PASS后再安排其T768；4MiB仍先核对传输、包、编译及自己的T12，再做同T768/延迟下的容量配对。不要把1MiB后端速度比较误当新的DTCM扩容收益，也不从T384全驻留结果推断4MiB价值。

## 10. 后续执行入口与运行安排

### 10.1 Ubuntu只读重查T384配对

不重跑RTL，可对已有完整日志重新执行比较器；所有路径以实际存在为准：

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
python -B verification/google_tcm_capacity/prepare_workset.py compare --logs \
    "$HOME/coral_tcm_capacity_8e4_v1/workset_d1024_t384_r0.AMFGqg/test.log" \
    "$HOME/coral_tcm_capacity_8e4_v1/workset_d2048_t384_r0.xymg0S/test.log"
)
```

若需新实验，正常入口为`bash verification/google_tcm_capacity/run_workset.sh <DTCM_KiB> <T> <delay>`；尖括号为说明，不原样执行。T384/T768应明确墙钟保护，例如在同一子终端设置`TCM_WORKSET_TEST_TIMEOUT_SECONDS=86400`；默认21600秒，既不是预计耗时，也不保证一定足够。一次一档，保留cache，安静进度输出；不在source任务进行中pull或安装新包。

### 10.2 服务器VCS已有模型的入口

保留原编译器隔离策略，包外ANSI安全入口的固定SHA是`e2668cd25e690177dea89087f4804b7fb4a426c8c9e8a2a2d19c9effb04999f0`。以下是已有1MiB入口的环境检查，不启动新仿真：

```bash
(
set -eo pipefail
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-vcs
tcm_python="$CONDA_PREFIX/bin/python"
export TCM_DPI_CXX="$(command -v g++)"
export PATH="/usr/bin:/bin:$PATH"
export CC=/bin/gcc CXX=/bin/g++
export TCM_VCS_CC=/bin/gcc TCM_VCS_CXX=/bin/g++
unset COCOTB_ENABLE_PROFILING
tcm_adapter=/home2/lqq/coral_vcs_tools/ansi_fix_v2.bzKDlm/vcs_workset.py
printf '%s  %s\n' \
    e2668cd25e690177dea89087f4804b7fb4a426c8c9e8a2a2d19c9effb04999f0 \
    "$tcm_adapter" | sha256sum -c -
tcm_package=/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1
"$tcm_python" -B "$tcm_adapter" --package "$tcm_package" check
)
```

真正新增运行用同样隔离环境下的`run --tiles ... --delay ... --timeout ...`；不得把参数中的不同容量包混用。没有必要为了本次文档整理再次复测已经通过的VCS T12。

### 10.3 网络恢复

Windows PowerShell保持反向SSH窗口运行；本地Clash7908须开启。服务器17908是代理端口，22是SSH，3390是远程桌面：

```powershell
ssh -N -T -p 22 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:17908:127.0.0.1:7908 lqq@172.27.127.152
```

端口占用报错先在服务器只读检查`ss -lntpe`、自身sshd，确认为自己的旧转发且不是当前会话才TERM对应PID。不要直接复制历史PID32796/189931，不killall sshd。代理能下载不等于远程桌面剪贴板已恢复，两者分开排查。

团队私有Git采用本人SSH key/ssh-agent及scoped GIT_SSH_COMMAND；不要把私钥/token放仓库、命令URL或交接文档。提示私钥passphrase时填创建该密钥时设置的口令；未知口令不能由本助手猜出，不能拿服务器密码替代。

## 11. 仿真速度结论与成本边界

| 场景 | 已测墙钟 |
| --- | ---: |
| VM Verilator 1MiB/T12 | Bazel test292.4秒 |
| Server VCS 1MiB/T12 | wrapper1178.5秒、cocotb1172.38秒 |
| VM Verilator 1MiB/T384 | Bazel test6736.5秒 |
| VM Verilator 2MiB/T384 | Bazel test8789.0秒 |
| Server VCS 1MiB/T384 | wrapper37619.46秒、cocotb37605.01秒 |
| Server VCS 2MiB/T12 | wrapper1187.676秒 |
| Server独立Verilator 1MiB/T12 | 429.077秒；编译434.214秒另计，复用模型 |
| Server独立Verilator 1MiB/T384 | 13979.842秒，约3h53m；复用同模型，VCS参考EXACT |

不同主机/编译器/边界下不把约5.58倍T384观察差异写成纯模拟器差异。VCS profiling的638658902次调用、433.861秒profile、百万到千万级VPI/时钟/观察器回调显示平台有成本，但累计时间嵌套不能相加，wrapper减profile不等于精确RTL时间；profile运行1403.893秒不作基线。

VCS debug/ACC可见性、Python逐周期时钟/AXI观察、CPU单线程和编译器都值得查，不等于已量化根因。保持原检查/时钟/SRAM，当前T12的服务器Verilator/VCS流程比为2.74659，T384为2.69098（Verilator墙钟少62.8388%）；不宣称纯内核或所有工作集比。相同1MiB/T384下VM的6736.5秒比服务器Verilator13979.842秒观察快2.07524倍，边界/主机/负载不同。T384/T12墙钟增长32.5812倍，但不能保证T768或新容量线性。

## 12. ITCM与完整模型：暂缓但不要丢失判断依据

ITCM工具新增时DTCM固定2MiB、ITCM8/16/32/64/128KiB。只测核停止状态的地址/掩码，不测取指执行，更没有性能阶段；14项本地测试不是RTL PASS。用户目前选择回DTCM，未执行新ITCM扫描。

现workset指令装载段1664字节，8KiB对于这份微基准足够，即使DTCM4MiB也不必等比扩ITCM。完整AI软件不同：固定`8e4df09b`的官方`run_full_mobilenet_v1_binary`示例BUILD设ITCM/DTCM各1MiB，但它依赖dummy模型，不是用户提出的1001分类模型，更不是1MiB最低需求证明。

官方默认linker把`.rodata`和初始化段也放ITCM，const模型数组若未显式放外部段可能占ITCM。应先拿实际tflite、算子实现/编译选项生成ELF/map，分别算代码/常量、栈、arena、外部段，再定容量。不能承诺所有模型8KiB够，也不能一概说1MiB无必要。

## 13. 下一步清单、交接材料与验收

### 13.1 待办优先级

1. 保存现有Linux完整证据，核对服务器2MiB/T384最终状态。
2. 保留已经通过的1MiB Server Verilator T12目录`.../runs/t12_r0.fmvgge7f`和修复入口，不重跑旧失败或伪造重编。
3. 保存已经通过的1MiB Server Verilator T384及VCS精确参考，不重复1MiB。按第9.5节先新建2MiB模型、用既有VCS2MiB T12参考验收；不把1MiB前置用于2/4MiB。
4. T768做2/4MiB配对；2MiB先自己的Verilator T12，4MiB先核对/传输原归档、编译和自己的T12。各前置通过后再安排大运行；记录磁盘/队列，不承诺一夜完成。
5. 再讨论延迟8、真实SoC外存带宽/仲裁、备选调度和实际模型；ITCM等用户另排期。
6. SRAM宏、200MHz、DC/STA/GLS、四NPU竞争交给团队明确配置和责任，再安排验证。当前没有网表/SDF/库返回证据。

### 13.2 交给下一位的实际材料

- 本个人工具仓库及本说明；记录实际`git rev-parse HEAD`、工作树和本次所用入口固定版本。
- Ubuntu实验`source/`中的三个阶段manifest及已应用补丁/参数，现有Bazel9.1.0/cache位置；不要只复制一个bazel-bin symlink。
- 已PASS和失败的独立运行目录：原始test日志、summary、命令、开始/结束时间、退出状态、参数头、RTL/ELF/hash、向量manifest；后台任务console和profiling文件分开列。
- 1/2/4MiB不可变源码归档及SHA文件；服务器实际升级副本、外部适配器、构建记录/模型二进制仅在兼容环境内使用，不跨系统当可移植物。
- 用户/团队批准的访问权限；私钥、token、license、PDK模型另按安全渠道，不提交公开Git。
- 10月4日docs_v2综合包若还需历史综合复核，应独立发送原包和hash，不混入本轮MiB目录、不改旧包内说明来“更新历史”。

### 13.3 接手验收

- [ ] 知道官方已选定，fork工作只保留历史。
- [ ] 知道本轮是一个NPU、ITCM8KiB、2/4MiB指DTCM，实验地址不等于SoC地址。
- [ ] 区分两个上游基线、五种版本身份、VCS与Verilator的编译器/状态目录。
- [ ] 找到并备份Ubuntu1/2MiB T384完整日志及比较器结果，知道17.07%结论的固定调度边界。
- [ ] 查明VCS2MiB T384当前真实状态；不把启动输出、过时PID或别人simv当自己的运行。
- [x] 1MiB Server Verilator T12已回传REFERENCE_MATCH/RUN_PASS，429.077秒；原始文件在服务器，接手仍需核对/备份。
- [x] Server Verilator1MiB/T384已回传REFERENCE_MATCH/RUN_PASS，13979.842秒，实际目录`t384_r0._66rc55e`。
- [ ] 2/4MiB各自Verilator T12及T768配对完成，目前没有这些后端/容量的完成结果。
- [ ] 知道4MiB仅导出、T768和延迟8未完成，ITCM已暂停，完整模型/200MHz/门仿均缺本轮证据。
- [ ] 没有清除旧结果、篡改manifest、放宽golden/重复/AXI/周期判据，且接手材料不含凭据或商业库。

以后每份结果同时记录：机器、源/工具版本、包及RTL/ELF身份、输入/golden、容量/T/延迟、完整次数/输出数、端点定义、原始日志/状态/墙钟、PASS/FAIL/INCOMPLETE及遗留问题。只更新仓库外层记录，不重写不可变包内导出声明。
