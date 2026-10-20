# 状态1持续：同模型DM诊断，不重新编译

2026-10-20。服务器200万周期结果目录`runs/smoke_person.ttnd8y5g`；执行窗口698.728060秒，前门装载/读回18.492447秒，总718.555秒。无fault，模型/输入读回与栈底检查通过，但仍status1、arena_used=0、invoke_cycles=0、输出[37,53]哨兵、未自然halt。**没有模型推理PASS，也不能据此判断硬件错误或死循环。** 状态1覆盖GetModel/版本核对、算子注册、interpreter构造、AllocateTensors，不能说已经精确定位到AllocateTensors。

不继续盲目增加周期。上一版smoke在窗口结束后使用CSR halt/reset，然后进程退出，已经不能从旧进程找回运行现场。新诊断使用同一个原RTL/ELF/可执行模型重新初始化，改用官方DM暂停，在**复位之前**读DPC/GPR/异常CSR，再恢复采样。

## 服务器命令

```bash
(
set -eo pipefail
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-verilator
unset WAVES GUI COCOTB_ENABLE_PROFILING
export CC="$CONDA_PREFIX/bin/gcc"
export CXX="$CONDA_PREFIX/bin/g++"
cd /home2/lqq/Desktop/Coral_matrix
if [ -n "$(git status --porcelain)" ]; then
    git status --short
    echo "存在未提交修改，未更新。"
    exit 1
fi
git pull --ff-only origin main
pd_package=/data/home2/lqq/Desktop/coral_person_packages/person_pilot.dJfrJn/coral_person_i256_d512
"$CONDA_PREFIX/bin/python" -B verification/google_person_detect/diagnose_person.py \
  --package "$pd_package" --cycles 200000 --samples 3 --timeout 600
)
```

前台运行，粗按已测速度预留约2分钟（非保证），墙钟上限10分钟；不调用build，不重新下载/导出，不更新已有build指针/身份。原runner SHA `597dfe711e95ee9168be7c77b32a39c0ebc02a97444a6fe8fa5025210914593a`、原bench SHA `78d1ea52f7ac63597fd8b48fce33d7b5c1919dd8bd4814a4b3de129aaf6fdc76`必须不变，全部模型/包/环境身份仍精确匹配。失败先看错误，不删模型或手改hash。

## 收集什么

先按原路径前门初始化/加载/模型和输入读回；启动后20万周期，DM halt并等待DMSTATUS，读取DPC、DCSR、ra/sp/s0/a0~a7，尝试mepc/mcause/mtval/mtvec/mcycle/minstret。核心寄存器读取失败会停止；可选CSR若不支持则明确记录并清除abstractcs.cmderr，不伪造0值。调试操作有自己的周期上限，无CSR reset兜底掩盖现场。

把DPC映射到ELF `.symtab` 中包含该地址的真实函数范围，记录偏移；仅邻近符号明确标NOT_containment。返回地址ra-1、栈顶128字节中疑似代码指针只是调用位置候选，**不是DWARF栈回溯**。本地`c++filt`如存在，仅对显示名称解码，不改原符号/日志。

第一份快照后DM恢复，间隔4096周期再暂停；共最多3份。检测到硬件fault或自然halt则提前停止并保留现场。源码依据固定8e4的`tests/cocotb/core_mini_axi_debug.py`及包内原`core_mini_axi_interface.py`调试接口；此诊断尚未在服务器实际验证，不提前记DM成功。

这些样本用于区分初始化热点、软件等待/异常处理循环、内存/地址错误等。PC相同可能只是热点循环，PC变化也不保证最终能完成；需结合函数、ra/参数、minstret与状态变化。mcycle增加本身不证明指令退休，optional CSR不可用时必须保留不确定性。调试会扰动执行、额外增加周期，**不用于速度或原基准周期对照**。

## 输出/边界

回传3行`PERSON_DEBUG_SNAPSHOT`及`PERSON_DIAGNOSTIC_CAPTURED`；失败回传启动器给出的`diagnostic.log`末尾。结果单独放原状态目录的`diagnostics/pc.XXXXXX`，原包、模型、旧日志和旧build记录不变。

`CAPTURED`只表示收集完成，不表示模型/硬件正确。诊断fixture本身cocotb PASS也不得冒充INFERENCE_PASS；发现fault也可成功完成现场收集。新诊断5项本地软件契约检查，与既有29项合计34项通过；Python语法通过，没有本地RTL/DM执行。

## 首次实际DM快照：20万周期附近有程序进展

用户回传`diagnostics/pc.ts77oz3y`，3份快照及CAPTURED完成。DM cause均3（调试暂停），原固件/模型不变、采样前没有复位，无fault，mepc/mcause/mtval均0、全部可选CSR读取成功；status均1、arena_used/invoke均0。

| 样本 | DPC十进制 | 包含DPC的ELF函数 | minstret |
| --- | ---: | --- | ---: |
| 0 | 59212 | `tflite::AlignPointerUp` +12；ra落在`SingleArenaBufferAllocator::AllocateTemp` | 192834 |
| 1 | 37024 | `tflite::internal::InitializeTfLiteTensorFromFlatbuffer` +900 | 195037 |
| 2 | 49576 | `tflite::PopulateConvolutionQuantizationParams` +932 | 197809 |

