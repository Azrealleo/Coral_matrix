# 已验收结果的只读复用成本分析

独立于正在运行的pair-v2源码、固件、工具清单和结果目录。
不启动Bazel/编译/仿真，不写入job，不更新全局进度或交接文档。

在M8完成后，使用同一conda环境运行：

```bash
python -B verification/google_llm_vme_analysis/analyze.py \
  --job "$HOME/coral_tcm_capacity_8e4_v1/llm_vme_pair.kudXJL"
```

一般数秒至数十秒（重新计算文件校验和），不是RTL仿真。
加`--json`输出结构化结果，不支持跳过验收或只导入复制的summary/控制台输出。
内部复用不可变工具快照的`collect_vm`，重新核对原始日志/XML/退出状态、
ELF、RTL模型、源码、计数和硬件探针。只纳入已有case-proof的完成测试；
probe单独通过不构成性能结果。

分别分析上一版单tile和新双tile路径，包含：

- 一次预打包加1/2/3/4次reuse的实际测量窗口求和；
- 与相同数量RVV调用相比的成本及倍率；
- 假设后续调用保持3个稳态样本的平均成本时，严格胜过RVV的复用次数范围；
- 最好/最差已见样本成本下的条件模型范围，**不是统计置信区间或未来保证**。

模型公式：`RVV(R)=r0+(R-1)*mean(rs)`，
`VME(R)=prepack+v0+(R-1)*mean(vs)`。
平局不算加速；如果稳态VME反而更慢，不会误报“复用足够多就一定胜出”。
如果只在少量调用获胜，也报告上限。大于4次的预测没有新增RTL测量依据。

`R`是共享一次权重预打包的调用次数，不是M/K/N。
不将`complete-reuse`当作预打包成本：两者来自不同计时窗口。
不推导未测尺寸、通用调度阈值、DRAM性能、完整模型或冷缓存启动加速。

本地测试（不跑RTL）：

```bash
python -B -m unittest discover -s verification/google_llm_vme_analysis -p test_analysis.py -v
```
