# 未优化算子第一步：RVV AveragePool 独立候选

2026-10-21。用户要求 Depthwise 暂时不要改动、使用官方实现，先处理没有现成优化的其他算子。本轮只新增 AveragePool 优化；不修改 Depthwise 源码，也不切换它的注册方式。当前仍是此前v1固件采用的官方默认 `tflite::Register_DEPTHWISE_CONV_2D_INT8()`，**不是宣称已启用官方RVV Depthwise**。

## 实际模型与优先级

固定原模型只有一个 AveragePool：`[1,3,3,256] -> [1,1,1,256]`，3×3、stride2、VALID、无融合激活。输入/输出 scale 都是0.01860933005809784、zero_point 都是-128。源码检查表明当前默认实现按通道反复计算窗口边界及循环相加，可沿连续NHWC通道向量化。

Softmax只有2个输出，Reshape只处理2个INT8元素，因此本轮不重写它们，也不声称改一个Pool就会让整网显著加速。卷积/Depthwise及量化初始化仍可能是主要开销，需周期实测。

| 部分 | 此候选处理 |
|---|---|
| 14个1×1 Conv | 原VME v1源码逐字保留 |
| 14个Depthwise | 官方默认注册不变，不新增自定义实现 |
| 1个AveragePool | 新增显式RVV候选 |
| Reshape / Softmax | 默认实现不变 |
| 模型、权重、RTL、RAM配置 | 不变，ITCM256KiB / DTCM512KiB |

## AveragePool 做了什么

- 窗口边界与有效样本数每个空间输出只计算一次，而不是每个通道重复。
- RVV沿通道连续加载INT8，符号扩展并用INT32向量累加；支持通道尾块，排除窗口外padding样本。
- 使用真实有符号整数向量除法 `vdiv.vx`，精确保留固定TFLM的正负数舍入：正和加count/2、非正和减count/2，再向零截断除法；不改为浮点近似、右移或ties-to-even。
- 按原激活上下界截断；沿用官方PoolingPrepare检查量化参数。输入/输出量化一致时不额外减zero_point，保持原参考内核语义。
- 累加数据只在向量寄存器中，无完整输出大小的INT32缓冲，无每次Invoke动态堆分配。校验版另外在arena申请输出INT8字节数的可复用scratch，本模型为256字节。
- 不支持的类型/几何显式回退并记录计数；固定模型固件要求pool_calls=1、fallbacks=0、vector_blocks>0、mismatches=0，校验版还要求validated=1，才允许完成。

`pool_core.h`共享窗口调度和独立标量模拟；`pool_rvv.h`是真实RVV backend，不把主机模拟计数当硬件向量执行。校验版执行原TFLM AveragePool并逐字节比较；测速版不重复reference计算，二者ELF和身份分开。

## 已实际完成的本地检查

- MinGW GCC6.2严格编译执行：2160组窗口/步长/SAME与VALID/批次/通道尾块/激活范围，比较1291923个输出元素；count1..49全部可能INT8求和范围的舍入测试通过，含负数和半整数边界、溢出/空窗口拒绝、输出guard。
- 本地玄铁GCC14.3、`rv32imf_zve32f_zicsr/ilp32`真实编译 `pool_compile_test.cc`；反汇编确认 `vle8.v`、`vsext.vf4`、`vadd`、`vmerge`、`vdiv.vx`、`vmax/vmin`、`vse8.v`。这是目标文件编译，不是固定官方工具链完整链接或RVV硬件执行。
- 7项新增工具测试通过：Depthwise/Softmax注册保持、父候选不覆盖、硬件/主机模式区分、模式化符号审计、路径限制等；原VME工具18项与默认路径34项回归亦全部通过。新脚本语法检查通过。
- 用实际原模型与样本生成17份候选文件，模型源码与父候选逐字相同。

**尚未执行**：固定TFLM参考的2160组原生测试、完整原模型两图的Pool+VME逐层比对、新候选完整交叉链接/资源审计、真实RVV硬件与整网性能。主机模拟不能证明RVV指令数值/硬件行为。

## Ubuntu VM 下一步

新目录为 `tests/cocotb/person_detect_vme_pool_v1`，单独manifest；原 `person_detect_vme_v1` 和已导出的 `coral_person_vme_i256_d512_v1` 包不改。旧默认版/短VME probe可在服务器继续运行，本轮不操作它们。

待VM当前其他Bazel任务结束后执行；锁忙即退出，不杀进程：

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_person_pool/build.sh
)
```

脚本先用固定TFLM参考池化核做native差分，再跑原两张图片：14个Conv加1个Pool每图逐字节比较，共30层，最终输出仍须有人[-113,113]、无人[57,-57]。主机部分以C++模拟VME和RVV，不是硬件。

之后交叉编译validate/fast两份真实VME+RVV固件，审计原始模型、256/512KiB段界及两组计数器符号。结果在新的 `person_pool_v1.*`。成功标记 `[PERSON_POOL_HOST_AND_LINK_PASS] ... NPU_RTL=NOT_RUN`。

请先回传主机与资源日志，再制作对应的新硬件验证包；不要将新ELF替换进旧不可变包。当前没有测得池化或整网加速倍数。

固定来源：NPU `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`；TFLM `b75c6ff4e2270047f2b48fa01f833c8101c31f43`。舍入依据该版本 `tensorflow/lite/kernels/internal/reference/integer_ops/pooling.h`；注册与量化检查依据 `micro/kernels/pooling.cc` / `pooling_common.cc`。
