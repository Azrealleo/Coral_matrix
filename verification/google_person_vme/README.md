# Person Detection：独立 VME 优化候选 v1

2026-10-20。用户明确要求参考团队 SoC 的手工优化算子库。此前只做了库审查和默认 TFLM 基线，没有接入，这是执行遗漏。本目录开始实际实现，不把此前默认版改称优化版。

## 本版做了什么

- 保留预训练模型、两张原始样本、默认版固件、服务器正在运行的默认模型任务以及原 runner/bench，均不修改。
- 14 个 Conv2D 经实际模型盘点均为 1×1、步长1、INT8，输入通道最大256；替换这14层的卷积计算。支持16输出通道×16空间位置分块，以及 M/N/K 尾块。
- 参考团队固定提交 `fa4b83e43bb0b1d58b18eb5f4c31d98ee4054123` 的 `sw/models/h4-resnet8/npu.cc`：K×16 权重预打包、同权重块跨空间位置复用、Tk4 发射、tile 初始化/读回。编码依据官方固定版本的 `vme_test_utils.h`，衍生文件保留 Apache-2.0 来源说明。
- VME 指令的 A 有符号、B 无符号。INT8 激活 `x` 转为 `u=x+128`，bias 修正为 `bias-(128+input_zero_point)*sum(weight)`，因此保持原式 `sum(weight*(x-input_zero_point))+bias`。不是把负数直接强转 uint8，也不是把模型本身改成 UINT8。
- 继续使用固定 TFLM 的 `ConvPrepare`、逐通道乘数/移位、`MultiplyByQuantizedMultiplier`、输出零点和融合激活上下界；不套用团队诊断图的简单右移及 `[0,127]` 截断。
- Depthwise（包括首层倍率8）、AvgPool、Reshape、Softmax 暂时不替换。因此这不是“全算子已优化”。量化 Prepare 中的软件 double 热点也没有在本版消除。
- 固定 workspace 9280字节，不在每次调用分配大栈。仅单解释器、单NPU、非重入。链接上限保持 ITCM256KiB / DTCM512KiB、栈16KiB；仍需实际交叉链接审计，不预先宣称装得下或栈峰值安全。

## 三种路径必须区分

| 目标 | 乘法执行位置 | 逐层校验 | 用途 |
|---|---|---|---|
| `host_model_test` | 主机 C++ 模拟 VME 算术 | 两图×14层，每个输出字节对比原 TFLM，并核对最终原始分数 | 接口/量化/打包正确性，不是RTL或性能 |
| `person_vme_validate.elf` | NPU真实VME指令 | 每层再运行默认卷积并全字节比较 | 后续RTL正确性，不用于测速 |
| `person_vme_fast.elf` | NPU真实VME指令 | 不重复执行默认卷积 | validate实际通过后才能用于RTL性能比较 |

校验模式用 TFLM 的 arena scratch 保存该节点的优化输出，然后执行原卷积、逐字节比较；不是只比较top1或hash。scratch复用在160KiB原arena内，实际用量需主机与NPU报告确认。

不支持的卷积显式计入 `pd_vme_fallback_calls` 并回退默认实现；固定模型固件要求14个卷积均走候选路径、fallback=0、矩阵发射计数>0，才允许设置完成状态。发射计数是软件发射记录，不冒称独立硬件退休计数。主机模拟另计 `pd_vme_emulated_tiles`，不会伪造硬件发射记录。

## 已在 Windows 实际验证

- 共享 C++ 核心用 MinGW GCC6.2、C++11、`-Wall -Wextra -Werror` 编译执行：336组，原始INT32累加结果逐项一致；包括正负数、-128、零点-128/-1/0/127、K=1..256的多种边界、M/N尾块、无bias、输出guard及溢出拒绝。此测试不验证TFLM量化或RTL。
- 使用本地玄铁 GCC14.3、`rv32imf_zve32f_zicsr` / `ilp32`，实际编译 `tile_compile_test.cc` 成RISC-V目标文件，汇编约束/编码语法通过。不是固定官方工具链的完整交叉链接或硬件执行。
- 新增7项工具契约/资源审计测试通过；原默认路径34项测试仍全部通过。原 `person_program.cc` / `person_runner.py` / `person_bench.py` 无改动。
- 用原始模型和BMP实际生成12份候选源码/数据文件，通过原模型SHA与样本SHA检查；模型不改。

**尚未执行**：固定TFLM的完整主机候选测试、两份候选的完整交叉链接与资源审计、VME RTL逐层校验、整网性能对比。不得把本目录名称或上述局部测试当作这些工作的PASS。

## 下一步：只在 Ubuntu VM 做主机验证和交叉编译

服务器默认版完整推理继续运行，不要停止，不用在服务器运行本脚本。沿用已建立的VM实验源和资产，不重新克隆私有团队仓库，不启动RTL，不重复默认版数小时观察：

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_person_vme/build.sh
)
```

执行次序：核对固定容量实验源及原基线 → 新增 `tests/cocotb/person_detect_vme_v1`（独立manifest）→ 主机核心测试 → 原始两图逐层全字节校验及最终原始分数核对 → 分别交叉编译 validate/fast → 真实ELF资源/模型/计数器符号审计。任何一步失败就停止；不覆盖旧候选，不自动放大ITCM/DTCM。

成功标记 `[PERSON_VME_HOST_AND_LINK_PASS] NPU_RTL=NOT_RUN`，目录 `$HOME/coral_tcm_capacity_8e4_v1/person_vme_v1.*`。**请先回传本步日志，再制作独立优化RTL运行包**。不要将新ELF直接塞进旧的不可变包；旧包manifest与runner绑定原ELF。硬件逻辑预计可保持同一256/512配置，但后续复用可执行模型必须验证RTL、依赖、工具和编译身份，不能绕过旧检查器。

## 验收与后续优化

1. 主机原模型两图、14层全部逐字节一致，且fallback=0。
2. 独立优化固件在同一NPU RTL上通过真实VME逐层校验；发射计数及反汇编与VME路径相符。
3. 同输入/模型/地址图/时钟/加载方式，分别比较准备周期、Invoke周期、总周期；validate固件不参与测速。
4. 再考虑 Depthwise（尤其倍率8）及量化初始化优化。当前Depthwise和软件double仍可能占主要时间，不能预先承诺整网加速幅度。

固定原始模型SHA：`808cfdfc0cf3a6fa6f6fa26bfa379ea97c16d5db7334637766e39c3408502e9d`；TFLM `b75c6ff4e2270047f2b48fa01f833c8101c31f43`；官方NPU `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`。
