# VME软件优化候选：明天验证，今晚不仿真

独立候选tests/cocotb/llm_vme_opt_v1，固定单NPU ITCM256KiB/DTCM512KiB，原4种resident INT8形状。
原官方RVV、旧VME完整调用和权重复用保留，新增优化完整调用/权重复用，共五条同ELF路径。
当前仅准备阶段：本地主机/交叉编译检查已执行，但尚无本候选正式VM链接、RTL正确性或速度结论。

## 修改范围

- RVV打包权重并累积每通道有符号补偿，输入跨步加载转置并XOR0x80。
- M1/M16使用向量初始化累加器和直接跨步写回行主序输出，省去临时累加器转置。
- 其他M使用显式记录的原HardwareTile回退，不把回退冒充新快路径。
- K最多64，按4补齐；N尾块按16补齐、严格清零。原HardwareTile、旧v2/分段诊断、RTL、Depthwise均不变。
- 普通VSET会清除此实现的mtype；直接写回使用msettn调整和恢复VL。正式ELF额外审计机器码，拒绝该片段中的普通VSET。

主性能输入仍限制W[-127,127]，允许X=-128，满足官方RVV限制。native边界检查另外覆盖W=-128；
这不表示官方RVV在双边-128下正确。所有结果为raw INT32，不含量化/激活，不是完整LLM。

## 验证顺序

先运行同一新ELF的9形状短硬件探针，覆盖新指令、M1/M16、K/N尾部和回退。
探针通过前，VM/服务器包装入口拒绝运行性能例子。不要绕过包装入口直接调用底层Bazel测试作为正式验收。
探针不是性能结论，不用旧探针替代新优化指令验证。
之后优先在VM单例运行，预计不超过1小时的例子不必转服务器。
服务器保留原Pool模型只读复用方式，不编译RTL。

首次/稳态分开，权重预打包分别计时，报告含预打包的首用和四次摊销。
主机独立INT64参考、签名、调用/命令/快路径计数、前门读回和guards均需通过。
不同ELF代码布局可能改变旧路径周期，以本ELF配对为准，不拼接旧v2或插桩周期。

## 明天：推荐先quick

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_llm_vme_opt/tomorrow.sh quick
)
```

quick顺序：2个native测试→正式交叉链接/资源/机器码审计→导出备用服务器小包→
**仅build**全部5个RTL测试可执行文件（复用原llm_linear_v1模型的正确exec配置）→
短硬件探针→prefill_tiny性能对照→严格重验并产生partial summary.json/md。
不会并行跑，也不启动完整模型。首次模型编译/依赖不在仿真ETA内，缓存正常准备为数分钟级。
首个新指令探针未通过就停止，不自动放宽检查或跳过。

预计短探针3～10分钟；case0约4～10分钟，case1约10～20分钟，case2约5～15分钟，case3约20～45分钟。
quick粗估15～35分钟，all约45～100分钟，再加首次准备；均来自原服务器结果的粗估，VM需以首例校准。
每次run打印ETA。VM每例默认test_timeout=3600秒，父进程另留120秒Bazel收尾；不是ETA。

## 仅准备，绝不跑RTL

```bash
bash verification/google_llm_vme_opt/tomorrow.sh prepare
```

prepare也是tomorrow.sh不带参数的默认行为。仅native/链接/审计/导出和**build**测试可执行文件，
不会对RTL目标执行bazel test，也不调用run_vm.sh。原始源manifest拒绝覆盖未知修改。
准备成功打印LLM_VME_OPT_READY_FOR_TOMORROW和目录；目录中firmware内包含可传服务器的tar.gz和.sha256。

## 续跑已有准备（不要重复生成新包）

将下面目录替换成终端打印的实际prepared目录，不要照抄占位符：

```bash
tcm_prepared=/实际打印的prepared目录
bash verification/google_llm_vme_opt/run_vm.sh "$tcm_prepared" quick
bash verification/google_llm_vme_opt/run_vm.sh "$tcm_prepared" all
python -B verification/google_llm_vme_opt/summarize.py --vm-prepared "$tcm_prepared"
```

all逐例为probe、0、1、2、3；已通过并保留完整证据的例子会重验后明确CASE_REUSED，不重复仿真。
证据损坏/型号或固件变更会拒绝，而不是跳过。失败/断电未完成的例子使用新attempt目录重跑，旧日志保留，
不是CPU checkpoint。单独运行用run_vm.sh "$tcm_prepared" probe或0/1/2/3；已有已验收结果时拒绝隐式重测。
若确实要复测，显式建立新准备目录，缓存的构建可复用。summary默认需要4例；quick后只汇总一例用--partial。

## 服务器备选

由VM生成的包coral_llm_vme_opt_i256_d512_v1.tar.gz不含RTL。校验打印的真实SHA后在新目录解压，
不要覆盖旧v2/分段包。激活服务器coral-verilator，CC/CXX指向该Conda编译器，unset WAVES GUI COCOTB_ENABLE_PROFILING。
从新包执行bash run_server.sh quick；默认为check，probe仅跑新短探针，all为新探针后4例串行。
run_server.sh 0/1/2/3要求第二参数给实际新候选探针run目录；不能用原Pool探针冒充新指令验证。
原Pool包/模型/probe.46bl5uqr保持只读核验，不重新编译模型。
虚拟机探针不能直接替代另一宿主机模型的服务器探针。服务器日志和结果写包外_runtime目录，原包不变。

服务器只读汇总可从新包运行（原始run目录保持原路径）：

```bash
python -B summarize.py --packet "$PWD" --probe-run /实际新探针目录 \
  --runs /实际case0目录 /实际case1目录 /实际case2目录 /实际case3目录
```

只有完整原始日志/XML/退出状态/同ELF/同模型/探针关联通过才生成汇总。
不要手工将fault改为false、放宽计数或修改sealed包。准备/主机PASS都不能标成RTL PASS。

## 失败时回传什么

保留打印的run目录，发test.log/XML和状态；服务器为_test.log/results.xml/_test-status.json，
VM为test.log/test.xml/test-status.json，并保留bazel-console.log。
探针额外打印current_case、step、已完成例数、首个不匹配元素及actual/expected的uint32原始位。
step1填数、2参考打包、3候选调用、4结果核验、5布局/guard核验、6完成该例；status42数值错误、43打包错误、44guard错误。
即使提前trap，也先记录实际M/K/N和探针进度，再严格拒绝，不用断言把诊断信息截掉。

本地检查包含980组边界/极值和65536个M1..16/K1..64/N1..64组合的native算术穷举、GCC14静态分析，
以及真实RV32目标对象/本地合成ELF的机器码和资源审计。这些都不是RTL仿真；Ubuntu正式链接与两种宿主机入口仍待实际运行验证。
