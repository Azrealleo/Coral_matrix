# 官方单NPU：Ubuntu导出，CentOS7独立VCS运行

当前状态：**1/2/4MiB均已实际导出并通过原RTL/固件字节一致性检查；1MiB已在服务器通过VCS编译（60.523秒），T12的cocotb/XML为1/1 PASS，六条记录和完成标记已回传，但汇总器被JSON后的SGR颜色复位字符阻断**。已新增下述包外验收入口；实际重新验收结果待回传。2/4MiB尚未回传服务器编译/运行结果。1MiB还已在Ubuntu通过同T12的Verilator完整测试（292.4秒）。实际路径、包SHA256与状态见[导出记录](EXPORT-results.md)。保持旧的Bazel/Verilator实验副本、manifest、程序和结果，不修改团队仓库。

## 旧版包：补充VCS elaboration选项

VCS Q-2020.03-SP2-7在原始RTL的elaboration `$fatal`处明确报告`Using elaboration system tasks requires option -assert svaext`。这是旧版启动器漏加编译选项，并非已经证明WIDTH参数非法；不删除检查、不加SYNTHESIS、不关闭断言或改RTL。

新导出的包自动包含`-assert svaext`。已经传到服务器的旧包无需重新生成RTL、重新跑Bazel或复制整个仓库，只需取得本目录的`upgrade_svaext.py`，在服务器已激活的coral-vcs环境执行：

```bash
python -B /已下载的脚本路径/upgrade_svaext.py \
  /home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024
```

升级器先校验原版校验库/启动器固定SHA、完整manifest及全部包文件，然后新建同级`coral_tcm_vcs_d1024_svaext_v1`（已存在则拒绝覆盖）。唯一既有负载改动是runtime.py编译参数增加两个token；SV、ZIP、头文件、DPI、固件、fixture和工作集脚本字节不变。新manifest记录父manifest哈希及升级原因，并保存父manifest证据。原包、原SHA文件和失败编译日志保留；不篡改旧包来伪造校验通过。

进入新包目录运行`python -B runtime.py verify`及`python -B runtime.py build`。编译参数参与build identity，新包使用新的独立runtime目录，不复用旧失败模型。升级PASS不等于VCS编译/仿真PASS。

## 实验室已验证的编译器隔离方式

服务器系统GCC4.8.5、Conda默认GCC/G++15.3.0。补入svaext后，VCS内部`filelist.hsopt`使用`CC_CG`构建rmapats.c；仅传`-cc /bin/gcc`仍出现隐式函数声明错误。将系统目录放在PATH前、同时保留Conda Python与DPI编译器绝对路径后，1MiB实际编译通过。构建和运行都使用相同隔离设置，避免环境指纹改变；设置限于子终端，不修改系统配置或全局LD_LIBRARY_PATH：

```bash
(
set -eo pipefail
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-vcs
tcm_python="$CONDA_PREFIX/bin/python"
tcm_dpi_cxx=$(command -v g++)
export TCM_DPI_CXX="$tcm_dpi_cxx"
export PATH="/usr/bin:/bin:$PATH"
export CC=/bin/gcc CXX=/bin/g++
export TCM_VCS_CC=/bin/gcc TCM_VCS_CXX=/bin/g++
cd /home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1
"$tcm_python" -B runtime.py check
"$tcm_python" -B runtime.py build
)
```

这是已通过编译的环境设置，不等于所有容量的VCS测试已通过。1MiB T12的JSON异常已定位为下述SGR显示颜色；不要编辑日志、放宽算术/流量判据或跳过重新验收。2/4MiB仍需各自的小工作集验收。

## 不重跑仿真：验收已有彩色日志

本次JSON结尾为`}\x1b[49m\x1b[39m`：数据对象已结束，但颜色复位字符使严格`json.loads`报告Extra data。`vcs_workset.py`是放在包外的独立入口，先核验原版校验库和svaext启动器固定SHA及完整包，再加载包内原始解析器。它只在内存中去除结构化JSON边界的SGR显示颜色；JSON内部控制字符、未知转义、任意额外文本、第二个JSON仍拒绝，原始日志、XML、状态、manifest、RTL和固件均不改。

先激活相同Python/编译器隔离环境，取得本目录的vcs_workset.py（存放在包外），然后执行：

```bash
"$tcm_python" -B /已下载的脚本路径/vcs_workset.py \
  --package /home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1 \
  accept --run-dir /data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_runtime/runs/t12_r0.6xf7vakp
```

accept只接受该包runtime/runs内的T12/等待0运行，检查原始退出码0、无超时、原始命令与模型路径、运行环境/包快照、成功构建记录及模型哈希、XML恰好1个无失败/跳过测试，以及全部6条严格算术完成/流量/重复性记录、实际ELF/布局与向量身份。只有全部通过，才独占创建缺失的result.json，记录原始文件哈希、原始墙钟耗时、验收脚本哈希和显示规范化策略；已有result.json则拒绝覆盖。输出`[TCM_VCS_ACCEPT_PASS] simulation_rerun=false raw_files_unchanged=true`才代表这次补充验收成功，不伪造一次新的仿真。

