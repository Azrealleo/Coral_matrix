# 官方 CoralNPU：已跑仿真配置的 RTL 交接

面向综合组员的详细交接说明见 [HANDOFF-simulated-rtl.md](HANDOFF-simulated-rtl.md)，包含本次基线、综合入口、RAM、SoC 接口、启动控制和网表回传清单。本文保留导出工具的简要使用方法。

本流程直接复制 Ubuntu 工作目录中已有的生成文件，不调用 Bazel，不重新生成硬件，不使用 `prod/` 目标。它替代此前关闭 AXI 外部取指的生产配置交接包；两包不能混用。

## 1. 在 Ubuntu 导出

从比较仓库根目录运行，Python 只需要标准库：

```bash
cd "$HOME/桌面/Coral_matrix"
python3 verification/export_simulated_google_rtl.py --repo coralnpu-google
```

默认收集之前已通过的权重复用测试日志：

```text
coralnpu-google/bazel-testlogs/tests/cocotb/vme_test/vme_matrix_shared_weight_batch_vme_matrix_shared_weight_batch_test/test.log
```

若这个日志不存在，可显式选择另一个之前通过的 VME 整核测试，例如：

```bash
python3 verification/export_simulated_google_rtl.py --repo coralnpu-google \
  --test-log bazel-testlogs/tests/cocotb/vme_test/vme_matrix_tk4_tile_vme_matrix_tk4_tile_test/test.log
```

相对日志路径以 `coralnpu-google` 为基准。脚本不会重新跑测试；必须找到已有 cocotb `PASS>0、FAIL=0` 的汇总。如果生成文件缺失、参数不符、已有日志失败或核心目录有已跟踪文件改动，脚本停止，不删除、不覆盖这些文件。

输出为用户主目录中的 `coralnpu_sim_rtl_<时间戳>/` 和同名 `.tar.gz`。把压缩包传回 Windows 即可；不把生成 RTL 提交进比较仓库，也不覆盖旧生产包。

## 2. 固定配置与来源

| 项目 | 本包 |
| --- | --- |
| 硬件来源 | `google-coral/coralnpu` 官方源码在比较仓库中的候选版本 |
| 顶层 | `VmeCoreMiniAxi`，完整 NPU 核，不是独立矩阵单元或整个 SoC |
| 此前使用的生成目标 | `//hdl/chisel/src/coralnpu:vme_core_mini_axi_cc_library_verilog` |
| 此前使用的仿真模型 | `//tests/cocotb:vme_core_mini_axi_model` |
| AXI 外部取指 | **开启**，`KP_enableAxiInstructionFetch=true` |
| ITCM / DTCM | 8 KiB / 32 KiB |
| RVV / VME | 开启，向量宽 128 bit |
| 浮点 / BF16 | 开启，与此前仿真生成配置一致 |
| AXI | 地址 32 bit、数据 128 bit、master ID 6 bit |
| verification 配置 | `false`；不是大容量 verification 变体 |

原始文件取自 `bazel-bin/hdl/chisel/src/coralnpu/`，不是其 `prod/` 子目录。脚本检查 `VVmeCoreMiniAxi_parameters.h` 中的真实参数，保存原始 `.sv`、`.zip`、参数头文件的 SHA-256；复制前后再次核对哈希，避免边生成边导出。

`manifest.json` 记录导出时 Git HEAD、生成文件哈希与已通过日志。HEAD 是导出时工作目录的版本，不能反过来当作旧生成文件的生成时提交证明。已有通过日志也没有补写“生成文件运行时哈希”：本流程保存现有生成物和证据，不声称重跑了功能仿真。

## 3. 文件与综合入口

