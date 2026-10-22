# 服务器独立Verilator：原封不动读取已校验的TCM RTL包

**2026-10-22范围覆盖：** 下方TCM后端结果及命令保留为历史；不自动恢复2/4MiB T768或重编已验证模型。当前LLM算子使用另一份固定256/512KiB Pool模型及小固件包，见[最新进度](../PROGRESS-current.md)和[LLM服务器入口](../google_llm_ops/server/SERVER.md)。不能混用两套构建身份。

状态：2026-10-19已收到服务器1MiB/T12完整RTL PASS及与VCS参考的精确比对PASS，实际运行429.077秒；复用了434.214秒编译通过的原模型。首次trace启动失败保留，修复后的新运行另存，不覆盖失败证据。环境为Python3.11.17、Verilator5.052、Conda GCC15.3、glibc2.17。

后续1MiB/T384亦已完整PASS、精确匹配VCS，13979.842秒，继续复用原模型。这个后端交叉验证已完成，不再重复跑1MiB；当前转向2/4MiB的T768准备，先为每个新容量完成自己的T12。服务器2MiB包已落盘，可按[当前交接指南](../HANDOFF-current.md#server-verilator-2m-pilot)建立独立模型及pilot；4MiB传输/运行尚未确认。只更新外层说明，不修改已导出包或原证据。

## 后续回传：1MiB/T384实际PASS，VCS参考EXACT

- 控制台：`/home2/lqq/coral_vcs_tools/verilator_t384.ydMKyr.log`。
- 结果：`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_verilator_runtime/runs/t384_r0._66rc55e`。目录随机后缀中的下划线是实际字符，不要删改。
- 原`e6ab26657e58.xbhdmzuj`模型及构建记录未改；无新增RTL/固件/编译动作。
- 两策略各3次，每次294912个输出、75497472个有用MAC，合计1769472输出检查；ITCM8KiB/DTCM1MiB、T384、附加读等待0。
- stream等待6885516周期、CSR总6885263、权重外读4718592字节；prefix等待5208090、CSR总5207833、驻留251块、权重外读2662400字节。输入/计算/输出阶段、轮次、AXI全部拍数/事务/字节、ELF和向量均与原VCS参考一致。
- 用户回传REFERENCE_MATCH=EXACT及RUN_PASS=13979.842秒，约3h53m。这是完整大工作集交叉验证，不是只测首轮或拼接残缺记录。
- 同服务器VCS原wrapper37619.46秒，当前Verilator流程观察快2.69098倍、墙钟少62.8388%；VM同容量Bazel test6736.5秒，VM流程观察比服务器Verilator快2.07524倍。统计边界/机器/当时负载不同，不作为纯CPU或引擎理论速度比。
- 本次墙钟为T12的32.5812倍，与32倍tile规模接近，但不能保证T768或不同容量同比例。NPU周期完全相同，变化的是主机仿真开销，不是硬件计算加速。

## 2026-10-19：修复后的T12实际PASS

- 已使用的修复入口：`/home2/lqq/coral_vcs_tools/verilator_trace_fix.S7nNd7/verilator_workset.py`；脚本SHA256仍为`9031f22eadbfc75d308f2bcd67bde9b943b06822ccbbe8da702b821112273855`。
- 控制台：同目录`console.log`。
- 实际运行：`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_verilator_runtime/runs/t12_r0.fmvgge7f`。
- 复用模型`.../builds/e6ab26657e58.xbhdmzuj`；输出BUILD_REUSED和RUNTIME_FIX，原模型及构建记录未改。
- 两策略各3次、每次9216个输出检查，合计55296元素；stream等待225222周期，prefix145029周期。对应CSR总224975/144782、权重外读147456/49152字节、AXI读9984/3840拍、写2304拍，其他阶段/轮次及数据身份与原VCS参考相同。
- 用户回传`TCM_VERILATOR_REFERENCE_MATCH cycles_counters_axi_elf_vectors=EXACT`及`TCM_VERILATOR_RUN_PASS simulation_wall_seconds=429.077`。不是只凭编译或两条摘要推定PASS，完整外层验收已执行。
- 同服务器当前配置/T12下，对比正常VCS wrapper1178.5秒，观察速度比2.74659、墙钟减少63.5913%；两个流程均不把编译时间算入运行值。不是所有模型的仿真器理论比，也不承诺T384/T768同比例。
- Ubuntu同容量T12的Bazel test292.4秒仍是不同机器/略不同边界，不用来评价服务器CPU优劣或纯引擎速度。服务器其他容量尚需自己的T12。

本地验证：修正前19项检查通过，但当时的真实Runner测试未使用生产子进程环境，漏掉了`WAVES="0"`问题。补充生产环境到真实cocotb2.0接口的启动命令检查、旧模型只读复用和拒绝环境/命令/模型篡改等回归后，本入口25项通过。原DTCM工具64项和原VCS工具40项此前回归通过。这些检查不替代服务器上的RTL测试。

最新DTCM状态：Ubuntu1/2MiB T384均完整PASS并配对；服务器VCS1MiB/T384 PASS（37619.46秒）、VCS2MiB/T12 PASS（1187.676秒），VCS2MiB/T384只收到启动。服务器Verilator1MiB T12/T384均精确匹配VCS，其他容量仍需自己的pilot。ITCM暂停，不把其几何工具自测当RTL/模型性能验证。

只把`verilator_workset.py`放到包外即可，无需克隆整个仓库、重新导出RTL或在服务器装Bazel/Java/RISC-V编译器。读取原`google_tcm_vcs`导出的不可变1/2/4MiB包；核验固定校验库SHA和完整manifest后才导入原始测试。原VCS的包、simv、运行目录和日志不动，ITCM保持8KiB，暂停新的ITCM实验。

## 语义与构建

- 用同一份原始单文件SV，不把ZIP内SV重复编译；宏与原工作集相同，Verilator自带VERILATOR宏选择原始SRAM DPI路径，不定义VCS或SYNTHESIS。
- 原始`sram_backdoor.cc/.h`直接编译链接进Verilator模型，使用Verilator的DPI头文件；不复用VCS的DPI SO或头文件，不将SRAM改为其他模型。
- 编译命令沿用原Bazel模型：仅顶层`io_*`/时钟/复位public、原警告列表、C++17、OPT_FAST=-O3、-rdynamic，不使用`--public-flat-rw`保留全部内部网。
- 不使用cocotb默认Verilator build入口，以免它自动打开全网可见性。test使用cocotb2.0公共Runner接口；显式`COCOTB_TRUST_INERTIAL_WRITES=0`，保留原Python时钟和写入调度，不因后端自动切GPI时钟。
- 时钟1.25ns只是原仿真时间单位，不代表硬件频率可达800MHz。无波形，无profiling，无新增关闭断言/时序检查选项。模型运行默认单线程；--jobs仅控制编译进程（默认2，上限8）。
- 编译器采用coral-verilator的新版GCC/G++，不套用VCS的系统GCC4.8优先设置。子进程共享库路径限于本环境，不全局修改系统LD_LIBRARY_PATH。

## 隔离与验收

每包使用独立同级`<包名>_verilator_runtime/{builds,runs}`。编译/运行失败、超时保留原始日志、命令和退出码，不自动清理、不覆盖旧模型。构建指纹包括入口、包、工具版本/哈希、Python/VPI库、编译环境和可见性策略；原指针只在新模型完整构建后更新。相同包的并发启动会被独立锁拒绝，不停止其他用户进程。

### 2026-10-19：关闭错误启用的波形，不重编已有模型

首次服务器T12目录`..._verilator_runtime/runs/t12_r0.zl1315rn`的进程1.777秒退出255、未超时，错误为`--trace requires the design to be built with trace support`。原因在包外入口：子进程设置`WAVES="0"`和`GUI="0"`，但[cocotb2.0的Runner源码](https://docs.cocotb.org/en/v2.0.0/_modules/cocotb_tools/runner.html)用`bool(os.getenv(...))`判断，两个非空字符串均为真，覆盖显式`waves=False, gui=False`并追加`--trace`。这不是RTL算术失败，也不是慢速仿真或编译失败。

修复只从子进程环境移除WAVES/GUI，继续显式传False；不增加编译跟踪、不改RTL/DPI/固件/测试内容。除了当前入口自身的模型，额外仅允许复用原入口SHA256为`f502f30e17d75e408418e89e408aa115c156d5ef4907f8c0e6701c41c7ca3d0d`生成的模型，条件为：完整旧构建身份与当前包/环境匹配、模型文件哈希一致、保存的全部编译命令和顶层可见性与当前配方一致、保存的构建记录与退出0且未超时的状态一致。任何条件不符，`run`停止，不自动重编或更改校验值。

已有模型目录`.../builds/e6ab26657e58.xbhdmzuj`、原构建记录和指针保持不变；新的T12使用新运行目录。成功结果保留实际旧`build_identity`，另记当前运行入口`adapter_sha256`，不把旧可执行文件冒充新编译。看到BUILD_REUSED只表示复用校验通过，最终仍须REFERENCE_MATCH和RUN_PASS。

先用`verify`校验包，`check`核对环境/全部工作集向量/真实ELF布局，再`build`，然后`run --tiles 12 --delay 0 --reference-log <同容量已完整通过的日志>`。

原测试依旧两策略、每策略独立重复3次，检查全部输出、CSR阶段周期、每轮周期和实际AXI事务。外层要求子进程退出0、XML恰好一个无失败/跳过测试、原严格解析器接受完整6条记录、实际ELF/入口/加载段/符号/向量身份匹配，包及模型运行前后不变。只在JSON边界内存去除SGR显示颜色，不修改原日志、不修复JSON。

首次T12还必须与指定的同容量VCS/Verilator已通过日志精确匹配（含halt周期、CSR、AXI、轮次、固件和向量）；不匹配停止，不偷偷给周期加偏移。只有相同包、相同模型和环境下完成参考比对的T12记录才解锁其他工作集/延迟。profiling开启时拒绝作为速度基线。

`TCM_VCS_PACKAGE`只是既有runfiles适配器历史变量名；在此用于定位同一ELF，不代表运行VCS。

## 首次在服务器运行

激活`$HOME/coral_vcs_tools/miniforge3`下的`coral-verilator`，把本入口下载到包外新目录，并核对随命令提供的固定SHA。不要把脚本写进原包。

```bash
python -B /包外路径/verilator_workset.py --package /已有包目录 verify
python -B /包外路径/verilator_workset.py --package /已有包目录 check
python -B /包外路径/verilator_workset.py --package /已有包目录 build --jobs 2
python -B /包外路径/verilator_workset.py --package /已有包目录 run \
  --tiles 12 --delay 0 --reference-log /同容量完整通过的_test.log
```

看到`[TCM_VERILATOR_REFERENCE_MATCH]`和`[TCM_VERILATOR_RUN_PASS]`才代表跨后端验收成功；本次1MiB/T12两者已实际收到。check/Python导入/工具单元测试均不是RTL PASS。新增容量首次模型仍在服务器本地编译，不传Ubuntu可执行文件；编译与运行分开记录。其他工作集和容量的提速仍待实测，不用T12或VM结果替代。

之后才能在同一模型上`run --tiles 384 --delay 0 --timeout 86400`等。4MiB必须先传输其独立RTL包并完成自己的T12验收，不复用1/2MiB模型。