首版包外验收（23afde9）在真实服务器误报`logged ELF/layout/vectors do not match this package`。原因已在本地重现：官方inspect_elf返回list[tuple[int,int]]，JSON加载段为list[list[int]]，旧测试用列表未覆盖真实类型。修正版只把预期加载段的元组转换为列表再比较，地址、长度、入口、符号、ELF及向量哈希仍严格相等；错误时输出具体不匹配字段。该停止点在创建result.json之前，不需要删除文件或重新仿真。下载修正版到包外新目录重试即可，保留旧脚本和原始证据。

此后通过同一包外入口的`run --tiles 384 --delay 0`等命令启动后续测试（仍使用同样编译器隔离设置），而不是直接调用旧包runtime.py。入口复用原有模型和大工作集前置小用例判据，能读取已验收的原始彩色日志；编译选项、RTL、固件和测试语义不变。未来子进程强制`COCOTB_ANSI_OUTPUT=0`及`NO_COLOR=1`，防止同类显示问题再次阻断汇总。两变量意义见[cocotb2.0日志颜色文档](https://docs.cocotb.org/en/v2.0.0/library_reference.html#log-coloring)。新导出的2/4MiB包也可直接使用这个包外入口的check/build/run，无需再次生成RTL。

## Ubuntu先导出1MiB配置

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
if [ -n "$(git status --porcelain)" ]; then
    git status --short
    echo '存在未提交修改，停止，不覆盖。'
    exit 1
fi
git pull --ff-only origin main
bash verification/google_tcm_vcs/export.sh 1024
)
```

只构建该容量的原始SV/ZIP/参数头和同一固件ELF；**不构建Verilator模型、不启动长仿真**。导出前后验证现有三阶段manifest及工具指纹。仅当SV SHA与对应容量的完整控制组PASS产物记录一致、ELF SHA与某份完整T12工作集PASS日志一致时才输出包；不一致会停止，不提供跳过检查的选项。

不要与仍在运行的长仿真并行启动导出。脚本使用`--noblock_for_lock`；若同一Bazel服务器忙，会立即停止并保留日志，不排队等待数小时，也不自动终止正在运行的测试。

成功后输出`[TCM_VCS_PACKAGE_ARCHIVE]`和`[TCM_VCS_PACKAGE_SHA256]`。运行目录为`$HOME/coral_tcm_capacity_8e4_v1/vcs_export_d1024.XXXXXX/`，内含包目录、tar.gz及外部sha256校验文件。不猜测随机后缀；上传时使用实际输出路径。

将tar.gz及其.sha256文件传到服务器的个人目录，先`sha256sum -c`，再解包。不要复制Ubuntu的simv、Verilator可执行文件、Bazel缓存或整个Conda环境。服务器步骤见[随包说明](PACKAGE-README.md)：先准备兼容Python3.11，安装固定依赖，verify/check，再build和T12小工作集。VCS许可仍使用实验室原配置，无需Docker或管理员权限，但依赖兼容性/许可可用性必须实测。

1MiB流程跑通后，用相同导出脚本分别传2048、4096，形成三套固定、独立、可追溯的RTL/服务器simv。改变容量需换包；相同包下换T或外部读等待不重新生成硬件。

## 本地验证范围

补充真实ELF元组/JSON列表表示回归后：VCS包/升级/验收入口40项检查通过（含真实cocotb2.0公共API和固定fixture导入检查、真实返回类型正例、各身份字段数值差异反例），原TCM实验64项检查通过。这些是本地工具检查，不替代服务器实际验收。

检查包括ZIP路径安全、参数/宏、完整原始字节、来源证据、篡改拒绝、路径适配器、VCS命令参数/原程序复用、XML拒绝失败、模型指纹和超时处理。真实VCS2020与glibc2.17环境无法在Windows工作区验证，必须由用户在实验室运行小用例确认。此时仍是VCS+cocotb，Python逐周期开销未消除，也不承诺速度优于Verilator。

额外依赖：原始Sram.v在VCS下依赖C++17的`sram_backdoor.cc`；一并按固定Git提交原样导出。服务器使用个人环境的C++17编译器及VCS自带svdpi.h单独编译DPI SO，静态链接该SO的C++运行库；VCS自身默认继续使用/bin/gcc、/bin/g++。包内有精确依赖版本、兼容glibc2.17的历史Miniforge指引、环境检查与DPI C-ABI字节掩码自检入口。不替换系统glibc或全局修改LD_LIBRARY_PATH，也不拿Verilator的svdpi.h给VCS用。

API依据：[cocotb2.0 runner](https://docs.cocotb.org/en/v2.0.0/library_reference.html#python-test-runner)、[VCS支持](https://docs.cocotb.org/en/v2.0.0/simulator_support.html#synopsys-vcs)。没有照搬官方面向网表的零初始化/禁时序检查/FSDB选项，也没有为“跑通”而改SRAM或加SYNTHESIS。
