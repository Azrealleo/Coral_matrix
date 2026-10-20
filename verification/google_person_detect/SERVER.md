# 服务器单图入口：先短窗口，后完整推理

2026-10-20。VM已实际生成ITCM256KiB / DTCM512KiB的RTL，用户回传构建34.698秒、原ELF/模型字节校验通过。导出目录：

`/home/lqq/coral_tcm_capacity_8e4_v1/person_rtl_export.r9bhUw`

归档`coral_person_i256_d512.tar.gz` SHA256：

`a83bd98bd92157163223b75d74a25e5f426a59937354fb3784d830be4f130726`

**服务器传输/校验和Verilator新模型编译已实际通过，20万周期观察已完成但不是完整推理。** 状态1、无fault、arena_used=0、输出仍为哨兵，详见第5节；完整模型推理尚未通过。新配置不能沿用旧ITCM8KiB的仿真资格。

## 1. VM传包（不是Windows终端）

```bash
(
set -eo pipefail
cd "$HOME/coral_tcm_capacity_8e4_v1/person_rtl_export.r9bhUw"
sha256sum -c coral_person_i256_d512.tar.gz.sha256
ssh -p 22 lqq@172.27.127.152 \
  'mkdir -p /home2/lqq/Desktop/coral_person_packages && test ! -e /home2/lqq/Desktop/coral_person_packages/coral_person_i256_d512.tar.gz'
scp -P 22 coral_person_i256_d512.tar.gz \
  lqq@172.27.127.152:/home2/lqq/Desktop/coral_person_packages/
)
```

需要服务器账号登录，首次主机密钥须核对。远端若已有同名归档则停止，不覆盖；先在服务器核验是否为上面的SHA。VM须能实际连接服务器；不可达时可经Windows中转，不把SSH端口改为RDP3390。

## 2. 服务器前台pilot（不需要Bazel）

先更新个人工具仓库，有未提交改动则停止；不修改团队仓库，不停止其他用户仿真：

```bash
(
set -eo pipefail
cd /home2/lqq/Desktop/Coral_matrix
if [ -n "$(git status --porcelain)" ]; then
    git status --short
    echo "存在未提交修改，未更新。"
    exit 1
fi
git pull --ff-only origin main
bash verification/google_person_detect/server_pilot.sh
)
```

只有git pull需要GitHub网络/代理；本地编译和运行不依赖代理。脚本选择现成`coral-verilator`环境及Conda gcc/g++，不使用VCS专用的系统GCC4.8设置，清除WAVES/GUI/profiling（不能把字符串0当关闭）。

脚本核验固定归档SHA，然后在旁边新建`person_pilot.XXXXXX`解包，包内不写文件。总日志`pilot-console.log`，模型和运行输出在包外的`coral_person_i256_d512_verilator_runtime/`。`_build.log`/`_test.log`及状态JSON保留失败原因；不删旧目录、不编辑manifest/hash。当前是前台运行，关闭终端可能中断，不是后台队列。

verify重查全部文件、原模型、原ELF资源及实际256/512KiB边界；check检查依赖版本、C++17和共享库。build只复用SHA固定的旧Verilator工具中的通用编译函数，**不复用旧模型或workset bench**：编译新顶层原单文件SV、原SRAM DPI、cocotb入口，C++17/-O3/-j2、不启波形。构建身份和可执行文件hash防止混用；脚本/包/环境变化要求重编。

首次构建时间需实测；build和smoke分别有1800秒墙钟上限，超时只终止本启动器创建的子进程组。

## 3. 观察窗口的含义与验收

- 沿用包内8e4前门fixture；地址ITCM0、DTCM0x01000000、CSR0x02000000。原fixture不改；只提供不解析Bazel路径的runfiles命名空间适配。
- 前门写256KiB ITCM的NOP、512KiB DTCM的A5，再加载同一原ELF；整个300568字节模型读回核SHA，有人图9216字节输入读回逐字一致，不再次减128。
- 启动CPU，2个settle周期后观察最多200000周期，等待自然halt、fault或预算到达。装载/读回与执行窗口墙钟分开记录；20万只是成本探针，不是预计整网周期。
- 结束后使用原CSR halt接口停止一次性实例，再读固件状态、arena、invoke周期、分数和栈底64字节canary；**不是可恢复checkpoint**，完整推理会重新初始化。
- 状态0=仍在CRT/未到main，1=准备/分配，2=Invoke进行中，3=Invoke完成。101~105、fault、读回不一致、arena越界、canary变化或过早自然halt均失败。

