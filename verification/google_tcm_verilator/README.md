# 服务器独立Verilator：原封不动读取已校验的TCM RTL包

状态：服务器`coral-verilator`基础环境已回传PASS（Python3.11.17、Verilator5.052、Conda GCC15.3、glibc2.17）；本入口尚无真实RTL编译/仿真PASS，不能据此承诺速度。

本地验证：新入口19项检查通过（含真实cocotb2.0公共test接口、保留Python时钟、真实原包只读验证、完整结果/精确参考比对、失败/超时保留及大测试门控）；原DTCM工具64项和原VCS工具40项回归通过。它们不替代服务器上的模型编译和RTL测试。

最新已回传的DTCM工作集状态：Ubuntu1/2MiB的T384均完整PASS并配对比较；服务器1MiB/T384完整PASS（流程37619.46秒），2MiB/T12完整PASS（1187.676秒）；服务器2MiB/T384仅收到启动信息，尚无完成回传。ITCM新工具已暂缓，不把其几何检查当作模型性能验证。

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

看到`[TCM_VERILATOR_REFERENCE_MATCH]`和`[TCM_VERILATOR_RUN_PASS]`才代表这轮跨后端验收成功。check/Python导入/工具单元测试均不是RTL PASS。首次模型要在服务器重新编译，不传Ubuntu可执行文件以免glibc不兼容；编译时间与运行时间分开报告。实际提速待服务器实测，不以虚拟机结果替代。

之后才能在同一模型上`run --tiles 384 --delay 0 --timeout 86400`等。4MiB必须先传输其独立RTL包并完成自己的T12验收，不复用1/2MiB模型。
