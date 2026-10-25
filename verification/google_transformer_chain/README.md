# FP32 算子链组合验证

固定官方 Coral `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，单 NPU，
ITCM 256 KiB / DTCM 512 KiB。冻结父版本 `6193f5a4ce223d752cff846f62985ac78ee68b54`。

本实验是合成的 `RMSNorm → tanh-GELU×Up → Residual` 算子链，
不是标准完整 Transformer Block：没有 QKV、Attention、FFN 的矩阵投影、
模型权重或 token 生成，也不测 DRAM 搬运。输入已驻留 TCM。

数学定义（每行归一化，gamma 在行间共享）：

```
norm = gate / sqrt(mean(gate²) + 1e-5) * (1 + gamma)
activation = 0.5 * norm * (1 + tanh(sqrt(2/pi)*(norm + 0.044715*norm³))) * up
output = activation + residual
```

`1+gamma` 是这里采用的官方 Gemma RMSNorm 约定。
独立 Python FP64 参考在每阶段末显式取 FP32，保留真实张量存储边界。
规范化、激活、最终输出均读回并检查，两个阶段分隔保护区逐位校验。
主机以标量镜像验证接线；真实 RVV 结论必须来自 RTL。

同一新 ELF 的三条路径依次调用各自的三个算子：

- scalar：原项目标量实现。
- project：原项目 RVV 实现，tanh 仍为标量 libm。
- candidate：未修改的官方 RVV RMSNorm、已验收的高精度 RVV GELU 独立移植、
  未修改的官方 RVV Residual。没有声称实现跨算子融合。

三个性能用例：1×32、1×37、4×64；零输入 1×1 是启动安全探针。
每条路径四次调用，轮换测量顺序；总链原始 mcycle 包括调用、阶段切换及中间存储，
不扣空边界。输入装载、输出检查在计时外。
严格精度保持 `atol=2e-5, rtol=2e-4`，任何阶段失败均拒绝验收。

只新增源码包；旧源码、RTL、旧工具和日志均不修改。
MIT 派生 GELU 的许可和来源随父工具一并导出。
兼容 observation 的 `official_*` 槽位代表组合 candidate，公开 comparison 与汇总
使用 candidate；不能把本次链周期与旧单算子周期直接拼接比较。

准备（不启动 RTL 仿真）：`bash verification/google_transformer_chain/run.sh`。
仿真：`bash verification/google_transformer_chain/resume.sh JOB quick`。
`quick` 为安全探针和 1×32；也支持 `probe|0|1|2|all`。
粗估 quick 1–5 分钟；三例合计约 4–12 分钟，另计首次构建，需实测校准。
脚本会复核冻结工具身份和原始结果，不自动更新全局进度或交接文档。

当前工具/源码包版本 v2。v1 的主机测试及真实交叉编译均已通过，
但汇总检查器中的日志标记未同步更名，准备阶段拒绝验收，尚未运行 RTL。
v1 目录和日志保留；v2 在新目录修正日志标记的一致性，算术和精度门限不变。