窗口到达但未完成时标记`PERSON_SMOKE_OBSERVED_NOT_INFERENCE`。即使cocotb测试本身PASS也不能说整网跑通；status0更不证明CPU已有有效进展，需后续诊断/增加预算。栈底canary完好不是完整水位或无任何溢出的证明。

只有**自然halt + status3 + 实际arena合理 + invoke周期>0 + 两个INT8输出精确匹配原生主机参考**，才可标`PERSON_NPU_INFERENCE_PASS`。输出顺序[no_person,person]，有人图[-113,113]、无人图[57,-57]；不仅比较top1。窗口刚好看到status3但未自然halt时检查分数，仍不标完整推理通过。

仍为固定TFLM INT8基线，未接VME矩阵加速；1.25ns行为时钟不是物理频率资格，不从smoke线性外推完整模型耗时。

## 4. 回传与后续

回传`PERSON_VERILATOR_BUILD_PASS`、`PERSON_RTL_OBSERVATION`及最后标记。失败则回传启动器给出的`_build.log`或`_test.log`末尾，不先重新导出/换浮动依赖。

入口亦支持`person_runner.py --package <路径> infer --case person --cycles <预算> --timeout <秒>`，**当前先不启动**；根据pilot的阶段、异常及cycles/wall再定完整单图预算。完整图通过后才运行另一图、逐层核验及矩阵内核优化。

本地29项工具/合成检查通过（原22项、新7项），包括原模型字节的合成ELF审计、失败结果拒绝、环境清理和构建命令。bench Python及Bash语法已核对；没有在Windows编译/运行此RTL，也不提前记服务器通过。

## 5. 首次服务器pilot实际结果（2026-10-20）

用户回传：`/data/home2/lqq/Desktop/coral_person_packages/person_pilot.dJfrJn`。

- verify/check通过，原包不变；Python3.11、Verilator5.052、Conda gcc/g++，依赖版本与旧验证环境相符。
- 新模型`builds/a5d0fd5aca9a.g9pa3q0w`编译439.989秒。不是旧TCM模型复用。
- `runs/smoke_person.8xymkq4w`观察200000周期，执行窗口67.977322秒、前门装载/模型及输入读回17.818258秒，整个测试87.178秒。
- 原模型和输入前门读回一致，栈底64字节canary未变，未观察到fault；`firmware_status=1`、`arena_used_bytes=0`、`invoke_cycles=0`、`natural_halt=false`。
- 输出[37,53]仍是初始化哨兵，不是分类结果。状态1证明已到main的准备/分配阶段，尚未记录AllocateTensors完成，不能仅凭无fault排除卡住。
- ELF SHA：`e3078c156fd03315be2796c95044558cc3722854c077d6d8702100c18dd2b877`；有人图输入SHA：`d4ebdafe351a7b7851c3d087fb7ec798c739badcd7e248dcb81fa92dd572aaed`。

下一步不运行会新解包/重编的`server_pilot.sh`，也不改runner/bench；直接复用同一包和已编模型，重新初始化后观察2000000周期。不是在旧停止点继续。按本次窗口速度只作运行预算，粗约12分钟，非完成整网的承诺。若仍状态1，进一步定位准备/分配流程，不无上限增加预算或宣称硬件错误。

```bash
(
set -eo pipefail
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-verilator
unset WAVES GUI COCOTB_ENABLE_PROFILING
export CC="$CONDA_PREFIX/bin/gcc"
export CXX="$CONDA_PREFIX/bin/g++"
cd /home2/lqq/Desktop/Coral_matrix
pd_package=/data/home2/lqq/Desktop/coral_person_packages/person_pilot.dJfrJn/coral_person_i256_d512
"$CONDA_PREFIX/bin/python" -B verification/google_person_detect/person_runner.py \
  --package "$pd_package" smoke --case person --cycles 2000000 --timeout 1800
)
```

若构建身份不匹配，先回传错误，不删除状态/修改hash或自动重编。这一轮仅文档更新，未修改模型身份相关脚本。

## 6. 200万周期结果：转入诊断

用户随后回传`runs/smoke_person.ttnd8y5g`：2000000周期执行698.728060秒，总718.555秒，仍status1、arena_used/invoke均0、[37,53]哨兵、未自然halt；模型/输入读回、栈底检查通过且无fault。不再增加窗口，下一步改为[同模型DM暂停/PC诊断](DIAGNOSTIC.md)。旧runner/bench/RTL/固件不修改，不触发重编；实际原因仍待现场采样，不直接归因RAM大小或RTL错误。