退休指令增加2203、2772，当前函数/调用候选由临时张量分配转到卷积量化准备，证明这个短时间段CPU并非停止执行，且工作路径确属Invoke前准备。mcycle分别202402/209304/216206包含DM握手/额外执行，不能拿4096窗口直接算无干扰IPC或推理性能。

**这只解释20万附近，不证明200万乃至后续一定继续前进，也不排除稍晚错误/循环。** 仍无完整推理PASS。下一步复用相同诊断入口，将首个采样点改为2000000周期，保留3样本/4096间隔，timeout改1800秒；这是取此前停留点的PC，不是没有诊断信息地继续加预算。

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
"$CONDA_PREFIX/bin/python" -B verification/google_person_detect/diagnose_person.py \
  --package "$pd_package" --cycles 2000000 --samples 3 --timeout 1800
)
```

不用更新代码、不重编，预计粗约12分钟（按已测200万执行窗口预算，不保证）。回传PC/函数/退休数后再选择修复或长运行，不能提前把本次结果定性为“只是慢”。

## 200万实际DM结果：卷积量化准备的软件double热点

用户回传`diagnostics/pc.tyngamx6`，3样本CAPTURED；DPC89856/97220/89840分别落入`__divdf3`(+460)、`__fixdfdi`(+252)、`__divdf3`(+444)。调用者由ELF范围定位为`PopulateConvolutionQuantizationParams`或`QuantizeMultiplier`。minstret1509687→1513222→1516732，增加3535、3510；无fault，mepc/mcause/mtval=0，可选CSR均成功，仍status1/arena_used0/invoke0。

据此确认该采样段有真实指令进展，且正在执行量化准备的软件双精度运算；不能称为CPU停机，也不能用3个点当作时间占比剖析或证明后续必完成。s0/其他GPR变化只记录，不未经反汇编就认定为通道下标。

依据[GCC运行库说明](https://gcc.gnu.org/onlinedocs/gccint/Soft-float-library-routines.html)，`__divdf3`为double除法、`__fixdfdi`为double到整数的转换。固定TFLM [kernel_util.cc](https://github.com/tensorflow/tflite-micro/blob/b75c6ff4e2270047f2b48fa01f833c8101c31f43/tensorflow/lite/kernels/kernel_util.cc)逐通道用double计算input_scale*filter_scale/output_scale，再调用[QuantizeMultiplier](https://github.com/tensorflow/tflite-micro/blob/b75c6ff4e2270047f2b48fa01f833c8101c31f43/tensorflow/lite/kernels/internal/quantization_util.cc)生成整数参数。源码已通过固定原始URL只读核对。现有Coral目标编译配置有F/向量FP32而无D；不能把此现象概括为“整个NPU没有FPU”。INT8模型的准备阶段有double并不矛盾，尚未运行的卷积Invoke性能不能由这些初始化样本代表。

下一步不改变原模型/固件、不切换float精度或定义TFLITE_EMULATE_FLOAT、不增加RAM；先让原基线在1000万周期有界窗口运行，观察准备是否返回并进入Invoke（状态2），或是否提前自然halt且分数精确匹配。`arena_used`仅在AllocateTensors返回后赋值，因此当前0不是实际占用0或内存不足的证据。按已测窗口速度估算该预算约1小时，不是整网完成时间预测；设置7200秒墙钟上限，可能因执行阶段负载变化而不同。

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
  --package "$pd_package" smoke --case person --cycles 10000000 --timeout 7200
)
```

本轮仅文档更新，脚本/模型身份保持不变；不用重编，不再反复200万处暂停诊断。窗口未完成时仍NOT_INFERENCE，发生异常即停止分析；1000万窗口尚未执行/回传。

## 1000万回传后：完整有人图长运行预算

`smoke_person.bzrml3j3`已实际完成1000万窗口，status2/arena_used82300，无fault/栈底破坏，说明准备成功返回；还没有完整Invoke/分类输出。执行窗口3475.519607秒、总3495.779秒，不外推矩阵硬件性能。

现在不再取初始化快照。下面服务器命令用现有模型重新初始化并运行完整有人图（不是恢复旧进程），后台启动，最多2亿周期/24小时墙钟；跑满周期粗预算约19小时，并非预计一定要这么久，完成会自动提前停止。异常/超时为失败，不降级成观察PASS。没有改动运行代码，无需git pull或重编。

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
pd_job=$(mktemp -d "$HOME/coral_vcs_tools/person_full.XXXXXX")
nohup "$CONDA_PREFIX/bin/python" -B verification/google_person_detect/person_runner.py \
  --package "$pd_package" infer --case person --cycles 200000000 --timeout 86400 \
  > "$pd_job/console.log" 2>&1 < /dev/null &
pd_pid=$!
printf '%s\n' "$pd_pid" > "$pd_job/pid"
printf '[PERSON_FULL_PID] %s\n[PERSON_FULL_CONSOLE_LOG] %s\n' "$pd_pid" "$pd_job/console.log"
)
```

返回提示符表示后台启动，不是推理完成；只执行一次。启动器自身仍会校验现有模型身份和锁，失败在console.log，不自动重编。初期控制台只有run目录是正常的，详细阶段在该运行目录`_test.log`；不随意kill其他用户进程。服务器重启不在nohup保护范围。验收仍必须`PERSON_NPU_INFERENCE_PASS`及原生分数[-113,113]逐字匹配；有人图通过也不等于另一图或数据集准确率已通过。
