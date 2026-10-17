# 官方单NPU：Ubuntu导出，CentOS7独立VCS运行

当前状态：独立包工具已实现，**Ubuntu实际导出和服务器VCS编译/仿真尚未执行**。本地新入口26项静态/合成/依赖API检查通过（其中2项使用真实cocotb2.0和固定官方fixture），不把它们当实际RTL PASS。保持旧的Bazel/Verilator实验副本、manifest、程序和结果，不修改团队仓库。

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

检查包括ZIP路径安全、参数/宏、完整原始字节、来源证据、篡改拒绝、路径适配器、VCS命令参数/原程序复用、XML拒绝失败、模型指纹和超时处理。真实VCS2020与glibc2.17环境无法在Windows工作区验证，必须由用户在实验室运行小用例确认。此时仍是VCS+cocotb，Python逐周期开销未消除，也不承诺速度优于Verilator。

额外依赖：原始Sram.v在VCS下依赖C++17的`sram_backdoor.cc`；一并按固定Git提交原样导出。服务器使用个人环境的C++17编译器及VCS自带svdpi.h单独编译DPI SO，静态链接该SO的C++运行库；VCS自身默认继续使用/bin/gcc、/bin/g++。包内有精确依赖版本、兼容glibc2.17的历史Miniforge指引、环境检查与DPI C-ABI字节掩码自检入口。不替换系统glibc或全局修改LD_LIBRARY_PATH，也不拿Verilator的svdpi.h给VCS用。

API依据：[cocotb2.0 runner](https://docs.cocotb.org/en/v2.0.0/library_reference.html#python-test-runner)、[VCS支持](https://docs.cocotb.org/en/v2.0.0/simulator_support.html#synopsys-vcs)。没有照搬官方面向网表的零初始化/禁时序检查/FSDB选项，也没有为“跑通”而改SRAM或加SYNTHESIS。
