# 成熟矩阵内核调度借鉴：独立 K-loop 候选

固定官方基线 `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，单NPU，
ITCM256KiB/DTCM512KiB。RTL、ISA、官方RVV源和既有已验收实验均不变。
本候选尚无正式Ubuntu链接/RTL执行/性能结果。主机测试不是硬件验证。

## 移植内容与对照

参考固定提交的官方Coral矩阵代码生成和Arm KleidiAI INT8 SME微内核，
实际源码分析及出处见本目录SOURCES.md。本版移植的是configure-once、
完整K循环在一个asm块内累加、最后统一读回的调度方法，不是把Arm指令拿来运行。

- 上一版：每条Tk4前重复msetmtype/TM/TN配置，循环包含C++调度。
- 本候选：每个输出tile只设置一次mtype/TM；K循环在单个asm块内。
- M16：K循环中无配置指令。M<16：加载时TN16、计算时TN=M，
  每步仅保留必要的两次msettn，绝不以缩短VL的方式漏载权重。
- 保留X+128、有符号补偿、权重/输入布局、累加器初始化与直接输出写回。
- 不引入官方新编译器的signed-B altfmt、新Zvt编码、额外tile、DMA或异步双缓冲。
- 仍为raw INT8乘法到INT32，不含模型量化/激活/外部存储。

性能与RTL探针保持W[-127,127]、X[-128,127]，遵守固定官方RVV基线限制。
native额外极值检查不等于已经证明双边-128的硬件路径。

同一份新ELF比较五条路径：官方RVV、**已验证的直接写回VME完整/复用**、
新K循环VME完整/复用。不是与最初的慢VME比较，也不拼接历史周期。
为兼容已验证控制器，JSON的complete/reuse表示已验证VME基线，opt_*表示本候选；
比较记录显式标明baseline_path/candidate_path，Markdown列名也明确区分。
旧路径只改命名空间/入口名以避免链接和ADL冲突，算法/指令不改。

M扫描仍为1/2/4/8/12/16、K=N=64。每路径首次加3次稳态，完整计入打包；
reuse还分别报告计入一次性预打包后的首用与4次摊销，不隐去预处理成本。

## 验证门槛

1. 本地/native数值和packing检查；原官方RVV源码身份固定。
2. 正式RV32 ELF资源/机器码审计：识别全宽及部分宽度两个真实K循环，
   检查唯一msetmtype位于回跳目标之前，循环含8次向量加载/1次矩阵命令，
   禁止普通VSET、循环内调用和额外控制跳转。审计不是执行证明。
3. **新候选自己的13组短RTL探针**必须通过，然后才允许性能用例。
4. 逐元素INT64参考、前门输入/输出/packed/workspace读回、签名、调用及
   软件命令计数、guard、无fault和自然halt。栈只验底部64字节canary，非完整水位。
5. 不要求新候选一定更快；若正确但更慢，保留真实结果。

两个K循环模板在硬件只使用已有旧编码；汇编循环中软件计数每次真实迭代递增，
但仍不是独立硬件退休计数。主机模拟不执行这些指令。

## 虚拟机先 quick

预计仿真20～45分钟（13组探针加M8），准备/首次编译另计；
依据前一轮同M扫描，仍需本候选首例校准，不是完成承诺。
每例默认3600秒超时不是ETA。整套6例粗估80～180分钟，先不要直接all。

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_llm_vme_mature/run.sh quick
)
```

不带参数或prepare仅准备/构建，不运行RTL。请保留打印的
`LLM_VME_MATURE_JOB_DIRECTORY`及整个tools/prepared目录。
quick通过后优先增加M1和M16，无须重跑原探针/M8：

```bash
bash verification/google_llm_vme_mature/resume.sh /实际job目录 0
bash verification/google_llm_vme_mature/resume.sh /实际job目录 5
```

M1预计5～15分钟，M16预计20～45分钟，不含已完成构建。
其他case为1=M2、2=M4、3=M8、4=M12；all包含全部6例。
序列会严格重验已有PASS证据后复用；单例重复执行会拒绝，失败尝试保留。

## 服务器备用

准备阶段会导出不含RTL的新包`coral_llm_vme_mature_i256_d512_v1.tar.gz`，
校验实际打印的SHA后在新目录使用。沿用已验收Pool模型只读复用，
服务器必须通过本候选在该宿主机的probe，不能使用旧opt/sweep/VM探针冒充。
新包的run_server.sh quick仍先probe后M8；不开波形，不覆盖旧包。

全局工作记录和交接文档依用户约定不自动更新。此README仅说明本候选，
不把本地工具、主机模拟、交叉编译或代码审计写成RTL PASS。

本地回归入口为`python -B -m unittest discover -s verification/google_llm_vme_mature -v`。
原生/目标检查分别使用环境变量LLM_TEST_CXX、LLM_TEST_CROSS、LLM_TEST_OBJDUMP，
脚本语法检查使用LLM_TEST_BASH；需要pyelftools0.32。未提供编译器时相关检查
会明确skip，不能把有skip的结果当作完整检查通过。