```text
original/VmeCoreMiniAxi.sv          原始单文件生成物，字节不变
original/VmeCoreMiniAxi.zip         原始逐模块生成物，字节不变
original/VVmeCoreMiniAxi_parameters.h
rtl/                              原始 ZIP 的完整解包内容
compile_units/all.sv               只 include 原始文件的编译入口
filelist_synth.f                   综合文件清单，只有一个编译入口
dc_sources.tcl                    DC 的顶层、宏、包含目录、源文件变量
evidence/                         已有通过日志与生成/仿真 BUILD 文件
manifest.json                     导出来源与配置
SHA256SUMS                        包内所有文件的哈希
verify_export.py                  独立完整性核对工具
HANDOFF.md                        本说明，包含 RAM 规格
LICENSE                           官方许可，RTL 内原始版权头也保留
```

从包根目录使用清单。不要同时编译原始单文件 `.sv` 和逐模块 RTL，也不要同时分析 `compile_units/all.sv` 与它 include 的每个模块，否则会重复定义。

包装入口保持官方 ZIP `filelist.f` 的源文件、全局头文件、宏及 typedef 顺序；没有修改原始 RTL。综合宏为 `SYNTHESIS USE_GENERIC VLEN_128 TB_SUPPORT ZVE32F_ON ZVT_ON`。`SYNTHESIS` 让原始 `Sram.v` 选择可综合数组分支，而不是仿真的 DPI 存储分支；不改变 Chisel 生成参数，更不关闭 AXI 取指。这里没有加入 SRAM 黑盒替换或工艺库映射。

DC 可读取 `dc_sources.tcl` 中的变量。师兄沿用自己的库和约束脚本，在包根目录设置包含路径后执行 `analyze`：

```tcl
source dc_sources.tcl
set_app_var search_path [concat $handoff_include_dirs $search_path]
analyze -format sverilog -define $handoff_defines $handoff_sources
elaborate $handoff_top
```

这是文件入口说明，不是已执行过的综合报告。本次不新增 DC、频率验证或门仿工作。

## 4. RAM 交接规格

| 项目 | ITCM | DTCM |
| --- | --- | --- |
| 容量 | 8 KiB | 32 KiB |
| 组织 | 1 × 512 × 128 bit | 4 × 512 × 128 bit |
| 每块端口 | 单端口 1RW | 单端口 1RW |
| 地址 | 每块 9 bit 字地址 | 每块 9 bit 字地址 |
| 每字 | 16 byte | 16 byte |
| 写掩码 | 16 bit，每 bit 对应 1 byte，高有效 | 同左 |
| 访问时钟 | 上升沿 | 上升沿 |
| 读响应协议 | 一周期 | 一周期 |

TCM 合计 **5 块 512×128 bit，40 KiB**。DTCM 四个 bank 并不等于四个独立访问端口；40 KiB 也不包含标量/向量/矩阵寄存器及流水缓冲。

`Sram` 包装接口是 `clock, enable, write, addr, wdata[127:0], wmask[15:0], rdata[127:0], rvalid`；`enable`、`write` 高有效。`rvalid` 为请求有效延迟一周期，写请求也会产生延迟有效。RAM 本身没有清空阵列的复位，不应假定复位后数据全零。

当前地址图：ITCM `0x00000000–0x00001FFF`，DTCM `0x00010000–0x00017FFF`，核控制 CSR 窗口 `0x00030000–0x00030FFF`。开启外部取指允许核执行 ITCM 以外、由 AXI 外部存储器响应的代码，不增加 ITCM 容量。

之前 Verilator 仿真使用官方 DPI RAM 行为模型；交付保留同一份 `Sram.v`。综合用其数组分支。该分支能否映射成真实 SRAM，以及宏的端口/时序适配，由后续综合流程处理，不能将行为仿真模型当作工艺 SRAM。

## 5. 接收后核对

解压后进入包根目录：

```bash
sha256sum -c SHA256SUMS
python3 verify_export.py --verify .
```

Windows 也可以运行 `python verify_export.py --verify <解压目录>`。检查内容包括：原始生成物未变、所有逐模块文件与原始 ZIP 字节一致、参数为此前仿真配置、文件清单顺序正确、已有通过日志仍匹配。它验证交接完整性，不把打包成功当作新跑了功能仿真。
