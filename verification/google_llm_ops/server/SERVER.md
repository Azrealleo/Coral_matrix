# 单NPU LLM算子：VM构建，服务器仿真

**当前断点：两ELF已链接、小包已导出/传服务器，INT8 case0 pilot真实RTL通过。** job `operators._jxei5s3`，四次标量10563/RVV263周期，最终`cases=1`。本页VM构建、传包、check/pilot步骤保留供复现，当前不必重做。21例命令已给出，未收到其新job/结果；先确认是否启动，不发重复任务。统一状态/路径与证据等级见[PROGRESS-current.md](../../PROGRESS-current.md)，操作见[HANDOFF-current.md](../../HANDOFF-current.md)。

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
# 一次性安全修复旧版cc_test规则；已修复时只复核，不重复覆盖。
python -B verification/google_llm_ops/transformer/repair_host_build.py
bash verification/google_llm_ops/export_server.sh
)
```

导出前严格验证候选源码，原INT8候选及FP32内核/bench不改；FP32生成器仅进行下述显式BUILD修复。链接失败或实际RTL SHA与服务器已验证模型不同则停止，不强行修改身份。请保存`LLM_SERVER_PACKET_ARCHIVE/SHA256/BYTES`。小包不含RTL和模型权重；`simulation=NOT_RUN`不是失败，也不是硬件通过。归档及`.sha256`传到服务器新的独立目录，校验通过后解压，不覆盖旧包。具体路径以实际导出输出为准，不使用虚构的归档哈希。

2026-10-22构建修复：旧FP32 BUILD误将`kernels.h`放进native `cc_test.hdrs`，该规则不接受此属性，改放`srcs`；自定义固件规则允许`hdrs`，保持不变。相应生成器身份有意更新，上方修复工具只接受已知旧生成器及所有原始文件的精确哈希，先备份旧BUILD/manifest，再更新这两项；任何未知修改都拒绝覆盖。内核、固件bench、fixtures、参数/计时不改，无需clean或删除缓存。先前122项工具检查没有实际执行Linux Bazel包分析，因此未发现此错误；本地检查不能替代VM真实分析/链接。

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

这次21例预计**1～3小时，低置信度粗估，不含编译**；依据此前同服务器负载约2800～3000周期/秒和当前小规模，INT8粗约20～30分钟，FP32首次/exp/tanh及共享负载不确定，收到实测须更新。用户要求每次发仿真命令先交代预计、是否含编译及依据；`5400`是**每例墙钟超时上限，不是总耗时预测**。不自动启动后台、不重复编译模型。保持服务器供电；共享负载影响墙钟，不改变NPU mcycle。

每例开始/结束一行，不每几秒刷屏。失败立即停止，rawlog、XML、退出状态保存在`LLM_SERVER_CASE_START`输出的路径；未完整通过不能标PASS。作业目录为`<小包>_server_runtime/jobs/operators.*`，`summary.md/json`逐例更新，保留全部原始mcycle和口径。

```bash
# 将下方路径替换成实际LLM_SERVER_JOB_DIRECTORY；不是仿真CPU checkpoint。
python -u -B server_ops.py --packet "$PWD" --rtl-package "$tcm_rtl" \
  resume --probe-run "$tcm_probe" --job /实际作业目录 --timeout 5400
```

续测重新核验原包、工具、模型、环境、每条已完成原始日志/XML/退出状态/结果哈希；只有未变的完整PASS跳过。未完成或中断case另建attempt，从固件入口重跑，不删除旧证据。全部21例验证后才打印`LLM_SERVER_JOB_PASS cases=21`。单例job只有`cases=1`，不能冒充整套通过。

## 当前真实证据边界

用户已回传VM `llm_server_export.HJkCC5`实际链接/资源审计和小包导出成功。INT8 ELF SHA `17b3e2b6a5c208f638db2d7b85f4ddc5f8f64c336290093a9a11ce06a3dd072d`，ITCM占用2976、DTCM静态13536、heap494368字节；FP32 ELF SHA `ab1c95f0398f1e1ee43a0bc7b94677daebe21fdb4ff359046ce7eecf2c81f312`，对应10992/59808/448096字节。均是LINK/AUDIT，不是RTL执行PASS。

实际归档`coral_llm_ops_i256_d512_v1.tar.gz`，210545字节，SHA `fab74b4ff7ff643474d10f6b5d6513100e11d66cc8b291c9aca5abe7d2805b25`。服务器包位于`/data/home2/lqq/Desktop/coral_person_packages/llm_fab74b4f/coral_llm_ops_i256_d512_v1`，check及INT8 case0 pilot已实际通过，原模型`7a54106b3148.z558xni8`只读复用。下一步确认/收集21例套件结果，不再重复传包或编译；当前无整套结果。

实际pilot job为`/data/home2/lqq/Desktop/coral_person_packages/llm_fab74b4f/coral_llm_ops_i256_d512_v1_server_runtime/jobs/operators._jxei5s3`，attempt `int8_0.g3eqoi8b`。用户回传scalar=[10563,10563,10563,10563]、rvv=[263,263,263,263]、边界3、比40.163498；最后`JOB_PASS cases=1 full_model=NOT_RUN VME=NOT_RUN`。pilot实际墙钟未回传，不补造；新21例应另有job。

旧VM INT8 case0/1真实RTL通过，分别10563/263和168618/4110周期；不补造其旧ELF哈希，也不把此次导出的ELF自动标成旧实测同字节身份。FP32真实RVV/NPU执行仍待服务器。原Person/Pool/VME/Conv包和所有已测ELF/RTL保持不变。
