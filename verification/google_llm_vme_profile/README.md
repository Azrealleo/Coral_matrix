# VME分段诊断（独立候选，不覆盖v2性能结果）

固定ITCM256KiB/DTCM512KiB、原输入/4种形状、同一已验证RTL。先只测case3：M16/K64/N64。
当前仅工具准备；尚无本诊断正式ELF/RTL结果。不是算子优化版，不是完整模型或纯阵列峰值测试。

## 计时口径

同ELF保留RVV、未插桩VME完整调用和未插桩VME权重复用，另加权重复用的分段探针路径。
四路径各4次、轮换先后顺序，全部输出逐元素INT64检查，host前门再次回读输出/权重/输入/工作区/guard。
分段探针只加在新复制的profile_tile.h；原HardwareTile、旧v2候选和已导出包不修改。

五阶段为input_pack、accumulator_init、load_config_issue、readback_and_possible_completion_wait、output_layout。
权重预打包仍单独实测一次，不属于这五段复用调用。
input_pack每次调用1段，其他阶段每个输出通道tile1段；case3为4段，按阶段累计。
累加器初始化含行填充/配置/搬运；load_config_issue含K循环配置、操作数加载、矩阵发射与软件命令计数。
readback含读回配置和16行完整读回，可能承担尚未完成矩阵操作的等待。

**探针的fence rw,rw不等价于矩阵退休屏障。** 读mcycle及寄存器压力会改变流水/调度/代码布局，阶段比例仅属于插桩调用。
同时报告未插桩reuse、插桩whole、两者原始差值和whole减五段之和的unassigned部分。
unassigned还包含函数/循环/指针计算及统计开销，不能全称为探针成本；不把差值扣回旧v2来伪造分段。
所有周期保留原值，不扣空边界。基线本ELF允许与旧v2不同，不强求逐周期相等，不用旧v2周期除以新插桩周期冒充速度比。

## VM只构建、审计并导出

缓存正常预计数分钟级，以下不运行RTL：

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_llm_vme_profile/build_export.sh
)
```

独立源包tests/cocotb/llm_vme_profile_v1，固件包coral_llm_vme_profile_i256_d512_v1。
回传LLM_VME_PROFILE_ELF_AUDIT、PACKET_ARCHIVE、PACKET_SHA256、PACKET_BYTES，再安排服务器传输和运行。
VM阶段native测试不是RTL。正常退出复用官方CRT：main返回0后mpause；失败返回非零仍触发fault，验收不放宽。

## 服务器（实际包路径待导出）

沿用原Pool包、编译模型及probe.46bl5uqr，只读校验，不编译/改标签/改RTL。
环境coral-verilator，unset WAVES GUI COCOTB_ENABLE_PROFILING，CC/CXX用该Conda。
从新包运行server.py --packet "$PWD" --rtl-package "$tcm_rtl" check --probe-run "$tcm_probe"，
随后run --probe-run "$tcm_probe" --case 3；默认也为3，不自动跑其他例。
首次case3粗估20～40分钟，不含VM构建。5400秒及1000万周期是上限，不是ETA。
需同时有LLM_VME_PROFILE_BREAKDOWN与LLM_VME_PROFILE_RTL_PASS，原log/XML/退出状态/源身份保留。
中断重跑只建立新结果目录，不是CPU checkpoint，不删除旧结果。
