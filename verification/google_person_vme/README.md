# Person Detection：独立 VME 优化候选 v1

**2026-10-21最新进展：** 用户回传 `person_vme_v1.zFvRgl`，主机两图28次Conv逐字节对比、validate/fast两份完整交叉链接和资源审计均通过。validate ELF SHA `980b3373ad9a0ad8ab00e820eaa3dd10d6bae9eaf6612d832276eb03cb8b0cb7`，ITCM139760/DTCM静态483760/堆24144字节；fast SHA `c07d3039e66e0422e688abc2f8c281b110cd3ba7a1b40872ea94df86430821fd`，ITCM139136/DTCM静态483744/堆24160字节。两者均适配256/512KiB配置，均未执行NPU RTL。下一步为下方独立导出及短VME硬件probe，不再重复build.sh。

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

以上为初始本地验证范围；后续VM实际结果见下节，不将主机或链接通过当作RTL通过。

## VM实际回传及审计修复（2026-10-20）

运行目录 `person_vme_v1.acWcT3`。固定TFLM原模型完整主机测试已实际通过：有人图[-113,113]、无人图[57,-57]，共28次候选卷积层输出与默认内核逐字节一致；主机校验模式arena_used=122000字节。这是主机模拟矩阵算术，不是NPU实际arena测量或VME硬件验证。

validate固件实际交叉链接/资源审计通过：ELF SHA `980b3373ad9a0ad8ab00e820eaa3dd10d6bae9eaf6612d832276eb03cb8b0cb7`，ITCM占用139760字节、DTCM静态483760字节、剩余堆24144字节、保留栈16KiB，装进选定256/512KiB配置。fast也已链接成功，但旧审计脚本错误地要求它保留两个仅校验路径使用的变量，导致符号检查停止；尚无fast资源审计PASS。

修复只改 `audit.py`：validate仍要求六个符号，fast要求其main完成门限实际使用的四个（conv_calls/fallback_calls/commands/mismatches）；允许仅校验用的validated_layers/first_bad_index被链接垃圾回收。若可选符号保留下来，仍检查其大小与DTCM范围，其他必需符号缺失仍停止。报错现在列出具体missing/invalid，不跳过符号审计。内核、安装manifest的生成器和全部生成源码均未改，不需要覆盖候选或重建RTL。新增4项回归，合计11项新工具测试、34项默认路径测试通过。

**下一步重新执行下方build.sh即可**：已有目标可命中缓存，主机测试也只约0.3秒；新结果目录保留原失败目录，不覆盖证据。随后仍须独立的VME RTL逐层校验和性能测试，当前均未执行。

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

## 下一步：VM独立导出，不重新生成RTL

新增 `export.sh`/`export_bundle.py`：核验上面的实际主机/ELF证据；复制原 `person_rtl_export.r9bhUw/coral_person_i256_d512` 的逐字节相同RTL、DPI、fixture、模型和输入；原样复制已通过的validate/fast ELF；只新增并交叉链接一个短VME硬件probe固件。不修改原包、旧安装manifest、原默认程序或既有候选源码，不跑主机模型或RTL仿真。

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_person_vme/export.sh \
  "$HOME/coral_tcm_capacity_8e4_v1/person_vme_v1.zFvRgl" \
  "$HOME/coral_tcm_capacity_8e4_v1/person_rtl_export.r9bhUw/coral_person_i256_d512"
)
```

成功输出 `[PERSON_VME_BUNDLE_ARCHIVE]` 与 SHA256。输出位于新的 `person_vme_export.*`，包名 `coral_person_vme_i256_d512_v1.tar.gz`；原包/原结果目录保留。先回传导出日志和SHA，再传服务器核验解包。若缺原解包目录，停止并定位原档案，不用另一次随意生成的RTL代替。

### 为什么先跑短硬件probe

主机全模型测试的矩阵计算是C++模拟，没有执行真实VME指令。先验证同一 `pointwise_core.h`/`vme_tile.h` 在真实NPU RTL上的负数、极值、零点-128/-1/0/127、M/N/K尾块：8组、840个原始INT32结果逐项与独立标量参考比较，预期发射233条矩阵指令，输出签名3016346044。代码不调用TFLM初始化，不需要等10M周期的量化准备才遇到第一条VME指令。

`hardware_probe.cc`的主机模拟分支已实际编译执行通过（8/840/签名一致），真实硬件分支已由本地玄铁GCC14.3编译成RISC-V目标文件；仍不是官方工具链完整链接或RTL PASS。18项候选工具测试、原路径34项测试、脚本语法和命令行入口检查通过，含一次完整合成导出验证；合成文件不冒充实际固件/模型/RTL。

### 包内服务器工具（暂时只跑短probe）

- `portable_vme.py`：核对三份ELF、原模型/输入/RTL和全包清单；不修改检查和manifest来“修复”包。
- `server_probe.py`：复用SHA固定的旧环境检查/通用构建函数，所有编译/运行结果在新包同级 `_verilator_runtime`。不接触旧默认任务的模型或状态文件。参数只支持verify/check/build/probe及内部阶段，**不是整网推理入口**。
- `probe_bench.py`：原fixture前门加载、原时钟语义，等待自然halt，检查fault/status/8组/840元素/233条指令/签名/栈底canary。跑满预算或任何错误不标PASS；输出明确 `full_model_inference=NOT_RUN`。
- 首次server build会在独立目录编译同一份RTL，不偷偷改写旧模型身份。probe程序可提前结束，周期上限默认200万、墙钟上限1800秒；运行时间以实际结果为准。后续validate/fast整网运行入口在短probe通过后接续，不手动塞新ELF进旧包。

当前VM实际导出、probe固件官方链接、服务器新模型编译和短probe RTL均尚未执行。服务器原默认版长任务保持不动。
