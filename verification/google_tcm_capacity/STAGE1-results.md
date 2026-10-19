# 阶段1：单 NPU DTCM 容量检查结果

依据用户回传的 Ubuntu Verilator/cocotb 运行摘要整理。原始完整日志仍在 Ubuntu，下表不是完整测试报告，也不是性能或综合报告。

固定官方源码 `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`、团队生成补丁及 ITCM=8KiB；单次只有一个 NPU。实验地址图 DTCM=`0x01000000`、CSR=`0x02000000`，不是团队现有 SoC 地址图。

| DTCM | 8KiB bank数 | 16字节检查位置数（含ITCM首尾） | 掩码用例 | 回传结果 | Ubuntu结果目录 |
| --- | ---: | ---: | ---: | --- | --- |
| 32KiB | 4 | 14 | 2 | PASS | `/home/lqq/coral_tcm_capacity_8e4_v1/run_d32.SjP1zX` |
| 128KiB | 16 | 50 | 2 | PASS | `/home/lqq/coral_tcm_capacity_8e4_v1/run_d128.pvtztE` |
| 512KiB | 64 | 194 | 2 | PASS | `/home/lqq/coral_tcm_capacity_8e4_v1/run_d512.4QMBOZ` |
| 1MiB | 128 | 386 | 2 | PASS | `/home/lqq/coral_tcm_capacity_8e4_v1/run_d1024.cKWONf` |
| 2MiB | 256 | 770 | 2 | PASS | `/home/lqq/coral_tcm_capacity_8e4_v1/run_d2048.i8qruA` |
| 4MiB | 512 | 1538 | 2 | PASS | `/home/lqq/coral_tcm_capacity_8e4_v1/run_d4096.ZCVfVI` |

每档均回传 cocotb 1/1 PASS、`[TCM_EXPERIMENT_VERIFIED]`、`[TCM_STAGE1_PASS]`。检查覆盖每个 DTCM bank 首/中/尾位置，全写后全读以检测地址镜像，并在首/末bank测试字节掩码。不是全地址、全数据模式穷举，不等同于 March/MBIST。

结论：六档实验配置的前门 AXI 容量抽样检查均通过。尚未据此证明 NPU 计算正确、扩容后速度提升、200MHz达标、真实 SRAM 宏兼容或 SoC 集成通过。

后续状态（2026-10-19）：六档[小计算控制](CONTROL-results.md)已完整PASS；Ubuntu1/2MiB T384已完整配对，见[工作集结果](WORKSET-results.md)。这些新证据不把本节几何抽样扩展成全地址/物理宏验证。ITCM扩容是独立变量且当前暂停，接手见[当前指南](../HANDOFF-current.md)。
