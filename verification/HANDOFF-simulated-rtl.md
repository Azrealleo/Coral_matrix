# CoralNPU 官方候选版：已跑仿真 RTL 综合交接说明

文档版本：v2，2026-10-04。交接对象：负责综合的组员；后续网表回传给 NPU 验证人员。

本次交付是完整 NPU 核 `VmeCoreMiniAxi`，保留此前仿真的生成配置。直接导出 Ubuntu 已有生成物，没有重新生成硬件，没有修改原始 RTL，也没有切换到 `prod/` 目标。此前关闭 AXI 外部取指的生产包不作为本次综合基线。

## 1. 接手后先做什么

1. 使用文档更新版压缩包，在独立工作目录解压，不与旧 `prod` 包混放。
2. 进入解压后的包根目录，执行本节校验命令。
3. 确认顶层是 `VmeCoreMiniAxi`，参数为外部取指开启、ITCM 8 KiB / DTCM 32 KiB。
4. 综合时读取 `dc_sources.tcl`，只分析 `compile_units/all.sv`，保留清单中的宏和包含路径。
5. 先明确 RAM 是通用数组实现还是工艺宏实现，再解释面积和时序报告。
6. 综合后按第 9 节回传网表、约束、库模型、报告及 RAM 处理记录。

```bash
# 在包根目录执行；不需要 Bazel、Chisel、Scala 或 Conda。
sha256sum -c SHA256SUMS
python3 verify_export.py --verify .
```

预期校验结果包含 `original_rtl_unchanged=true`、`enableAxiInstructionFetch=true`。Python 只依赖标准库。校验只核对交付文件、配置和已有日志，不会启动仿真或综合。

## 2. 交付基线、版本与验证证据

### 2.1 当前基线

| 项目 | 本次固定值 |
| --- | --- |
| 上游硬件来源 | `https://github.com/google-coral/coralnpu` 的官方候选源码 |
| 比较及验证仓库 | `https://github.com/Azrealleo/Coral_matrix` |
| 原始导出目录 | `coralnpu_sim_rtl_20261004_042513` |
| 导出时比较仓库 HEAD | `887181e512439b29e0d873eea2bb2ab2a4209808` |
| 顶层 | `VmeCoreMiniAxi` |
| 此前使用的 RTL 目标 | `//hdl/chisel/src/coralnpu:vme_core_mini_axi_cc_library_verilog` |
| 此前使用的仿真模型 | `//tests/cocotb:vme_core_mini_axi_model` |
| 生成文件原路径 | `coralnpu-google/bazel-bin/hdl/chisel/src/coralnpu/`，不是 `prod/` 子目录 |
| 导出方式 | 复制既有生成物，复制前后核对哈希，不调用 Bazel |

导出时 HEAD 是工作目录版本，不是旧缓存生成物生成时提交的独立证明。本次用原始生成文件哈希锁定交接身份；不要把候选仓库的源码提交、工具提交和生成文件哈希混为一个版本号。

以下是首次从 Ubuntu 接收的原始导出包身份。文档更新版只修改说明和相关元数据，所以其整包哈希会不同；原始 RTL 的三个哈希保持不变。

```text
原始 Ubuntu 压缩包：coralnpu_sim_rtl_20261004_042513.tar.gz
原始压缩包 SHA-256：0a7d737dc1c18d49781b9cdb246a4fe0bf11ffeb1db509ca8263bca255f271ed

original/VmeCoreMiniAxi.sv
56bdb782f4dff93b5ed3a2341ddf702ef8ec6ce66cbc819d245656e5bedb4c8c
original/VmeCoreMiniAxi.zip
995399afeedb86b85cab374523c744a28ab4de940d4d27deea605793db294b26
original/VVmeCoreMiniAxi_parameters.h
adcd2566a0492b27d9776ca83b9592f73f92aacac73da46cd02a2d88153a0bbd
```

以后如果重新导出其他缓存或重新生成 RTL，必须以新包的 `manifest.json`、`SHA256SUMS` 和实际参数为准，不能沿用上面这份快照的文件身份。

### 2.2 当前已确认与尚未执行的工作

