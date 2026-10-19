# 固定RTL包实际导出记录

各小节按发生时保留状态，文末为最新结果。当前三档导出，服务器1/2MiB传输与VCS编译，VCS1MiB T12/T384及2MiB T12均PASS。VCS2MiB T384仅收到启动，4MiB服务器未回传。独立Verilator1MiB T12/T384均完整PASS、VCS参考EXACT，429.077/13979.842秒；下一步准备2/4MiB T768，各自先T12。接手见[当前指南](../HANDOFF-current.md)，不改旧包manifest。

## 2026-10-17：DTCM 1MiB

依据：用户回传的Ubuntu导出及实验室服务器终端输出；Windows工作区未直接读取该归档。

- 固定官方提交：`8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`。
- 导出工具提交：`088b836`；Bazel 9.1.0二进制校验输出为OK。
- 单NPU顶层：`VmeCoreMini_ITCM8KB_DTCM1024KBAxi`；ITCM 8KiB，DTCM 1024KiB。
- 导出工作目录：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d1024.yzU5z6`。
- 包目录：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d1024.yzU5z6/coral_tcm_vcs_d1024`。
- 归档：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d1024.yzU5z6/coral_tcm_vcs_d1024.tar.gz`。
- SHA256：`0e969183cd48d3f7a9eaa062e31aded9d89b011fa8fcddee58febd69823b8cb8`。
- 校验文件：同目录的`coral_tcm_vcs_d1024.tar.gz.sha256`。
- `[TCM_VCS_EXPORT_VERIFIED]`确认：`control_rtl_bytes_equal=true`、`firmware_bytes_equal=true`、`vcs_simulation="NOT_RUN"`。
- Bazel构建耗时59.043秒、1366项缓存命中；这是缓存构建/导出耗时，不是RTL仿真耗时。

结论：已导出与已有控制组PASS产物字节一致的RTL、与完整T12工作集PASS记录字节一致的固件。**不代表VCS编译或VCS仿真通过，也不能据此评价VCS速度。**

### 服务器实际进展

- 归档校验输出`coral_tcm_vcs_d1024.tar.gz: OK`，解包后输出`[TCM_VCS_SERVER_PACKAGE_CHECK] PASS`。
- 包位置：`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024`（`/home2/lqq`路径解析到`/data/home2/lqq`）。
- `[TCM_VCS_PACKAGE_VERIFIED]`通过；`[TCM_VCS_ENV_CHECK]`通过：独立Python3.11、cocotb2.0.0、NumPy1.26.4、pyelftools0.32、find-libpython0.5.1，主机glibc2.17；向量与ELF检查通过。
- VCS：`/opt/Synopsys/vcs/Q-2020.03-SP2-7/bin/vcs`。
- 首次构建目录：`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_runtime/builds/ad64e2610e46.ioqlvkyn`，日志`_build.log`保留。
- 原始SRAM DPI编译及C-ABI读写/byte mask自检通过，输出`[TCM_VCS_DPI_SELFTEST_PASS]`；这不是RTL仿真PASS。
- VCS解析SV第167036行elaboration `$fatal`时停止：`Using elaboration system tasks requires option -assert svaext`。当前证据是启动器漏加工具选项，不是已证明DivSqrt WIDTH非法。
- 旧启动器在提交088b836中未加该选项；现编译入口补入`-assert svaext`，为旧包提供保留父包的`upgrade_svaext.py`。只更改启动器编译参数，新manifest记录父包身份，不重新基准化RTL/固件哈希。
- 用户回传升级成功：新版包`coral_tcm_vcs_d1024_svaext_v1`；父manifest SHA256为`c9baf6844763752bd302a63bb544792abf769be768303e69f30fdcc64990dcc5`，原包、RTL及固件均不变。
- 升级后第二次构建目录为`coral_tcm_vcs_d1024_svaext_v1_runtime/builds/b2ceeee4d376.mwfd6xxz`。已越过原SV语法错误，122个module被读取；VCS生成的rmapats.c在隐式函数声明处编译停止，不能当作NPU仿真失败。
- 用户检查确认：系统`/bin/gcc`为4.8.5，激活Conda后的默认gcc为15.3.0；CC/CXX及常见flags环境变量为空；生成规则使用`$(CC_CG) $(CFLAGS_CG)`。具体CC_CG变量定义未回传，不把推测当成完整编译跟踪。
- 单次子终端把`/usr/bin:/bin`置于PATH前，保留Conda Python与DPI G++的绝对路径，并显式设置VCS CC/CXX为系统工具后，输出`[TCM_VCS_BUILD_PASS] compile_seconds=60.523`。
- 成功构建目录：`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_runtime/builds/754330b47408.u824wjiz`。60.523秒仅是构建时间，不是仿真耗时。
- 后续T12/等待0运行目录：`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_runtime/runs/t12_r0.6xf7vakp`。
- 运行入口输出`[TCM_VCS_STOP] Extra data: line 1 column 1946 (char 1945)`，当时未创建最终result.json。
- 后续用户回传XML：恰好一个`tcm_workset_test`，未出现failure/error/skipped；cocotb汇总`TESTS=1 PASS=1 FAIL=0 SKIP=0`，完整工作集完成标记出现，6条结构化记录均存在。
- 6条记录全部在JSON结尾附带SGR颜色复位字符`\x1b[49m\x1b[39m`；stream三次`wait_for_halt_cycles=225222`，prefix三次为145029，与Ubuntu1MiB T12一致。明确是展示字符使JSON汇总器拒绝解析，不据此称RTL算术失败。
- XML记录sim_time_ns=1411740.0、cocotb testcase time=1178.2477581501007秒（约19分38秒）；不是NPU硬件执行秒数，也不是最终wrapper墙钟值。与Ubuntu测试292.4秒的主机耗时不同，但两台主机、统计边界不同，不能据此给出仿真器本身的加速比；至少当前观测没有VCS更快的证据。
- 用户尚未回传原始_test-status.json内容及全部结构化数据；不只凭上述截断诊断就补写最终PASS。新增包外vcs_workset.py，保留原包/模型/原日志，重新检查完整进程状态、命令、模型与环境身份、XML、6条记录及原始文件哈希，再创建缺失的验收结果。
- 首版包外入口23afde9已在服务器下载、SHA256校验OK，位置`/home2/lqq/coral_vcs_tools/ansi_fix.xZ2b2v/vcs_workset.py`，脚本SHA256为`9e54a84b7e0f18f8ba53034428ec9272672ead2296ba66ff412637c62fc09654`。执行停止于`logged ELF/layout/vectors do not match this package`，未输出ACCEPT_PASS。
- 已本地重现并修复首版验收器的表示误比较：inspect_elf返回的加载段列表含元组，日志JSON含列表；只统一预期容器表示，不改变任何地址、长度或身份值。新增真实返回类型回归和逐字段错误值拒绝测试，修正版输出不匹配字段名。该失败发生于创建result.json之前，原始仿真不需重跑、证据不需删除。
- 修正版包外入口760bda8已在服务器下载并SHA256校验OK；路径`/home2/lqq/coral_vcs_tools/ansi_fix_v2.bzKDlm/vcs_workset.py`，脚本SHA256为`e2668cd25e690177dea89087f4804b7fb4a426c8c9e8a2a2d19c9effb04999f0`。
- 用户回传两条完整`[TCM_WORKSET_SUMMARY]`和`[TCM_VCS_ACCEPT_PASS] simulation_rerun=false raw_files_unchanged=true simulation_wall_seconds=1185.423`。验收复用原运行，不重跑仿真、不修改原始日志；result.json在原运行目录中新建，原模型/环境/命令/退出状态/XML/6条记录及数据身份通过严格检查。
- stream：等待halt225222周期，CSR总周期224975，输入/权重/计算及读出/输出周期为10002/120384/60336/32148，外部权重读取147456字节。
- prefix_cache：等待halt145029周期，CSR总周期144782，对应阶段为10002/40296/60336/32148，驻留12块，外部权重读取49152字节。
- 两策略各重复3次，每次9216输出元素；ELF SHA为`a8aa2d6feaefd56a5901f8bcca4f8f6bbf5394932add092243aff8f5eb497192`，向量SHA为`5f48b97cefb656ad1e4a96dc80a3f42804ed86d9c0553dade288d14519ebeb93`。两条汇总中的全部字段（包括AXI计数、各阶段/轮次周期）与Ubuntu1MiB/T12摘要一致。
- **1MiB VCS T12/等待0已正式验收PASS**，仅适用于该固定配置和工作集，不是整模型、2/4MiB或物理时序的PASS。

当时的下一步建议是回Ubuntu顺序跑1/2MiB T384，并保留VCS交叉验证；后来这些Ubuntu任务和服务器1MiB T384已完整通过，2MiB小用例也已通过，见文末，不再重复启动旧计划。VCS继续运行仍使用包外入口和相同编译器隔离，6小时默认上限不是耗时保证；4MiB需要自己的小用例，不能拿1MiB包冒充。

本记录位于源码仓库，独立于已导出的不可变包；不要为更新状态而修改包内文件或其manifest。

## 后续回传：DTCM 2MiB导出

- 固定官方提交仍为`8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`；ITCM仍为8KiB。
- 顶层：`VmeCoreMini_ITCM8KB_DTCM2048KBAxi`。
- 工作目录：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d2048.T5HEGi`。
- 包目录：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d2048.T5HEGi/coral_tcm_vcs_d2048`。
- 归档：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d2048.T5HEGi/coral_tcm_vcs_d2048.tar.gz`。
- SHA256：`499a7c31d97d06cb39ff8dcebe1ac2c6232605943d044af5d2eaa83ebe27d768`。
- `[TCM_VCS_EXPORT_VERIFIED]`：`dtcm_kib=2048`，`control_rtl_bytes_equal=true`，`firmware_bytes_equal=true`，`vcs_simulation="NOT_RUN"`。
- Bazel构建28.024秒；两条Chisel枚举转换warning未阻止生成，不将其解释为完整设计已无问题。
- 导出当时状态：Ubuntu导出与字节核验已通过；后续服务器传输、VCS编译/T12 PASS见下节，不能改写导出时包内NOT_RUN声明。

## 后续回传：DTCM 4MiB导出

- 固定官方提交及ITCM与2MiB一致。
- 顶层：`VmeCoreMini_ITCM8KB_DTCM4096KBAxi`。
- 工作目录：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d4096.W2JmMH`。
- 包目录：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d4096.W2JmMH/coral_tcm_vcs_d4096`。
- 归档：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d4096.W2JmMH/coral_tcm_vcs_d4096.tar.gz`。
- SHA256：`272a4e81560856660801d9c7dbcf28b40d8d290b3d1886395aa5f0c46d5269a5`。
- `[TCM_VCS_EXPORT_VERIFIED]`：`dtcm_kib=4096`，`control_rtl_bytes_equal=true`，`firmware_bytes_equal=true`，`vcs_simulation="NOT_RUN"`。
- Bazel构建25.754秒；同样两条Chisel枚举转换warning未阻止生成。
- 状态：Ubuntu导出与字节核验已通过，尚未回传服务器传输校验、VCS编译或VCS仿真结果。

三档导出仅证明包内RTL与对应容量的已通过控制组产物一致、固件与已通过工作集一致；不代表这些独立VCS包已通过仿真。2/4MiB导出耗时不是容量性能数据，包内`vcs_simulation="NOT_RUN"`是导出时的声明，不因后来服务器编译而修改原包。

## 后续已回传：VCS正常T12测速与profiling

1MiB正常复测目录`.../coral_tcm_vcs_d1024_svaext_v1_runtime/runs/t12_r0.mraudje0`，两策略完整PASS，周期/CSR/AXI/数据身份与首次验收结果相同；wrapper1178.5秒，cocotb1172.38秒，逻辑仿真时间1411740ns。它是新的正常速度参考，不覆盖首次运行。

profiling目录`.../runs/t12_r0.xluxpvy5`也完整PASS，wrapper1403.893秒；实际文件`cocotb.pstat`，638658902次函数调用、profile总433.861秒。不同层级的cumtime有包含关系，不能相加或把wrapper减profile当精确RTL内核时间。详细调查见[全程记录第24节](../WORKLOG-and-handover.md#section-24)。profiling运行不作为正常速度基线。

## 2026-10-18：1MiB/T384 VCS完整PASS

原运行根：

```text
/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_runtime/runs/t384_r0.pyg9qm5e
```

用户提供6条原始JSON、完整工作集CHECK、cocotb1/1 PASS及外层RUN_PASS/OVERNIGHT_ALL_PASS。stream等待6885516周期，prefix5208090周期；CSR总分别6885263/5207833，权重字节分别4718592/2662400。每策略3次、每次294912输出，全部计数与随后Ubuntu同容量摘要一致。

wrapper37619.46秒，cocotb37605.01秒，逻辑仿真时间45608321.25ns；10月18日02:21启动、12:47:53仿真结束、12:48:02外层ALL_PASS。不是NPU实际执行10小时，也不是所有容量/模型通过。完整容量结果见[工作集记录](../google_tcm_capacity/WORKSET-results.md)。

## 2026-10-18：2MiB服务器传输、VCS编译/T12 PASS

- 原归档`coral_tcm_vcs_d2048.tar.gz`服务器SHA检查OK，用户回传`TCM_2M_TRANSFER_PASS`。
- 包根：`/home2/lqq/Desktop/coral_tcm_vcs_packages/d2048_499a7c31/coral_tcm_vcs_d2048`。
- 完整pilot控制台：`/home2/lqq/coral_vcs_tools/d2048_pilot.LfpAwL.log`。
- 构建：包同级`coral_tcm_vcs_d2048_runtime/builds/5f9c6915a993.06j4djj0`；编译54.893秒PASS。
- T12：同级`coral_tcm_vcs_d2048_runtime/runs/t12_r0.e0u9djj4`；wrapper1187.676秒，RUN_PASS及PILOT_ALL_PASS。
- stream等待225226、prefix145033周期，内部总CSR224975/144782、权重阶段120384/40296、权重外读147456/49152字节，其他阶段/AXI/轮次/ELF和T12向量身份与1MiB小负载对应一致。
- 两策略各3次、每次9216输出检查；pool508、prefix驻留12块。比1MiB两个halt窗口均多4周期，内部CSR不变，原因未定位，不擅自修正。

随后2MiB/T384后台任务日志目录`/home2/lqq/coral_vcs_tools/overnight_vcs.TdW8Yk`，10月18日13:28:53启动，当时launcher PID344971。**当前没有最终回传**，不能推定已通过、仍在跑或使用此过时PID执行kill。

4MiB仍只有Ubuntu导出及字节一致性结果，未收到服务器传输/编译/运行；后续新建独立目录、自己的T12，通过后才允许T768，不复用其他容量二进制。

## 2026-10-19：同包新增独立Verilator后端，不动VCS材料

服务器`coral-verilator`环境基本检查PASS，采用用户态Conda新版工具而不改系统glibc；独立入口不需要Bazel，使用同包原始单文件SV、原SRAM C++和同fixture/ELF/向量。模型和日志另存`<包名>_verilator_runtime`，不覆盖VCS `_runtime`。

1MiB构建目录`.../coral_tcm_vcs_d1024_svaext_v1_verilator_runtime/builds/e6ab26657e58.xbhdmzuj`，编译434.214秒PASS。首次T12目录`.../runs/t12_r0.zl1315rn`在1.777秒退出255：`--trace requires the design to be built with trace support`。原入口WAVES/GUI字符串0被cocotb当真，不是RTL算术结果或超时。

修复提交`c0b4b76098a88d5bace3c3fbdcef318c10e924f7`，脚本SHA`9031f22eadbfc75d308f2bcd67bde9b943b06822ccbbe8da702b821112273855`。本地25项检查通过；严格核验后可复用既有模型而不改包/构建记录。最初此处还未收到实际运行；随后T12正式通过，见后续记录。Server Verilator大测试速度仍无回传。

### 后续1MiB Verilator T12实际验收PASS

入口`/home2/lqq/coral_vcs_tools/verilator_trace_fix.S7nNd7/verilator_workset.py`，控制台同目录`console.log`；运行根为同级`coral_tcm_vcs_d1024_svaext_v1_verilator_runtime/runs/t12_r0.fmvgge7f`。原`e6ab26657e58.xbhdmzuj`模型/记录不变，回传BUILD_REUSED/RUNTIME_FIX。

用户回传两条SUMMARY及REFERENCE_MATCH=EXACT、RUN_PASS=429.077秒。stream225222周期、prefix145029周期，CSR/轮次/AXI/ELF/向量与VCS1MiB正常T12参考全部相同；每策略3次，合计55296输出。此为真实RTL+严格参考验收，不是环境检查或单元测试。

相比同服务器VCS正常T12 wrapper1178.5秒，当前流程观察快2.74659倍、墙钟少63.5913%，编译另计；不外推其他工作集。后来1MiB T384也实际通过，见下节；[原命令](../HANDOFF-current.md#server-verilator-t384)保留为复现，不再重复跑1MiB。

### 后续1MiB Verilator T384正式PASS，VCS参考EXACT

控制台`/home2/lqq/coral_vcs_tools/verilator_t384.ydMKyr.log`；结果在包同级`coral_tcm_vcs_d1024_svaext_v1_verilator_runtime/runs/t384_r0._66rc55e`。原模型只读复用，2策略×3次、每次294912输出，总1769472元素检查；全部周期/CSR/轮次/AXI/ELF/向量与VCS大日志一致，用户回传REFERENCE_MATCH=EXACT、RUN_PASS=13979.842秒。

stream等待6885516、CSR总6885263、外部权重4718592字节；prefix等待5208090、CSR总5207833、驻留251块、权重2662400字节。不是新扩容结果，只确认该1MiB大工作集后端一致。

墙钟约3h53m，相对同服务器VCS37619.46秒观察快2.69098倍、少62.8388%；VM同档Bazel test6736.5秒，当前VM流程仍比服务器Verilator观察快2.07524倍。主机/编译器/统计边界及负载不完全受控，不当纯引擎或芯片速度结论。

当前回到2/4MiB T768准备：已落地2MiB包先独立Verilator编译/T12，用原VCS2MiB小用例作精确参考；4MiB仍需确认传输/模型及T12。[下一步命令](../HANDOFF-current.md#server-verilator-2m-pilot)。VCS2MiB/T384最终状态未收到，不猜测、不停止他人任务。
