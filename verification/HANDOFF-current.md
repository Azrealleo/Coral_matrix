# CoralNPU当前交接指南：单NPU Transformer/LLM算子验证

更新：2026-10-22（香港时间）。对象为继续此项软件/RTL验证工作的同学；不是只给综合人员的RTL使用说明。当前结果总表见[进度快照](PROGRESS-current.md)，全程经过见[工作记录](WORKLOG-and-handover.md)。原来叠加多轮“最新断点”的交接全文已完整保留为[历史交接快照](HANDOFF-archive-before-llm-20261022.md)，其旧计划不再作为当前任务。

## 1. 接手后先知道这六件事

1. 团队已确定官方CoralNPU，单NPU SoC集成测试由用户告知已通过，4核集成由团队继续；本人当前不验证4核互连。
2. 当前只测Transformer/LLM算子，不是预训练LLM或文本生成。固定单核ITCM256KiB/DTCM512KiB，优先Verilator。
3. Windows维护代码和记录，VM只做Bazel/Chisel、native参考、固件交叉链接/导出，服务器执行RTL仿真，不在旧CentOS7上强行运行当前Bazel。
4. INT8 case0/1原VM及服务器pilot通过后，用户已回传完整**21例RTL PASS（4 INT8+17 FP32）**；新FP32现在有真实硬件结果，不能再写待执行。
5. 整套job为`operators.cgtja4_x`，不是旧pilot `operators._jxei5s3`。当前只读归档结果/实际计时，不重复运行`all`。完整周期与证据边界见[结果报告](google_llm_ops/RESULTS-20261022.md)。
6. 每次给新仿真命令先说明预计墙钟、是否含编译、估算依据/不确定性。当前21例已补齐子进程耗时和3136.512秒（约52分17秒），不含case间核验及编译；同条件复跑估计约1小时、保守1～1.5小时。`5400秒`仍是每例超时，不是预计耗时。

## 2. 当前固定身份，不能相互替代

