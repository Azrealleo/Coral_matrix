# 官方单NPU：Ubuntu导出，CentOS7独立VCS运行

当前状态：**1/2/4MiB均已实际导出并通过原RTL/固件字节一致性检查；1MiB已在服务器通过VCS编译（60.523秒），首次T12运行在结果JSON解析处停止，尚无完整VCS RUN_PASS**。2/4MiB尚未回传服务器编译/运行结果。1MiB还已在Ubuntu通过同T12的Verilator完整测试（292.4秒）。实际路径、包SHA256与状态见[导出记录](EXPORT-results.md)。保持旧的Bazel/Verilator实验副本、manifest、程序和结果，不修改团队仓库。

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

这是已通过编译的环境设置，不等于VCS测试已通过。目前T12结果显示`Extra data: line 1 column 1946 (char 1945)`，保留原始日志、XML和状态文件，待定位解析异常；不要编辑日志、放宽算术/流量判据或直接启动大工作集。新导出的2/4MiB包也不能因1MiB编译通过而跳过各自的小工作集验收。

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

补充svaext后的回归：VCS包/升级入口32项检查通过（含真实cocotb2.0公共API和固定fixture导入检查），原TCM实验64项检查通过。这些是本地工具检查，不是实际VCS编译或RTL仿真通过。

检查包括ZIP路径安全、参数/宏、完整原始字节、来源证据、篡改拒绝、路径适配器、VCS命令参数/原程序复用、XML拒绝失败、模型指纹和超时处理。真实VCS2020与glibc2.17环境无法在Windows工作区验证，必须由用户在实验室运行小用例确认。此时仍是VCS+cocotb，Python逐周期开销未消除，也不承诺速度优于Verilator。

额外依赖：原始Sram.v在VCS下依赖C++17的`sram_backdoor.cc`；一并按固定Git提交原样导出。服务器使用个人环境的C++17编译器及VCS自带svdpi.h单独编译DPI SO，静态链接该SO的C++运行库；VCS自身默认继续使用/bin/gcc、/bin/g++。包内有精确依赖版本、兼容glibc2.17的历史Miniforge指引、环境检查与DPI C-ABI字节掩码自检入口。不替换系统glibc或全局修改LD_LIBRARY_PATH，也不拿Verilator的svdpi.h给VCS用。

API依据：[cocotb2.0 runner](https://docs.cocotb.org/en/v2.0.0/library_reference.html#python-test-runner)、[VCS支持](https://docs.cocotb.org/en/v2.0.0/simulator_support.html#synopsys-vcs)。没有照搬官方面向网表的零初始化/禁时序检查/FSDB选项，也没有为“跑通”而改SRAM或加SYNTHESIS。