| 项目 | 状态及范围 |
| --- | --- |
| Windows 接收完整性 | 原始整包 SHA-256 与 Ubuntu 输出一致；262 个包内文件检查通过 |
| RTL 原样交付 | 原始 `.sv`、`.zip`、参数头文件未改；解包的 249 个文件与原始 ZIP 字节一致 |
| 生成参数 | 参数头文件已核对，详见第 3 节 |
| 随包功能仿真证据 | `evidence/test_00.log` 中已有测试为 PASS |
| 本次重新跑功能仿真 | 未执行；保存既有结果，不补写新的 PASS |
| 本包的 DC 综合、STA、门级仿真 | 尚未执行，待组员综合和后续网表回传 |
| 200 MHz | 暂定目标，对应 5 ns；不是已确认可达到的频率 |

随包测试为 `vme_matrix_shared_weight_batch_vme_matrix_shared_weight_batch_test`。日志实际记录 **9 个逻辑用例、每个重复 3 次，共 27 次执行、48,384 个输出元素比较通过**；cocotb 汇总为 `TESTS=1 PASS=1 FAIL=0 SKIP=0`。其中 K 为 16/64/256，单次运行分别产生 1/4/16 个 16×16 输出 tile；官方程序每个 tile 从内存重新加载 B，不能写成权重始终驻留矩阵阵列。

日志可确认仿真使用 **Verilator 5.052、cocotb 2.0.0、Python 3.11.9**，不依赖 VCS。Windows 只做了接收与文件核对。原测试 fixture 默认周期 1.25 ns，可被配置覆盖；仿真中设定周期不等于硬件已达到对应频率。

这份日志不是完整 AI 模型、Cheshire SoC 或门级实现的验证报告。此前还有其他矩阵功能和性能测试，但未全部收进当前包；本说明不把未随包提供的日志算作当前附件。

## 3. 交付范围与实际生成配置

交付包括标量核、RVV、VME 矩阵扩展、浮点相关逻辑、ITCM/DTCM、AXI 和核控制/调试逻辑。它不是独立矩阵 PE，也不是整个 Cheshire SoC。不包含 SoC 互连、DDR 控制器、PAD、标准单元工艺库、SRAM 工艺库或完整 scan/DFT 插入结果。

| 参数 | 实际值 | 说明 |
| --- | --- | --- |
| `KP_enableAxiInstructionFetch` | `true` | 允许从 ITCM 之外经 AXI 取指，不是只能从 AXI 取指 |
| `KP_itcmSizeKBytes` | `8` | ITCM 8192 byte |
| `KP_dtcmSizeKBytes` | `32` | DTCM 32768 byte |
| `KP_enableRvv` / `KP_rvvVlen` | `true` / `128` | RVV 开启，向量宽 128 bit |
| `KP_enableVme` | `true` | 官方矩阵扩展开启 |
| `KP_enableFloat` | `true` | 浮点配置开启 |
| `KP_enableZfbfmin` / `KP_enableVectorBf16` | `true` / `true` | BF16 相关配置开启，不代表本包已回归所有 BF16 运算 |
| `KP_enableVerification` | `false` | 不是大容量 verification 变体；不等于没有功能测试或调试模块 |
| AXI 地址 / 数据 / ID | 32 / 128 / 6 bit | 以实际顶层端口为准，master 和 slave 均有这些位宽 |

参数依据为 `original/VVmeCoreMiniAxi_parameters.h`。不能仅凭顶层都叫 `VmeCoreMiniAxi` 就认为另一份 RTL 与本包相同；宏、生成参数和源文件哈希也要对应。

## 4. 包结构与综合入口

```text
HANDOFF.md                        本说明
manifest.json                     导出来源、参数、哈希与状态
SHA256SUMS                        包内逐文件校验值
verify_export.py                  独立完整性核对工具
LICENSE                           官方许可证
original/VmeCoreMiniAxi.sv         原始单文件生成物，存档/替代入口
original/VmeCoreMiniAxi.zip        原始逐模块生成物
original/VVmeCoreMiniAxi_parameters.h
rtl/                              原始 ZIP 的完整解包内容
compile_units/all.sv               只 include 原始文件的编译入口
filelist_synth.f                   综合文件清单
dc_sources.tcl                    DC 顶层、宏、包含目录、源文件变量
evidence/test_00.log               已有通过日志
evidence/tests_cocotb_BUILD.txt     导出时仿真模型定义
evidence/rtl_generation_BUILD.txt  导出时生成目标定义
```

