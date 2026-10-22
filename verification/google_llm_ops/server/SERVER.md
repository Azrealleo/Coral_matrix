# 单NPU LLM算子：VM构建，服务器仿真

2026-10-22最新分工：VM只做native参考、两份RISC-V固件完整链接、内存审计及小包导出；不运行RTL仿真，不编译Verilator大模型。服务器使用原有coral-verilator环境和**已通过Pool probe的256/512KiB模型**，不需要Bazel，不重新编译或改写原模型。

本包21例：4例resident合成INT8线性层，17例FP32矩阵乘/RMSNorm/Softmax/RoPE/门控激活/残差/KV追加/因果GQA Attention。每例标量/RVV各首次+3次steady；不是完整LLM推理，不输出tokens/s，VME未参与。只有INT8/FP32矩阵乘取自固定官方Gemma源；其余FP32为项目基线，exp/tanh仍使用标量libm，不保证RVV更快。

## 1. VM：只构建和导出

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_llm_ops/export_server.sh
)
```

导出前严格验证原候选源码，原INT8与FP32生成器/内核不改。链接失败或实际RTL SHA与服务器已验证模型不同则停止，不强行修改身份。请保存`LLM_SERVER_PACKET_ARCHIVE/SHA256/BYTES`。小包不含RTL和模型权重；`simulation=NOT_RUN`不是失败，也不是硬件通过。归档及`.sha256`传到服务器新的独立目录，校验通过后解压，不覆盖旧包。具体路径以实际导出输出为准，不使用虚构的归档哈希。

## 2. 服务器：先检查，再跑单例

已知可复用的原包/短probe为：

```bash
tcm_rtl=/data/home2/lqq/Desktop/coral_person_packages/pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1
tcm_probe="${tcm_rtl}_verilator_runtime/runs/probe.46bl5uqr"
```

在**新解压小包**目录执行（而不是旧Pool包）：

```bash
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-verilator
unset WAVES GUI COCOTB_ENABLE_PROFILING
export CC="$CONDA_PREFIX/bin/gcc"
export CXX="$CONDA_PREFIX/bin/g++"
export PYTHONDONTWRITEBYTECODE=1

python -u -B server_ops.py --packet "$PWD" --rtl-package "$tcm_rtl" \
  check --probe-run "$tcm_probe"
python -u -B server_ops.py --packet "$PWD" --rtl-package "$tcm_rtl" \
  run --probe-run "$tcm_probe" --family int8 --case 0
```

新适配器只调整Bazel文件路径解析及测试入口，直接执行封存的原`run_case`函数体，保留前门加载、独立golden、输出guard/尾区、自然halt/fault、mcycle窗口、四次调用和栈底64字节canary检查。不是完整栈水位测试。`WAVES/GUI`必须unset，不能写`0`；已有模型无trace支持。

读原producer构建配方、环境、二进制哈希和原probe的XML/原始日志证据，核验通过才复用。环境不一致、包被改或原模型锁忙则停止；不要手改manifest/current_build，不杀他人的任务。运行期间持原模型锁，不能与使用同一私有状态的旧脚本并行。

## 3. 串行21例及恢复

单例正常后：

```bash
python -u -B server_ops.py --packet "$PWD" --rtl-package "$tcm_rtl" \
  all --probe-run "$tcm_probe" --timeout 5400
```

`5400`是**每例墙钟超时上限，不是总耗时预测**。不启动后台、不重复编译模型；若需要过夜后台运行，应先确认pilot，再单独用nohup包装并保存控制台日志。保持服务器供电；串行测试允许其他用户用别的核，但共享服务器负载会影响墙钟时间，不改变NPU mcycle。

每例开始/结束一行，不每几秒刷屏。失败立即停止，rawlog、XML、退出状态保存在`LLM_SERVER_CASE_START`输出的路径；未完整通过不能标PASS。作业目录为`<小包>_server_runtime/jobs/operators.*`，`summary.md/json`逐例更新，保留全部原始mcycle和口径。

```bash
# 将下方路径替换成实际LLM_SERVER_JOB_DIRECTORY；不是仿真CPU checkpoint。
python -u -B server_ops.py --packet "$PWD" --rtl-package "$tcm_rtl" \
  resume --probe-run "$tcm_probe" --job /实际作业目录 --timeout 5400
```

续测重新核验原包、工具、模型、环境、每条已完成原始日志/XML/退出状态/结果哈希；只有未变的完整PASS跳过。未完成或中断case另建attempt，从固件入口重跑，不删除旧证据。全部21例验证后才打印`LLM_SERVER_JOB_PASS cases=21`。单例job只有`cases=1`，不能冒充整套通过。

## 当前真实证据边界

旧VM INT8 case0/1真实RTL通过，分别10563/263和168618/4110周期；新服务器21例尚未运行。新增FP32主机参考与本地RV32对象检查已做，不等于官方ELF完整链接或NPU执行；需用户运行步骤1后再确认。原Person/Pool/VME/Conv包和所有已测ELF/RTL保持不变。
