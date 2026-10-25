# 高精度 RVV GELU 候选：RTL 已验收结果

验收日期：2026-10-25。官方 Coral `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，
单 NPU，ITCM 256 KiB / DTCM 512 KiB。候选是项目独立 RVV 移植，采用
[ONNX Runtime MLAS 的高阶 tanh 方案](https://github.com/microsoft/onnxruntime/blob/5c1b7ccbff7e5141c1da7a9d963d660e5741c319/onnxruntime/core/mlas/lib/tanh.cpp)，
保持官方内核、旧包、RTL 和 ISA 不变。MIT 许可见 LICENSE-MLAS.txt。

## 同一 ELF 的真实 RTL 结果

| 用例 | 标量周期 | 原项目 RVV 周期 | 新候选周期 | 原项目 RVV / 新候选 | 最大绝对数学误差 | 严格精度 |
|---|---:|---:|---:|---:|---:|---|
| gelu32 | 11265 | 11178 | 434 | 25.7558 | 8.19564e-8 | PASS |
| gelu_tail37 | 13421 | 13338 | 571 | 23.3590 | 1.19209e-7 | PASS |
| gelu256 | 90304 | 89559 | 2828 | 31.6687 | 2.38419e-7 | PASS |

数学参考仍为 tanh 形式 GELU 乘以 Up，不是 erf 形式。精度门限原样保留：
`atol=2e-5, rtol=2e-4`。每条路径测首次和三次稳态，四次周期均相同，
所有样本严格数学检查通过。表中为原始 mcycle，未扣除 3 周期空边界。
另有真实候选单元素零输入探针通过；它只用于启动、签名和边界检查。

比较基线是同一 ELF 中的原项目 RVV 路径，该路径的 tanh 仍调用标量 libm。
因此本表不是相对任意 RVV 库的收益，也不是与旧低精度官方 GELU 的等精度对比。
数据驻留 TCM，完整模型、数据集准确率、DRAM 搬运与 VME 均未在本候选中测试。

主机数值镜像另验证 81925 点：x 在 [-8,8]、步长 1/1024，
Up 为 {-2,-1,0,1,2}。最大绝对误差 1.90734863e-6，最大容差占比
0.0637865294。该有界检查不执行 RVV，也不证明任意 FP32、NaN 或 Inf 语义。

## 复核证据

虚拟机独立作业目录：
`/home/lqq/coral_tcm_capacity_8e4_v1/gelu_rvv_mlas_v2.4yHOrK`。

其 `prepared/` 下的原始验收目录：

- `runs/probe.wukje328`
- `runs/case0.zybppj9v`
- `runs/case1.07uc_qig`
- `runs/case2.qfb7re71`
- `summary.g0elal4z/summary.json`

完整汇总已重新验证三例的原始日志、XML、退出状态、输入读回、调用计数、
边界保护、故障/自然停止及工具/源码/ELF/RTL/模型哈希。低地址栈保护仅覆盖
64 字节，不代表完整栈高水位证明。

| 对象 | SHA256 |
|---|---|
| ELF | `0a9d427597056b709cb7362eaac7eae6be29ae8b996419c9f09b8402987b7d47` |
| RTL | `477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2` |
| 复用的模型二进制 | `827680a52a5d3107cfaa3d123af533b9e9d208acf1b44d23a880833bbb09de6c` |
| 完整 summary.json | `2ac3b813ef1fb76dd209bc4f54e7baadb15618ea15b90fb74112680185865567` |
| 固件导出包 | `79cefb956002469a4e7e609f656d22f6d94ae6f8f34e5b76d27c76814c05e769` |

固件包位于 `prepared/firmware/coral_gelu_rvv_mlas_i256_d512_v1.tar.gz`。
文件名与包信封 schema 保留 v1，里面冻结的源码/工具包为 v2；两者版本维度不同。

继承的原始 observation 使用 `official_*` 作为兼容字段，本候选中代表新候选。
继承的 Markdown 汇总仍有 `Project/official` 列名；其含义是原项目/新候选。
应以 comparison JSON 中的 `candidate_cycles`、`steady_project_over_candidate`
及独立 scope 为准。原始输出没有事后改写。

三例命令耗时分别约 37.98、44.75、156.23 秒，包含 Bazel 开销；
执行阶段分别约 31.88、38.79、150.00 秒。首次模型准备约 537 秒，另计。
这些时间是本次虚拟机的观测，不是 NPU 加速比。

## 审计与回归

v1 编译成功后，审计错误要求未调用的旧 GELU 符号保留；链接器
gc-sections 移除了它，导致审计失败。失败目录 `gelu_rvv_mlas.P63L2x`
及其工具/源码/日志均保留。v2 在新目录中要求实际调用的候选函数存在，
并含向量运算与 FP32 向量除法；不改变候选算术或数学门限。

本地六项候选检查、虚拟机两项 native host 测试全部通过。
包含真实 RV32 编译/反汇编、gc-sections 链接、移除 vfdiv 必须被拒绝、
冻结来源/输入不变、主机数值扫描、严格精度失败不可降级验收等检查。
原官方 RVV 六例旧证据也重新验收通过，无需重跑或改写旧日志。

## 继续使用

新建准备目录（构建与导出，不启动 RTL 仿真）：

```bash
bash verification/google_gelu_rvv_mlas/run.sh
```

重新验收已有证据并生成新汇总（不重跑仿真、不覆盖原始输出）：

```bash
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
python -B "$HOME/coral_tcm_capacity_8e4_v1/gelu_rvv_mlas_v2.4yHOrK/tools/verification/google_gelu_rvv_mlas_v2/summarize.py" \
  --vm-prepared "$HOME/coral_tcm_capacity_8e4_v1/gelu_rvv_mlas_v2.4yHOrK/prepared"
```

下一步可以组合已验收的 RMSNorm、Residual 与此 GELU 候选，测试小型
Transformer 子模块的正确性和周期；当前结果尚不构成完整 LLM 验证。