| 项目 | 固定值/说明 |
|---|---|
| 个人实验仓库 | [Azrealleo/Coral_matrix](https://github.com/Azrealleo/Coral_matrix)，本轮工具/记录同步于此 |
| 团队SoC库 | [cheshire-coral-soc/cheshire-coral-soc](https://github.com/cheshire-coral-soc/cheshire-coral-soc)，私有；本轮不写入 |
| 本实验官方源 | `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a` |
| 团队优化算子审查快照 | `fa4b83e43bb0b1d58b18eb5f4c31d98ee4054123`，不是自动跟随当前main |
| 当前顶层 | `VmeCoreMini_ITCM256KB_DTCM512KBAxi` |
| 复用RTL SHA256 | `477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2` |
| 新小包SHA256 | `fab74b4ff7ff643474d10f6b5d6513100e11d66cc8b291c9aca5abe7d2805b25`，210545字节 |
| INT8 ELF SHA256 | `17b3e2b6a5c208f638db2d7b85f4ddc5f8f64c336290093a9a11ce06a3dd072d` |
| FP32 ELF SHA256 | `ab1c95f0398f1e1ee43a0bc7b94677daebe21fdb4ff359046ce7eecf2c81f312` |

工具提交索引：`445b926`首次21例准备、`7bb95c5`服务器适配/小包导出、`38b5a9d`修复native cc_test及安全升级、`105b70d`记录实际ELF/包身份。当前文档整理不修改这些封存工具或包。不要把工具commit当RTL SHA，不把新ELF身份倒填到未提供旧ELF哈希的VM历史运行。

## 3. RAM和地址：本轮实际用的配置

| 项目 | 本轮 |
|---|---|
| ITCM | 256KiB，从`0x00000000`到`0x0003FFFF` |
| DTCM | 512KiB，从`0x01000000`到`0x0107FFFF` |
| CSR | `0x02000000`起，实验统一映射，不等同SoC最终图 |
| 栈 | DTCM末尾16KiB，`0x0107C000`到`0x0107FFFF` |
| INT8占用 | ITCM2976、DTCM静态13536、堆剩余494368字节 |
| FP32占用 | ITCM10992、DTCM静态59808、堆剩余448096字节 |
| 数据通路 | XLEN32、VLEN128，LSU/AXI数据128bit、AXI ID6bit |
| 开关 | RVV/VME/FP/BF16开启；AXI取指允许、FetchL0关闭、verification=false |

本实验SRAM为原逻辑/行为模型，保留原C++ DPI语义，不是真实工艺宏或网表门仿。逻辑1RW、128bit/16bit字节mask、读响应一周期；模型不保证上电全零，bench前门初始化。具体bank数/深度以锁定RTL和参数为准，不凭总容量推定物理宏型号。bench行为时钟1.25ns用于周期测量，不是芯片能跑800MHz的签核。

当前输入/权重/输出resident DTCM，未测外部AXI流式模型权重，不据此决定DDR带宽。动态栈只验证底部64字节canary，尚无完整水位证明。历史8/32KiB综合包来自旧源及旧地址图，不能替代本包。

## 4. 三台机器与必需材料

| 位置 | 角色与目录 |
|---|---|
| Windows | `E:\Projects\矩阵二选一`，个人工具仓库；未相关.gitignore、材料目录和旧RTL归档不得纳入本次改动 |
| Ubuntu VM | `/home/lqq/桌面/Coral_matrix`；study `/home/lqq/coral_tcm_capacity_8e4_v1`；source子目录为锁定源和实验补丁 |
| VM工具 | `$HOME/miniforge3`的`coral-matrix`；study中的Bazel9.1.0及既有缓存，不清缓存、不克隆最新上游替代 |
| EDA152 | `lqq@172.27.127.152:22`；`/home2/lqq`实际解析到`/data/home2/lqq`；CentOS7/glibc2.17 |
| 服务器工具 | `$HOME/coral_vcs_tools/miniforge3`的`coral-verilator`，Py3.11/Verilator5.052/GCC15.3 |
| Python依赖 | cocotb2.0.0、numpy1.26.4、pyelftools0.32、find-libpython0.5.1 |

交接必须另拿到原封存包、编译模型和原始证据，不是clone工具仓库就拥有可运行环境。密码/私钥/token不写进文档或Git，通过团队安全渠道转交访问权限。服务器代理断开不代表CPU仿真一定停止；进程状态应实时查看。

## 5. 不可变包、模型及最新PASS的准确位置

以下所有相对说明以此服务器根目录为基础：

```text
/data/home2/lqq/Desktop/coral_person_packages
```

- 新小包：`llm_fab74b4f/coral_llm_ops_i256_d512_v1/`，其中`server_ops.py`必须从该封存包运行，不随意换成Git新版本。
- 原Pool包：`pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1/`。
- 原编译模型：`pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1_verilator_runtime/builds/7a54106b3148.z558xni8/`。
- 原模型已验证短probe：同一`_verilator_runtime/runs/probe.46bl5uqr/`。
- 最新LLM pilot job：`llm_fab74b4f/coral_llm_ops_i256_d512_v1_server_runtime/jobs/operators._jxei5s3/`。
- pilot原始日志：上述job的`attempts/int8_0.g3eqoi8b/_test.log`；旁边应有XML、退出状态及result.json。job保存计划/身份及summary.md/json。
- **完整21例job**：`llm_fab74b4f/coral_llm_ops_i256_d512_v1_server_runtime/jobs/operators.cgtja4_x/`，控制台`/home2/lqq/coral_vcs_tools/llm_ops_all.mXLd8a.log`。每case四次样本一致，21条CASE_PASS和最终JOB_PASS cases=21；用户已回传summary.md及逐case子进程耗时，总和3136.512秒，不是严格套件端到端总墙钟。
- VM导出源job：`/home/lqq/coral_tcm_capacity_8e4_v1/llm_server_export.HJkCC5/`，保存两ELF、host/build日志和审计；归档名`coral_llm_ops_i256_d512_v1.tar.gz`。

新包依赖旧Pool编译状态和probe证据，不能只拷210KB小包到一台干净服务器就执行。读模型时核对原producer/环境/配方/二进制/短probe，持原状态锁；任何不一致即停，不修改manifest/current_build绕过检查。暂不要移动原模型路径，绝对路径属于身份记录的一部分。

pilot的四次标量均10563、四次RVV均263周期，空边界3；与旧VM case0数值一致，最终`cases=1`。首次/稳态比40.163498，不是完整LLM速度；用户未回传pilot实际墙钟，不猜填。

## 6. 性能口径与实现来源

21例的形状/来源逐项表在[进度快照第5节](PROGRESS-current.md#5-21例覆盖及软件来源)。只有INT8/FP32矩阵乘取固定官方Gemma源码；其他FP32是项目基线，不能概括成“官方优化内核全部启用”。Softmax/门控的exp/tanh仍标量libm且计入窗口。

同ELF两条路径分别首次+3次steady、交替顺序，fence+mcycle只计内核。输入生成、初始化、host装载和结果检查在窗外；空边界单列不扣。FP32固定atol2e-5/rtol2e-4，对独立参考；INT8 raw INT32精确核对，权重不取-128。检查真实输入/输出、guards/未使用尾区、自然halt/无fault/status3、调用计数、canary。不得放宽容差或删除开销来制造加速；RVV较慢也可正确通过。

原始Cocotb测试体以AST保持，服务器仅白名单替换文件定位并换入口；Bazel不会在服务器启动。WAVES/GUI必须unset，字符串`0`仍可能触发trace；原模型无trace支持。不要把此运行环境和VCS的系统GCC4.8/新DPI G++组合混用。

## 7. 接手第一步：只读回收已通过21例的结果

完整21例已通过，summary.md及21例耗时已回传。本节命令保留供只读复查/归档，不默认要求用户重复粘贴；只读预计数秒，不运行新仿真：

```bash
(
set -eo pipefail
llm_job=/data/home2/lqq/Desktop/coral_person_packages/llm_fab74b4f/coral_llm_ops_i256_d512_v1_server_runtime/jobs/operators.cgtja4_x
cat "$llm_job/summary.md"
find "$llm_job/completed" -maxdepth 1 -type f -name '*.json' | wc -l
)
```

summary.md包含每case子进程秒数；其和不是严格套件总墙钟，不含case间校验。完整job.json/summary.json和所有attempt原始文件应单独归档，不能只看计数21就重新验收。若日后调查未知任务，可用以下通用只读命令；不表示这次整套仍在运行：

```bash
(
set -eo pipefail
llm_state=/data/home2/lqq/Desktop/coral_person_packages/llm_fab74b4f/coral_llm_ops_i256_d512_v1_server_runtime
find "$llm_state/jobs" -mindepth 2 -maxdepth 2 -type f -name job.json -print
ps -u "$(id -u)" -o pid,ppid,etime,pcpu,stat,args | \
  grep -E '[s]erver_ops.py|[s]imv|[V]meCoreMini_ITCM256KB_DTCM512KBAxi' || true
)
```

这些是当前用户匹配结果，不自动证明每行属于本job；结合命令路径、job.json和日志核对。历史PID不能用于kill，不停止他人的任务。不要`tail -f`后误以为它会启动/推进仿真；本脚本只在case开始/结束写主控制台，长时间无新行不等于卡死。

## 8. 历史复现入口：21例前台运行（已通过，不默认重跑）

同条件复跑预计**约1小时、保守预留1～1.5小时，不含编译**；依据这次子进程和约52分17秒，需给case间校验/共享负载留余量。原首次1～3小时为历史粗估，不冒充实测。每例5400秒是上限。以下命令会新建job重跑21例，当前已通过，不默认执行，不接续pilot计划。

```bash
(
set -eo pipefail
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-verilator
unset WAVES GUI COCOTB_ENABLE_PROFILING
export CC="$CONDA_PREFIX/bin/gcc"
export CXX="$CONDA_PREFIX/bin/g++"
export PYTHONDONTWRITEBYTECODE=1
cd /data/home2/lqq/Desktop/coral_person_packages/llm_fab74b4f/coral_llm_ops_i256_d512_v1
tcm_rtl=/data/home2/lqq/Desktop/coral_person_packages/pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1
tcm_probe="${tcm_rtl}_verilator_runtime/runs/probe.46bl5uqr"
llm_console=$(mktemp "$HOME/coral_vcs_tools/llm_ops_all.XXXXXX.log")
printf '[LLM_CONSOLE_LOG] %s\n' "$llm_console"
python -u -B server_ops.py --packet "$PWD" --rtl-package "$tcm_rtl" \
  all --probe-run "$tcm_probe" --timeout 5400 2>&1 | tee "$llm_console"
)
```

每例`CASE_START/PASS`，失败立即停止。只有新的`LLM_SERVER_JOB_PASS cases=21`才是整套验收入口；还需保留summary、rawlog/XML/退出状态和原包身份，不能只留终端行。不在本次文档整理中启动/停止远程仿真。

## 9. 失败后如何继续，而不是再盲目all

1. 保存job路径、停止输出、出错attempt的`_test.log`、`_test-status.json`、`results.xml`及已有summary，不删除旧attempt。
2. 包/环境/构建身份失败先排查路径、工具和旧包是否改变；不要手改哈希或重编后冒充同一模型。
3. 数值/越界/fault失败先定位算子和实际输出，不能反复重跑求偶然PASS。需要改内核则做新版本、新身份，不覆盖封存包。
4. 外部中断且身份未变，可在同样环境、PWD和`tcm_rtl/tcm_probe`设置下执行：

```bash
python -u -B server_ops.py --packet "$PWD" --rtl-package "$tcm_rtl" \
  resume --probe-run "$tcm_probe" --job /替换为实际21例job目录 --timeout 5400
```

续测预计耗时按剩余case在[实际逐例计时](google_llm_ops/RESULTS-20261022.md)中的时间求和，并给case间校验/负载波动留余量；新增或改尺寸的case不能沿用旧时间。恢复只跳过原始证据重验完整的PASS，未完成case从固件入口另建attempt重跑，不是CPU checkpoint。不能用`cases=1`的pilot job恢复成21例。

## 10. 接手材料与验收清单

- 个人仓库当前工具/文档及commit，锁定官方源/实验补丁；不是clone最新版上游重做。
- 实际小包归档+SHA和两ELF资源报告；保留导出时host/build原始日志和源快照。
- 服务器原Pool封存包、整个已验证模型build目录、current_build记录、probe.46bl5uqr完整证据及对应Conda环境。原路径先保持。
- pilot job和后续21例job的job.json、completed索引、summary.md/json、每attempt原始日志/XML/退出状态/结果，包含失败记录。
- 若SoC/综合同学需要RTL/门仿，另交对应配置的生成RTL/参数/源版本和测试报告；本小固件包没有RTL，也不含完整测试报告。历史[8/32KiB交付说明](HANDOFF-simulated-rtl.md)不能直接代表256/512KiB当前模型。
- 接手成功的最小判据：能解释当前范围，定位原包/模型/probe/pilot证据，区分`READY`、链接审计、`cases=1`、`cases=21`和完整模型；能只读查看现有job，确认未运行时才启动/续测，能据summary追到每项原始证据。

尚缺：将服务器summary/原始证据和实际墙钟回收归档、更多尺寸/边界/真实输入覆盖、完整LLM/block/权重/tokenizer/持续KV、LLM VME与BF16/INT4/AXI流式性能、真实宏面积/功耗/200MHz STA及门仿签核。**当前21例及FP32真实RTL已经通过，不再列为未运行。** 旧默认Person单图PASS和VME/Pool短测不能替代上述未覆盖项。

## 11. 历史与专题导航（不自动继续旧计划）

| 内容 | 文档 |
|---|---|
| 最新进度/证据与待办 | [PROGRESS-current.md](PROGRESS-current.md) |
| 全过程、失败、旧比较和提交 | [WORKLOG-and-handover.md](WORKLOG-and-handover.md)，最新第29节 |
| 当前小包/服务器工具说明 | [LLM SERVER.md](google_llm_ops/server/SERVER.md) |
| 21例详细语义及旧VM备选 | [TOMORROW.md](google_llm_ops/TOMORROW.md) |
| 默认完整MobileNet、VME/Pool、Conv | [Person](google_person_detect/README.md)、[Pool](google_person_pool/README.md)、[Conv](google_person_conv/README.md) |
| 旧TCM性能结果 | [WORKSET-results.md](google_tcm_capacity/WORKSET-results.md) |
| 历史交接全文 | [归档](HANDOFF-archive-before-llm-20261022.md)，保留原阶段命令与说明 |

<a id="server-verilator-2m-pilot"></a>
<a id="server-verilator-t384"></a>

旧文档链接到上述TCM命令锚点时，请转到[历史交接相应章节](HANDOFF-archive-before-llm-20261022.md#server-verilator-2m-pilot)或[旧T384入口](HANDOFF-archive-before-llm-20261022.md#server-verilator-t384)。它们不是当前下一步；DTCM已按面积约束暂定512KiB，不自动恢复2/4MiB扫描。