包内没有 `run_dc.tcl`、SDC、SRAM 黑盒替换、工艺宏模型或已经综合的网表；不要照搬旧生产包中的文件名。所有交付 RTL 位于 `rtl/`，首跑推荐使用本包提供的编译包装和清单。

### 4.1 编译清单与宏

```text
+define+SYNTHESIS+USE_GENERIC+VLEN_128+TB_SUPPORT+ZVE32F_ON+ZVT_ON
+incdir+.
+incdir+rtl
compile_units/all.sv
```

`compile_units/all.sv` 保持官方 ZIP `filelist.f` 中的 package、全局头文件、宏、typedef、模块顺序；原始 RTL 字节没有被修改。`.svh`/`.h` 需要按顺序加载到同一编译作用域，不能只增加包含路径却遗漏这些头文件。

只选一种入口：**不要同时分析包装文件与它 include 的每个模块，也不要同时编译原始单文件和逐模块文件**，否则会重复定义。初次接手不要重新按文件名排序整个 RTL 清单。

| 宏 | 作用与限制 |
| --- | --- |
| `SYNTHESIS` | 选择可综合 RAM 数组分支，并屏蔽仿真初始化/断言等代码；不改变 AXI 外部取指生成参数 |
| `USE_GENERIC` | 保留官方通用实现选择，不表示已经绑定工艺 SRAM 或 ICG |
| `VLEN_128` | RVV 相关宽度配置，与已生成向量宽一致 |
| `TB_SUPPORT` | 官方 RVV 清单中的接口/类型配置，不能只因名字带 TB 就删除 |
| `ZVE32F_ON` / `ZVT_ON` | 与浮点向量/矩阵相关结构和接口一致；不要随意改变 |

ZIP 中保留了 `verification/` 资源。实际断言包装受 `ifndef SYNTHESIS` 保护；保留原文件不等于把验证模块综合进硬件。不要另行开启仿真随机初始化、验证宏或把 DPI C++ 文件交给 DC。

### 4.2 DC 最小接入方式

师兄沿用自己的工艺库和约束流程，在包根目录执行下列入口步骤。下列代码只说明文件接入，不是已经验证通过的完整综合脚本。

```tcl
# 先在自己的脚本中设置实际 target_library / link_library。
source dc_sources.tcl
set_app_var search_path [concat $handoff_include_dirs $search_path]
file mkdir work
define_design_lib WORK -path work

analyze -format sverilog -define $handoff_defines $handoff_sources
elaborate $handoff_top
current_design $handoff_top
link
check_design

# 团队暂定目标，只是约束起点。
create_clock -name npu_clk -period 5.000 [get_ports io_aclk]
set_case_analysis 0 [get_ports io_te]

# 在自己的流程中补全 I/O budget、门控时钟处理、库角及其他约束，
# 再执行综合并输出报告和网表。
```

`io_aclk` 内部经过 `RstSync` 和 `ClockGate`。通用 `ClockGate` 是低电平透明锁存使能加与门，相关 latch 是有意的门控结构，不应直接认定为意外锁存。若映射为工艺 ICG，需要记录对应库单元、test-enable 极性和时钟约束；不能无依据地把该模块删除、旁路或全局 false-path。

5 ns 主时钟并不构成完整时序约束。综合人员需检查内部门控时钟覆盖、未约束路径、I/O 延迟、复位路径处理和工艺角。不要据“工具成功退出”直接宣称 200 MHz 达标。

## 5. RAM 详细规格与综合处理

### 5.1 实际容量、组织与层级

