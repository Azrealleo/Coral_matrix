# 单NPU：更大K/N和M分块的INT8 Linear候选

新独立包tests/cocotb/llm_vme_large_v1；原RTL不变，ITCM256KiB/DTCM512KiB。
尚无本候选正式RTL PASS或性能结论。旧opt/sweep候选、工具、固件和日志均不覆盖。

| ID | M | K | N | 用途 |
|---:|---:|---:|---:|---|
| 0 | 16 | 64 | 64 | 同ELF小控制 |
| 1 | 1 | 128 | 128 | Decode |
| 2 | 16 | 128 | 128 | Prefill |
| 3 | 32 | 128 | 128 | 两个M块 |
| 4 | 17 | 128 | 128 | M尾块 |
| 5 | 1 | 256 | 64 | 更深Decode |
| 6 | 16 | 256 | 64 | 更深Prefill |
| 7 | 32 | 256 | 64 | 更深两M块 |

M以16分块、N以16分块，K每条矩阵命令处理4并补零。K最多256，不是任意大K的跨调用累加。
每个逻辑调用只打包一次权重，在所有M块之间复用；reuse路径还跨四次调用复用同一份打包权重。
这是串行软件分块，没有DMA/并行双缓冲，也不代表完整模型性能。

五条同ELF路径：官方RVV、旧VME完整/复用、新VME完整/复用。四次采样仍保留首用和三次稳态。
完整调用包含权重打包；reuse排除一次性打包，JSON另外计首用/四次摊销包含打包成本。
VME窗口包含M分块、输入打包、累加器初始化、矩阵命令、读回及输出写回。
CPU的独立INT64参考只计算一次，放在所有计时窗外；每次输出仍逐元素比较并签名，主机另外独立核验最终输出、gold参考和所有guards。
因此不能把本候选总仿真时间或旧候选的周期拼接成算法加速比。

## 边界与安全

内层K从64扩到256、N扩到128；INT16权重列和在[-32768,32512]内，先扩成INT32再乘128补偿。
硬件探针8例覆盖K=255/256、N=127/128、M=17/31/32，以及K256下整列+127/-127的补偿极值。
最大逻辑M32，所有临时存储和输出均静态限界，正式ELF重新审计是否落在512KiB DTCM内。
预留16KiB栈；仍只检查栈底64字节canary，不冒充完整栈水位证明。

性能对照保持N为64的倍数、K为4的倍数。官方RVV源保持原样：源码检查发现其N-tail路径有使用vlmax而非剩余有效VL的疑点，
尚未在RTL上单独复现，不能把该路径冒充已验证基线。非对齐K/N由VME短探针对独立INT64参考验证，不声称已完成双方尾部性能对比。
W仍[-127,127]、X[-128,127]；raw INT32，不含量化、激活、外部存储开销。

## 先跑quick

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_llm_vme_large/run.sh quick
)
```

先做3个native测试、链接/资源/机器码审计和Bazel build，再跑新8例探针以及case0控制。
quick仿真粗估20～60分钟，首次构建另计；仅此轮建议先在VM跑。
后续根据打印的VM_WALL和实际周期校准。大例粗估25～90分钟/例；预计超过1小时的优先转稳定服务器。
不要立即all铺开：全部8例粗估3～7小时，目前未校准。程序明确区分ETA、模型构建和超时。
VM每例默认5400秒超时，probe预算20M周期、性能预算30M周期，均不是ETA。

只准备、不仿真：run.sh prepare（也是默认）。已有job恢复：

```bash
bash verification/google_llm_vme_large/resume.sh /实际job目录 1
```

可选probe、0..7、quick、all；已通过例在sequence中重验复用，单例重复运行会拒绝。
失败日志保留，不放宽fault、halt、计数、签名、读回或guard条件；旧探针不能代替新候选探针。
所有工具在唯一job/tools内从固定a2497c0和add3bc4派生，原依赖字节和变更模板逐项核对，恢复前后复验清单。
保留整个job目录，不修改生成工具树。服务器备用固件包在prepared/firmware内，不含RTL，复用原已验收Pool模型仍需新候选探针先通过。
