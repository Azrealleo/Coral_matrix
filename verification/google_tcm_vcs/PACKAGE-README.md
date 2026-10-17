# 单NPU固定RTL：独立VCS工作集仿真包

本包只对应manifest中的一个DTCM容量，ITCM固定8KiB。服务器无需Bazel、Git、Java、firtool或RISC-V交叉编译器。**导出/哈希校验通过不是VCS仿真通过**；首次必须通过环境检查、VCS编译和小工作集，再跑大工作集。

## 保留的东西与边界

- `rtl/`：与已有控制组PASS产物SHA一致的原始单文件SV、参数头；不改写原RTL、不加SYNTHESIS、不替换SRAM。
- `original/`：原始生成ZIP；`rtl_dependencies/`是逐字节解出的完整依赖，**这些模块不与单文件SV重复编译**。
- 固定宏：USE_GENERIC、TB_SUPPORT、ZVE32F_ON、VLEN_128、ZVT_ON、ZVTBF16FMM_ON。512×128bit、一周期、16位byte mask的原始通用RAM；不是工艺宏/网表/SDF门仿。
- `dpi/`：固定官方提交的原始`sram_backdoor.cc/.h`，不改源码。原始Sram.v在Verilator/VCS仿真下均调用这套C++内存模型；前门装载也需要它。VCS入口显式定义后端宏VCS（与Verilator自动定义VERILATOR对应），单独在服务器编译本地DPI共享库，不复制Ubuntu的二进制。
- `firmware/workset_program.elf`：与完整T12工作集PASS记录SHA一致的RISC-V固件。同一个ELF支持本配置下的多个T和0/8附加读等待，换T不需要重新编译VCS。
- 当前测试入口专用于这个已验证固件，不是任意模型通用加载器。以后接入新模型需另行确认软件清单、布局和校验；不要直接替换包内ELF或修改manifest绕过完整性检查。硬件配置没变时仍可保留原RTL，软件测试入口可以独立扩展。
- `support/`及`python/coralnpu_test_utils/`：原始工作集、golden、AXI代理/观察器、fixture和严格结果解析器，不改算术、循环顺序、重复次数、计时窗口或AXI服务行为。
- `python/bazel_tools/`仅是路径适配器：把唯一的固件runfile名映射为包内ELF，不启动或依赖Bazel。
- 每策略3次独立重置重复；逐元素输出、软件计数、AXI实际握手、事务响应和重复周期均需正确。测试仍是**VCS+cocotb**，不是新写的原生SV测试平台，不能保证比Verilator快。
- 地址：ITCM0、DTCM0x01000000、CSR0x02000000、外部0x20000000；这是隔离实验地址，不是团队SoC集成修改。
- 测试时钟仍为1.25ns，与此前周期测试一致；它不证明物理800MHz或200MHz可达。主机装载/校验不计入NPU周期，但计入实际仿真墙钟耗时。
- 未强制把VCS四态中的X初始化成0，未屏蔽断言。若VCS报X或时序差异，先定位，不把掩盖X当成通过。

## 服务器环境

必须使用独立的**CPython3.11**环境，不能使用之前的系统Python3.6。依赖固定为`requirements.txt`中的cocotb2.0.0、NumPy1.26.4、pyelftools0.32、find-libpython0.5.1；刻意不复制Ubuntu的NumPy2.3.4或整个Conda环境。当前依赖版本旨在使用glibc2.17兼容wheel，实际动态库和VCS2020兼容性仍需下面的check/build验证。

原始SRAM C++使用C++17的structured bindings，系统GCC4.8不够。单独使用Conda C++17编译器把它编成C-ABI共享库，静态链接该库自己的libstdc++/libgcc，避免修改全局LD_LIBRARY_PATH。VCS自身生成代码仍默认使用`/bin/gcc`和`/bin/g++`，不强迫VCS2020改用新的主编译器。可用TCM_DPI_CXX指定DPI编译器、TCM_VCS_CC/TCM_VCS_CXX指定实验室支持的VCS主编译器。

如果管理员/其他组员已提供兼容Python3.11，优先使用。没有时，可在个人目录安装兼容CentOS7的旧Miniforge；不要安装要求更新glibc的最新版，不替换系统glibc，不全局修改LD_LIBRARY_PATH。Miniforge官方将24.9.2-0列为Linux x86_64/glibc2.17的兼容历史版本：
<https://github.com/conda-forge/miniforge#requirements-and-installers>

以下命令在实验室服务器、已连通网络/代理的终端执行；下载校验失败或已有同名安装目录时停止，不覆盖：

```bash
(
set -eo pipefail
tcm_env_tools="$HOME/coral_vcs_tools"
mkdir -p "$tcm_env_tools/downloads"
cd "$tcm_env_tools/downloads"
tcm_forge_base=https://github.com/conda-forge/miniforge/releases/download/24.9.2-0
curl -fL -o Miniforge3-24.9.2-0-Linux-x86_64.sh \
  "$tcm_forge_base/Miniforge3-24.9.2-0-Linux-x86_64.sh"
curl -fL -o Miniforge3-24.9.2-0-Linux-x86_64.sh.sha256 \
  "$tcm_forge_base/Miniforge3-24.9.2-0-Linux-x86_64.sh.sha256"
sha256sum -c Miniforge3-24.9.2-0-Linux-x86_64.sh.sha256
if [ -e "$tcm_env_tools/miniforge3" ]; then
    echo '安装目录已存在，停止；请使用已有安装，不覆盖。'
    exit 1
fi
bash Miniforge3-24.9.2-0-Linux-x86_64.sh -b -p "$tcm_env_tools/miniforge3"
)
```