| 存储器 | 容量 | 组织 | 每块接口 |
| --- | --- | --- | --- |
| ITCM | 8 KiB / 8192 byte | 1 × 512 深度 × 128 bit | 单端口 1RW |
| DTCM | 32 KiB / 32768 byte | 4 × 512 深度 × 128 bit，按地址深度分 bank | 每块单端口 1RW |
| TCM 合计 | **40 KiB / 327680 bit** | **5 块 512×128** | 不是双端口 RAM |

每块容量为 `512 × 128 / 8 = 8192 byte`。DTCM 四块不是四个独立并行访问端口，也不是统一的 512 bit 数据总线。核、AXI slave、调试接口经仲裁访问 TCM；多个请求来源不意味着需要多端口 SRAM 宏。

当前原始层级和 bank 基址如下。综合的 `uniquify`、扁平化或重命名可能改变路径，回传时请给出对应关系。

| 原始实例路径（相对顶层） | 用途 | 字节基址 | 参数 |
| --- | --- | --- | --- |
| `itcm.sram.sramModules_0` | ITCM | `0x00000000` | `NUM_ENTRIES=512` |
| `dtcm.sram.sramModules_0` | DTCM bank 0 | `0x00010000` | 同上 |
| `dtcm.sram.sramModules_1` | DTCM bank 1 | `0x00012000` | 同上 |
| `dtcm.sram.sramModules_2` | DTCM bank 2 | `0x00014000` | 同上 |
| `dtcm.sram.sramModules_3` | DTCM bank 3 | `0x00016000` | 同上 |

对应文件是 `rtl/TCM128.sv`、`rtl/TCM128_1.sv`、`rtl/SRAM_512x128.sv`、`rtl/SRAM_2048x128.sv`。`SRAM_2048x128` 是四个 512 深度 bank 的包装，不代表本包有一个 2048×128 工艺宏。

40 KiB 只统计 ITCM+DTCM，不包含标量/向量/矩阵寄存器、流水寄存器及其他缓冲；不能将它写成整个 NPU 的总存储量。

### 5.2 每块 `Sram` 接口与行为

| 信号或属性 | 实际规格 |
| --- | --- |
| `clock` | 上升沿采样访问；来自 TCM 时钟路径 |
| `enable` | 高有效请求使能 |
| `write` | 高有效写选择；单端口不能同时独立读写 |
| `addr` | 9 bit 字地址，0～511；不是字节地址 |
| `wdata` / `rdata` | 128 bit，每字 16 byte |
| `wmask` | 16 bit；每 bit 对应 1 byte，高有效写入 |
| byte lane | `wmask[i]` 控制 `wdata[8*i +: 8]` |
| 读响应协议 | 请求上升沿采样后按一周期读响应连接 |
| `rvalid` | `enable` 延迟一周期，写请求也会产生延迟有效；实际 bank 包装没有使用这个输出 |
| 复位 | `Sram` 没有清空阵列的 reset；不要假定 RAM 复位后全零 |
| ECC / parity | 此包装接口没有额外校验位或错误状态接口 |

通用数组分支在读请求时更新读地址，输出为该地址的数组内容。未读时不会更新这个地址；但写入同一个阵列地址可能改变输出，不能据此承诺宏输出在所有空闲/写入场景下都保持不变。宏替换还要核对 read-during-write 和未使能输出行为，不能仅比较深度、宽度就认为等价。

### 5.3 仿真 RAM、综合数组与工艺宏的区别

| 实现形式 | 当前角色 | 对综合及门仿的影响 |
| --- | --- | --- |
| 官方 DPI RAM 行为模型 | 已有 Verilator 仿真使用 | 支持后门加载，不是 SRAM 工艺宏；DPI 导入不能交给 DC 综合 |
| `Sram.v` 的 `SYNTHESIS` 数组分支 | 本包默认综合入口 | 能用于存储器推断；是否映射成实际宏由综合流程决定；若变成触发器/组合逻辑，PPA 不代表 SRAM 宏实现 |
| 接口空壳/黑盒 | 本包未提供或启用 | 如团队后来采用，只能先评估其他逻辑；没有功能模型不能做有效结果比较，未给宏库时面积/时序覆盖不完整 |
| 工艺 SRAM 宏及适配层 | 需要团队选择并提供 | 需实际时序/面积库与功能模型，匹配端口、mask、极性和响应延迟 |

