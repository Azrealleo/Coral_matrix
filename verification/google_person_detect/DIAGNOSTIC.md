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
