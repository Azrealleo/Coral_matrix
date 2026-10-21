# 单NPU：先测LLM算子，不加载完整模型

**明日统一入口：** [TOMORROW.md](TOMORROW.md)。已新增独立FP32算子准备套件与21例串行运行/汇总/续测工具，默认仍未启动远程仿真。`run_all.sh --mode all` 会先验证主机参考、实际链接与资源，再执行4例INT8+17例FP32。新增算子并非全部官方优化实现；来源、混合标量exp/tanh、数值容差及未覆盖项见该说明。下方保留已实测INT8记录。

2026-10-22。第一轮只做Transformer线性层使用的INT8 GEMV/GEMM微基准。**用户已回传case0、case1真实RTL PASS**，首次及后三次周期均一致：

| 已通过用例 | M/K/N | 标量周期/调用 | 官方RVV周期/调用 | 标量/RVV |
|---|---|---:|---:|---:|
| decode_tiny | 1/32/32 | 10563 | 263 | 40.163498 |
| prefill_tiny | 16/32/32 | 168618 | 4110 | 41.026277 |

实际run分别为 `/home/lqq/coral_tcm_capacity_8e4_v1/llm_linear_c0.brMbDF` 和 `llm_linear_c1.Ye75FC`。空边界3周期均未扣除，不是整网/完整decode/prefill/VME性能。M增16倍时RVV周期增约15.63倍，基本线性；与官方matmul逐行调用gemv的实现一致，不能据此宣称跨token权重复用或架构极限。用户尚未回传实际ELF审计行和仿真wall time，不补造哈希或耗时。下一步复用模型，分别测试case2/3的K64/N64。

后续再逐项加入RMSNorm、因果Attention/Softmax与其他激活，不将现成无掩码Attention测试直接冒充自回归模型测试。

## 本轮实际比较

同一新ELF内：朴素C++标量矩阵乘，对固定官方 `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a` 的 `tests/cocotb/rvv/ml_ops/gemma_kernels/rvv_int8_matmul.cc`。后者源码逐字复制，不重写；官方matmul目前逐行调用其GEMV。因此这是两个具体软件实现的比较，不是RVV/VME架构峰值或最佳实现比较。VME、完整模型、tokenizer、KV cache均不在本轮。

| case | 用途/对应形状 | M | K | N | MAC/次 |
|---:|---|---:|---:|---:|---:|
| 0 | decode形状小试跑 | 1 | 32 | 32 | 1024 |
| 1 | prefill形状小批处理 | 16 | 32 | 32 | 16384 |
| 2 | decode稍大线性层 | 1 | 64 | 64 | 4096 |
| 3 | prefill稍大线性层 | 16 | 64 | 64 | 65536 |

M=1/16只是模拟decode/prefill中线性层的矩阵形状，不代表执行了完整decode/prefill过程。输入为固定seed137+case的合成INT8，权重[-127,127]、激活[-128,127]，遵守官方内核不允许两侧同时出现-128的限制。该条件明确记录，不能宣称任意INT8范围或任意尾尺寸均已覆盖。

## 配置及性能口径

- 单NPU，ITCM256KiB/DTCM512KiB，原实验地址映射与已核对CSR/浮点patch。新Bazel包 `tests/cocotb/llm_linear_v1` 独立生成相同配置，不改旧TCM、Person、VME、Pool或Conv包。
- 官方Gemma测试原runner使用1MiB/1MiB和另一顶层，本轮不直接使用该大内存runner；新小固件实际链接和RTL参数均需审核后才仿真。
- 两条路径使用完全相同的行主序输入和权重、raw INT32输出；没有完整量化算子的重定量化、激活、外存访问或模型框架开销。
- 源码-O2，关闭自动向量化和LTO，RVV显式汇编/内建指令保留。四次调用，首次单列，随后三次steady；交替先后顺序。fence+mcycle包围各自内核调用，空边界单列、不扣除；输入生成、输出重置/检查、host装载在时间窗外。
- 所有数据驻留DTCM，只测resident计算。不能据此给出外部AXI权重流式读取速度、tokens/s或完整LLM推理时间。
- 每次逐项比较标量与RVV，最终再用独立Python整数golden经AXI读回两份完整输出、实际输入/权重、越界guard和栈底64字节canary。必须自然halt、status3、0错误、4次真实RVV调用；超时/故障/错误输出不标PASS。栈底canary不是完整水位测量。

## Ubuntu VM前台只跑最小case0

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_llm_ops/run.sh 0
)
```

不下载语言模型，不需要PyTorch/Transformers，不使用VCS。脚本先native标量参考与独立Python核对（不是RVV执行），再链接新ELF、生成并核对256/512KiB参数，最后显式前台运行一个Verilator测试。没有后台任务或全部用例自动排队。Bazel进度刷屏已关闭，日志保存在 `$HOME/coral_tcm_capacity_8e4_v1/llm_linear_c0.*`。

首次需编译新的仿真模型，可能要几分钟或更久；这部分与实际测试运行时间分开。case0的2百万周期、5400秒测试超时仅为停止上限，不是预计耗时。尚无本轮实测，不能承诺具体完成时间。后续case1/2/3按需单独运行同脚本，复用同一个已编译模型，第一例通过后再启动。

成功必须同时有 `LLM_LINEAR_OBSERVATION`、Cocotb `TESTS=1 PASS=1 FAIL=0`、`LLM_LINEAR_SUMMARY`、最终 `LLM_LINEAR_PASS`。请回传ELF审计和SUMMARY。若Bazel或测试出错，保留整个run目录；不要改官方内核或关闭检查来获得PASS。

本地10项工具检查通过，包含实际native标量执行对独立Python四例签名、实际RV32 bench/官方RVV目标文件编译与反汇编，以及内存/参数/日志/错误结果拒绝测试；Bash语法通过。目标文件检查使用本地玄铁GCC14.3，不是VM官方完整链接，不代表实际RVV执行。

旧Conv11项、Pool19项、VME18项、默认Person34项工具回归均通过，合计82项；这些旧回归不算新LLM硬件验证。

case0/1已由用户回传真实VM流水PASS，case2/3仍待执行。后两例在同一Ubuntu环境分别运行 `bash verification/google_llm_ops/run.sh 2` 和 `bash verification/google_llm_ops/run.sh 3`；每次只执行所选case，失败即停止，不自动切换完整网络。完成后回传ELF审计与SUMMARY。最终出现的 `LLM_LINEAR_PREPARED ... RTL=NOT_RUN` 只是生成器重新核验源码的标记，并非否定前面的RTL测试；真实运行结论以同一run的Cocotb结果、SUMMARY与LLM_LINEAR_PASS为准。