**本包保留同一份 `Sram.v`，但综合宏选择的 RAM 分支与已有 DPI 仿真分支不同。** 这不等于换了一份 Chisel 配置，也不代表综合后的 RAM 实现已经通过功能验证。

如果首跑得到很大的寄存器面积，先查看 RAM 是否被实现为触发器，不要立即归因于矩阵阵列效率。当前包没有自动把数组绑定到团队的 SRAM 宏，也没有保证 DC 会自行完成这种绑定。

源码已有 `USE_TSMC12FFC`、`USE_GF12LPP`、`USE_GF22` 等适配分支，但工艺库并未随包提供，也未确认团队工艺。若采用宏，需记录宏名、每块深度/宽度、数量、byte-mask 到宏引脚的映射、CE/WE/BWE 极性、读延迟、PVT 角和供电引脚处理。低有效宏引脚通常需要反相适配；64 bit 宽宏可考虑两块组成 128 bit，但会改变物理宏数量，必须明确记录。

ITCM/DTCM 容量是生成配置，不是运行时可调寄存器。本次保持 8/32 KiB；若扩容，需重新生成并同步地址图、软件和验证，不应在本次原样交接过程中直接改深度参数。

## 6. SoC 接口、取指方式与地址图

### 6.1 顶层主要端口

实际端口声明在 `rtl/VmeCoreMiniAxi.sv` 的模块头中。主要端口组如下：

| 端口 | 相对 NPU 方向 | 集成说明 |
| --- | --- | --- |
| `io_aclk` | 输入 | 主时钟；内部存在时钟门控 |
| `io_aresetn` | 输入 | 外部低有效异步复位，内部同步释放 |
| `io_te` | 输入 | test-enable；功能运行固定 0，不是完整 scan 接口 |
| `io_boot_addr[31:0]` | 输入 | 复位退出时采样的启动 PC，须保持稳定 |
| `io_halted` / `io_fault` / `io_wfi` | 输出 | 核状态；不是 AXI 请求信号 |
| `io_irq` / `io_timer_irq` / `io_software_irq` | 输入 | 进入 NPU 的中断，不能当作通知主 CPU 的完成中断输出 |
| `io_axi_slave_*` | 从接口 | 主 CPU/其他 master 装载 TCM、读写核控制寄存器 |
| `io_axi_master_*` | 主接口 | NPU 主动访问外部指令、输入、权重和结果存储器 |
| `io_dm_*` | 请求/响应接口 | 调试访问；未使用时按协议 tie-off |

未使用调试时，`io_dm_req_valid=0`，请求 payload 固定为已知值，`io_dm_rsp_ready` 可置 1；未使用的中断输入置 0。不要将 AXI master 的 ready/response 随意全置 0，否则一旦程序访问外部内存就会停等。应连接真实互连或有握手和错误响应的存储器模型。

本包 AXI 是地址 32 bit、数据 128 bit、ID 6 bit，写 strobe 为 16 bit。接入 Cheshire 时需要实际连接/适配位宽、ID、地址路由、时钟复位和错误响应；本包没有完成这些 SoC 级接线。

### 6.2 开启外部取指的准确含义

| PC 地址 | 当前取指路径 |
| --- | --- |
| ITCM 范围内 | 直接读内部 ITCM，不经外部 AXI |
| ITCM 范围之外 | 通过 `IBus2Axi` 从 AXI master 发起读取，外部互连和存储器必须响应 |

因此既能将程序放在 ITCM，也能将程序放在 AXI 可访问的共享 SRAM/ROM/DDR。核按 PC 自动选择路径，不需要主 CPU 一条条推送指令。指令读取与外部数据读取共享 master 读通道，并经仲裁区分；实际外部存储延迟和竞争会影响性能。

关闭外部取指仅取消第二条取指路径，不关闭 AXI slave 装载或 master 数据访问。但本次不改变这个生成参数。

### 6.3 当前核内地址图

| 区域 | 字节地址范围 |
| --- | --- |
| ITCM | `0x00000000–0x00001FFF` |
| DTCM | `0x00010000–0x00017FFF` |
| 核控制 CSR 窗口 | `0x00030000–0x00030FFF` |

