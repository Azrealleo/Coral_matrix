# 阶段2a结果：六档DTCM的小工作集控制组

根据用户回传的Ubuntu实际RTL仿真摘要整理。原始test.log、ELF、manifest和产物hash仍在Ubuntu运行目录；本记录不是原始完整日志的副本。用户随后回传六份完整日志比较成功：`[TCM_CONTROL_COMPARE_PASS] capacities=6`，结果为`/home/lqq/coral_tcm_capacity_8e4_v1/control_compare.L0Pxte.log`。该比较已在Ubuntu完成，包含ELF、符号地址、加载段、输入和重复结果一致性检查；Windows侧未直接读取原始完整日志。

## 共同条件

- 官方源码：`8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，保留团队两个生成补丁及实验统一地址图。
- 单NPU，ITCM=8KiB，RAM行为模型读一周期，Tk=4，signed INT8输入、INT32输出。
- 相同ELF SHA256：`8e2032348a4148ea22cf2b0c5010aad8bb0e148047c09099fc0f5f8535815ed8`。
- 数据全部驻留DTCM低32KiB。输入/输出保留数组总9344字节，不含CRT、状态、堆栈等；最大实际矩阵数据9216字节。
- 前门AXI预装载，ITCM尾部NOP填充；主机装载和结果读回不计入周期。计数严格遵循[控制组口径](CONTROL.md)，不是纯阵列延迟或模型端到端时间。

## 用户回传的结果

每档4个用例，每个用例重置后重复3次，各重复周期一致；每次逐项校验256个输出元素。合计72次内核运行、18432个输出元素检查。各档均回传cocotb 1/1 PASS、`[TCM_CONTROL_VERIFIED]`和`[TCM_CONTROL_PASS]`。

| DTCM | K16周期 | K64周期 | K256周期 | 边界值K16周期 | 状态 | Ubuntu运行目录 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 32KiB | 414 | 702 | 1854 | 414 | PASS | `/home/lqq/coral_tcm_capacity_8e4_v1/control_d32.BGTxTH` |
| 128KiB | 414 | 702 | 1854 | 414 | PASS | `/home/lqq/coral_tcm_capacity_8e4_v1/control_d128.T9iUm8` |
| 512KiB | 414 | 702 | 1854 | 414 | PASS | `/home/lqq/coral_tcm_capacity_8e4_v1/control_d512.yyvs0W` |
| 1MiB | 414 | 702 | 1854 | 414 | PASS | `/home/lqq/coral_tcm_capacity_8e4_v1/control_d1024.vW63qk` |
| 2MiB | 414 | 702 | 1854 | 414 | PASS | `/home/lqq/coral_tcm_capacity_8e4_v1/control_d2048.PnRRdz` |
| 4MiB | 414 | 702 | 1854 | 414 | PASS | `/home/lqq/coral_tcm_capacity_8e4_v1/control_d4096.mwDf6H` |

共同的逻辑输入+golden哈希如下，六档回传值一致：

| 用例 | vector_sha256 |
| --- | --- |
| signed_k16 | `e32898dc82f7a68eb461b8501d782c646c61e01ef607740971a0c9f5e4a27b4d` |
| signed_k64 | `08b71621f6d826048046a6c142aca5a70fcacef47d81ab37d8726090dc8a3911` |
| signed_k256 | `372548ee90ad7e069977a02d9a7c993f7516495b67f0fe57578da8f9f34ec6f9` |
| signed_edges_k16 | `dc8796a7433dea16e7f0bf5089be989425aecb49698da67296c7bdcafe1703a7` |

## 可以与不可以得出的结论

已观察到：在该固定小工作集及一周期RAM行为模型中，六档DTCM均计算正确，所测计数窗口周期完全相同。此控制组没有显示容量增大引入额外仿真周期。

不能据此得出：2/4MiB对真实模型无收益、所有高地址都已由NPU LSU正确访问、ITCM容量无影响、真实宏延迟不变、200MHz可达、功耗/面积相同、当前SoC可直接扩容，或已有整个模型的端到端性能结果。

## 六份完整日志复核命令（已在Ubuntu通过，可复查）

此步骤只读取已有日志，不重新编译、不启动仿真。将24条比较明细保存到新文件，终端只输出一次完成提示；若任何一份日志缺失、FAIL/遗漏/重复、输入golden不匹配、ELF或符号布局不同，命令停止并报错。

```bash
(
set -eo pipefail
cd "$HOME/桌面/Coral_matrix"
tcm_pair_root="$HOME/coral_tcm_capacity_8e4_v1"
tcm_pair_log=$(mktemp "$tcm_pair_root/control_compare.XXXXXX.log")
conda run -n coral-matrix python verification/google_tcm_capacity/prepare_control.py compare \
  --logs \
  "$tcm_pair_root/control_d32.BGTxTH/test.log" \
  "$tcm_pair_root/control_d128.T9iUm8/test.log" \
  "$tcm_pair_root/control_d512.yyvs0W/test.log" \
  "$tcm_pair_root/control_d1024.vW63qk/test.log" \
  "$tcm_pair_root/control_d2048.PnRRdz/test.log" \
  "$tcm_pair_root/control_d4096.mwDf6H/test.log" > "$tcm_pair_log"
printf '[TCM_CONTROL_COMPARE_PASS] capacities=6 result=%s\n' "$tcm_pair_log"
)
```

后续是跨容量阈值的大工作集实验，需显式改变数据驻留/分块搬运策略，记录NPU外部AXI事务和字节数，分别报告搬运、计算及端到端窗口，不能继续只用主机预装载的这个小控制组来判断容量收益。外部延迟/带宽应作为清楚标注的实验假设，不冒充团队SoC/DDR实测。新[固定调度权重驻留实验](WORKSET.md)已收到32/128KiB、T12、等待0的实际RTL PASS，见[工作集结果](WORKSET-results.md)；同一prefix策略跨容量少29.32%周期，完整日志比较器复核待执行，2/4MiB价值仍待更大工作集测试。