在正常终端创建独立环境：

```bash
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda create -n coral-vcs --override-channels -c conda-forge \
  python=3.11 pip cxx-compiler sysroot_linux-64=2.17 -y
conda activate coral-vcs
# cd进入已解包的coral_tcm_vcs_d1024/（或d2048、d4096）后执行：
python -m pip install --only-binary=:all: -r requirements.txt
python -B runtime.py verify
python -B runtime.py check
```

每个新终端需重新激活该环境并加载实验室正常VCS许可环境。check会检查Python/依赖精确版本、VCS路径/版本、VPI与libpython的ldd依赖、ELF布局、全部向量/golden哈希、C++17编译器与VCS自带svdpi.h；不启动仿真、不改变许可配置，不把许可证内容写入记录。VCS_HOME未设置时会尝试vcs安装目录的include/；必要时可用TCM_VCS_DPI_INCLUDE指定真实VCS include目录，不能拿Verilator的svdpi.h替代。若Conda求解或动态库失败，保留报错，不自动修改系统环境。

## 一次编译，重复运行

在当前包目录内：

```bash
python -B runtime.py build
python -B runtime.py run --tiles 12 --delay 0
```

默认运行目录在包旁边的`<包名>_runtime/`，不修改包自身。可在每条命令中使用相同`--state-dir /绝对路径/独立目录`指定位置。新构建使用唯一目录；已成功且环境/RTL/模型hash匹配时build直接复用，不删除任何旧模型。当前使用cocotb2.0官方VCS runner（包含其默认VPI访问选项），不启用波形、FSDB、coverage或kdb；实际编译命令保存在`_build.log`，这不是最大速度优化配置。

build先用VCS头文件编译原始SRAM DPI库并检查ldd，再通过C ABI测试末地址128bit读写/byte mask，随后编译RTL。仿真通过`-sv_lib`加载同一库，库和simv/daidir均参与复用指纹检查。`[TCM_VCS_DPI_SELFTEST_PASS]`仅代表C++内存读写自检，不是RTL/NPU PASS。DPI源码、SV本体和内核均不为适配老系统而改写。

VCS编译参数包含`-assert svaext`，用于支持原始RTL中的elaboration system tasks（例如参数合法性检查中的`$fatal`）。若旧包报告`Using elaboration system tasks requires option -assert svaext`，使用源码仓库google_tcm_vcs目录的`upgrade_svaext.py`生成保留父包的新版启动包，不手动修改SV、manifest或旧包内文件。

必须收到`[TCM_VCS_RUN_PASS]`才算完整通过。程序同时要求XML恰好1个测试、无failure/error/skip，以及6条完整输出、终止marker、正确golden/流量和重复性。单条`status=PASS`或`[TCM_VCS_BUILD_PASS]`都不等于整组仿真PASS。

本容量/同编译模型的T12/等待0完整通过后，才允许启动T>12。例如1MiB与2MiB包都分别先通过小用例，再分别运行：

```bash
python -B runtime.py run --tiles 384 --delay 0
```

4MiB包也先通过小用例；后续在2/4MiB包使用同T768比较。运行时只加载不同参数/数据，不需要重新生成RTL或重新编译VCS。每项默认6小时墙钟保护，可用`--timeout 43200`改为12小时，上限86400秒。构建与运行分别计时，超时杀掉本次子进程组并保留日志，不把部分记录计为通过。未提供checkpoint续跑。

## 结果与性能口径

运行目录包含`_test.log`、`results.xml`、命令、环境、墙钟时间/退出码、包manifest快照和严格校验后的`result.json`。主机实际耗时以`[TCM_VCS_RUN_PASS] simulation_wall_seconds`为准；该值包括初始化、执行和校验，不是纯RTL仿真吞吐率。编译耗时单独记录。`wait_for_halt_cycles`、CSR窗口和AXI字节仍按原来的定义，不因为换后端而更换口径。

用`python -B runtime.py compare --logs /绝对路径/日志1 /绝对路径/日志2`复用严格跨容量比较器（可读取原Verilator日志与新VCS日志），需同T、延迟、ELF和布局。先检查后端切换是否出现周期偏移，发现偏移需定位调度/采样差异，不能直接认作硬件提速。

若要比较真实仿真耗时，还需在Ubuntu运行同容量、同T12、同等待0的Verilator用例，不能拿1MiB VCS与32KiB Verilator的耗时直接比较。服务器与虚拟机硬件不同，墙钟差异也不能全部归因于仿真器。

服务器上的VCS2020、此Python环境和当前RTL尚需实际验证。包内原始证据只证明源配置、RTL字节与控制组PASS相同及固件来自已通过工作集；不是本包已在VCS通过、不是完整模型验证、更不是DC/门仿报告。