这是 NPU 当前核内地址图，不等同于 Cheshire 最终分配给 NPU 的 SoC 全局窗口。SoC 若做地址重映射，需要明确主 CPU 的访问地址与 NPU 看到的内部地址之间的对应关系。仿真 fixture 的外部内存示例基址是 `0x20000000`，不是本包为真实 DDR 固定的地址。

## 7. 复位、控制寄存器与启动流程

`RstSync` 当前复位释放延迟为 2 级，时钟使能释放延迟还包含 2 级；这是源码中的同步/门控结构，不是 RAM 复位。仿真及实际集成都应等待内部接口可用，并以握手成功为准，而不是只等待一个输入时钟边沿。

核控制寄存器的 reset 值为 `3`：bit0=核复位、bit1=核时钟门控。因此，**仅把 `io_aresetn` 拉高不会自动开始执行程序**。

| CSR 相对偏移 | 当前地址 | 字段与用途 |
| --- | --- | --- |
| `0x00` | `0x00030000` | bit0 核复位、bit1 门控；初值 3；写 0 解除复位和门控 |
| `0x04` | `0x00030004` | 启动 PC；初始从 `io_boot_addr` 捕获，可在启动前覆盖 |
| `0x08` | `0x00030008` | 状态，只读；bit0 halted，bit1 fault |

AXI 数据总线是 128 bit，CSR 寄存器是 32 bit。寄存器位于相应 byte lane，不能把任意 32 bit 值都放到 WDATA 低 32 bit：例如 PC 寄存器对应 `WDATA[63:32]`，读状态对应 `RDATA[95:64]`。适配/驱动需按地址放置数据、处理 `WSTRB`，并遵守实际 slave 支持的事务格式。

建议启动顺序：

1. 时钟连续运行；保持 `io_te=0`、未使用中断为 0、调试请求无效，连接好 AXI 外部响应路径。
2. 断言外部复位，稳定 `io_boot_addr`，再释放外部复位并等待同步/门控及接口初始化。
3. 核保持 reset/门控时，主 CPU 经 AXI slave 将程序写入 ITCM，或准备可访问的外部程序内存；初始化数据和结果区，检查写响应。
4. 若需要覆盖入口 PC，在 `0x30004` 写入口；最后向 `0x30000` 写 0 启动核。重启另一程序时先按控制协议停止/复位，再更新入口与数据。
5. 监视 `io_fault` 和状态寄存器，按照测试程序约定的 halted/完成状态判断结束；必须有超时。WFI 表示等待中断，不应自动当作计算成功。
6. 通过 AXI slave 或外部内存路径读回结果，按软件/golden 约定核对。

随包仿真日志显示测试程序曾通过 **DPI 后门**装入 ITCM/DTCM。这是仿真便利功能，不证明所有程序装载都经过顶层 AXI slave，也不是综合后网表的装载方式。后续门仿优先通过顶层 AXI 完成装载，避免依赖被综合优化掉的 RTL RAM 数组层级。

## 8. 综合前后需要记录什么

首跑不要求现在就确定所有 SoC 设计，但综合报告至少应能说明：使用哪份 RTL、什么宏、哪个工具/库角、RAM 如何处理、施加了哪些约束。

| 项目 | 请综合人员记录 |
| --- | --- |
| 输入身份 | 原始 ZIP/单文件哈希、采用的顶层和清单；不要仅写仓库 HEAD |
| 工具 | DC 版本、完整运行脚本及日志 |
| 库 | 标准单元 target/link 库、PVT/operating condition；有 SRAM/ICG 时单独列出 |
| RAM | 推断数组、触发器实现、黑盒还是实际宏；5 个逻辑 bank 的映射情况 |
| 时钟 | 5 ns 目标、内部门控时钟覆盖、I/O budget、复位及例外约束 |
| 检查 | 未解析模块、check_design、意外 latch、未约束路径、约束违例和警告处理 |
| 输出报告 | 层级面积、参考单元/RAM、setup/hold 时序、时钟与约束覆盖 |

若改变 RAM 包装、替换 ICG、插入 DFT、重定时或更改生成参数，需要回传变更说明。文档中“保持原样”只描述本次交付 RTL，不承诺后续综合/工艺适配不发生变化。

## 9. 网表回传与后续门仿交接

师兄综合完成后，请把下列内容作为同一版本回传；不是只发送一个网表文件。

| 回传项 | 用途或说明 |
| --- | --- |
| Verilog 网表及顶层名 | 完整模块/层级；注明端口有无变化与是否扁平化 |
| 综合脚本、日志、工具版本 | 复现库、宏、优化和约束设置 |
| 实际 SDC | 说明主时钟、门控时钟、I/O 和例外约束 |
| SDF（如已生成） | 注明是综合阶段还是布局布线阶段、所用角和时间单位；未生成就明确写无 |
| 标准单元、ICG 的 Verilog 仿真模型 | 与网表引用名称、引脚及库版本一致；内部按许可共享，不提交公开仓库 |
| SRAM 仿真模型及适配层 | 如果采用宏必须提供；黑盒输出不能用于有效功能比较 |
| RAM / ICG 映射记录 | 逻辑 bank 到实际实例/宏名的对应、极性、读延迟、mask 与电源脚处理 |
| 面积/时序/设计检查报告 | 说明 unresolved、blackbox、latch、未约束路径及剩余违例 |
| 变更记录与可选 DDC | 区分原样综合、宏适配、DFT/其他修改；DDC 有则一起回传 |

网表回传后再准备适用于网表的测试环境。先跑不带 SDF 的功能门仿，确认复位、顶层 AXI 装载、运行、完成状态和结果；之后再按可用模型/SDF 加时序。此处只给出交接顺序，本次未执行这些门仿。

不要直接复用依赖 `dut.core` 内部层级或 DPI RAM 后门的 cocotb 测试来宣称网表通过；综合后层级和 RAM 实现可能不同。没有模型、未正确装载程序、SDF 实例路径错误或未知值初始化问题时，应先区分测试环境问题与设计功能问题。

## 10. 重新导出方法与常见问题

已收到本次交接包的综合人员不需要执行导出。以下仅供维护者保留流程；不要为“更新说明”重新生成 RTL。

```bash
cd "$HOME/桌面/Coral_matrix"
python3 verification/export_simulated_google_rtl.py --repo coralnpu-google
```

默认收集之前通过的权重复用日志；如日志不在原位置，可明确指定另一个之前通过的 VME 整核日志：

```bash
python3 verification/export_simulated_google_rtl.py --repo coralnpu-google \
  --test-log bazel-testlogs/tests/cocotb/vme_test/vme_matrix_tk4_tile_vme_matrix_tk4_tile_test/test.log
```

日志相对路径以 `coralnpu-google` 为基准。生成文件缺失、参数不是外部取指开启的 8/32 配置、日志失败或核心目录存在已跟踪改动时，脚本停止，不清理缓存、不覆盖输出、不擅自重新 build。

| 现象 | 优先检查 |
| --- | --- |
| 重复定义模块 | 是否同时编译包装、逐模块、原始单文件；是否混入旧包 |
| 宏或 typedef 缺失 | 是否保留 `compile_units/all.sv` 的官方顺序和包含路径 |
| DC 遇到 DPI/仿真断言 | 是否忘了 `SYNTHESIS`；是否另行加入仿真源或宏 |
| 面积异常大 | RAM 是否被实现为触发器；不要把纯逻辑/黑盒面积写成包含 SRAM 的芯片面积 |
| 释放外部复位后不执行 | CSR reset/门控初值是 3，是否完成装载并写 0 启动 |
| 外部访问停等 | AXI master 是否接好响应模型；地址、ID、握手与错误响应是否正确 |
| 门仿程序或结果为 X | RAM/库模型是否缺失，是否装载、复位正确；不要默认 RAM 全零 |
| 准备调整容量或关闭外部取指 | 这是新的硬件配置，不属于本包文档更新，需要明确版本并重新验证 |

原始版权头与 `LICENSE` 保留；团队工艺库和模型的获取/共享按团队现有许可流程处理。
