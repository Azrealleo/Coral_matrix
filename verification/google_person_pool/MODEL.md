# 合并版完整模型：外部入口，复用已通过的编译模型

2026-10-21。默认完整模型已有真实RTL单有人图PASS；VME原始算术和新RVV Pool短probe均PASS。**合并版完整模型尚未执行/回传**，不能用短测推导整网通过或加速比。

当前不可变包：`/data/home2/lqq/Desktop/coral_person_packages/pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1`，归档SHA `7c8e0fe5121c0aeb37d9e8a54983dd7fe64603bf5de964b718aac4cd4b3076eb`。原包server_probe只跑短算术，仍不改动它、不向它添加infer或换ELF。新增model_runner.py/model_bench.py/run_model.sh放在**包外独立工具目录**。

## 复用条件

- 原包逐文件/SHA/原模型/样本、三份ELF及256/512KiB资源重新校验。
- 已封包server_probe/probe_bench及环境helper哈希固定；ELF SHA必须是已测validate `8137e2bf...`、fast `81f596bd...` 和实际probe `031cf123...`。
- 重新计算**原producer身份**，核对current_build、build-record、环境、编译命令/可见性和二进制哈希，不能把旧exe重新标成新runner的构建。
- 要求同包、同build的真实Pool probe结果，重新核验result.json、原始日志、XML、8/659/62/签名/自然halt/无fault及canary。
- 全程持原producer的锁，但不改current_build、编译模型或包内文件；新证据在同级`coral_person_vme_pool_i256_d512_v1_model_runtime/runs/*`。
- 配方或环境不同即停止，不自动重编、清cache、改manifest或跳过比较。锁忙也停止，不杀其他任务。

已确认实际build为`..._verilator_runtime/builds/7a54106b3148.z558xni8`，probe为`.../runs/probe.46bl5uqr`。默认run_model.sh使用后者，路径会解析到/data；新包不需要重新导出或再传。

## 第一轮：一张有人图的校验版

下载/传输本目录model_runner.py、model_bench.py和run_model.sh到服务器独立工具目录、校验已发布SHA后运行：

```bash
bash /ABSOLUTE/TOOL/DIRECTORY/run_model.sh
```

脚本先前台check，通过后才用nohup启动**一个**有人图validate后台任务，输出JOB_DIRECTORY/PID/CONSOLE_LOG。不自动排队无人图或fast，不重编RTL。查看进度：

```bash
tail -n 40 -f /ACTUAL/JOB/DIRECTORY/console.log
```

Ctrl+C只停止tail，不停止仿真。启动PID仅作本轮记录，不能以后盲目kill。复用编译不等于续跑probe，仍从完整固件入口重新初始化。

该固件14次VME Conv后逐层运行原reference并逐字节比对；Pool同样额外运行reference。要求14个Conv/1个Pool全部校验、0fallback/0mismatch、矩阵发射非零、Pool16向量块（VLEN128、256通道）、原始有人分数[-113,113]、自然halt、无fault、arena有效和栈底canary通过。最终标记`PERSON_POOL_MODEL_INFERENCE_PASS variant=validate performance_eligible=false`，**绝不作为加速结果**。

默认预算4亿周期、172800秒（48小时）是停止上限，不是预计耗时。原默认同图实际总约18小时18分；校验版重复reference，还保留默认Depthwise及量化初始化，不能承诺会更快。完成即提前退出；周期或墙钟耗尽保留日志，不记通过，不能从停止点继续。为了不改变周期口径，执行窗口中不通过AXI轮询计数器，故长时间没有新增日志并不等于停机。

## 随后：同图测速与第二张图片

validate通过后再决定fast；例如在相同Conda/CC/CXX环境中：

```bash
"$CONDA_PREFIX/bin/python" -u -B /ABSOLUTE/TOOL/DIRECTORY/model_runner.py \
  --package /ABSOLUTE/PACKAGE/coral_person_vme_pool_i256_d512_v1 \
  --probe-run /ABSOLUTE/PRODUCER_STATE/runs/probe.46bl5uqr \
  --validation-run /ACTUAL/MODEL_STATE/runs/validate_person.RESULT \
  --variant fast --case person --cycles 200000000 --timeout 86400 infer
```

该命令是显式前台示例，不在第一轮自动执行。fast要求**同一张图、同包/原producer build**的完整validate原始证据，不接受只剩控制台PASS文本；其ELF不能执行逐层reference校验计数。未获用户回传前，不声称任何优化整网PASS。

无人图需独立`--case no_person --variant validate`，随后同图fast；其参考分数[57,-57]。每次启动重新初始化，不将两图计数混合。内核调用/发射计数是软件记录，不是独立硬件退休观测。

默认基线有人图Invoke190673191周期，总194501581周期；fast只有同模型/输入/RAM/时序的Invoke周期才宜直接作此层面的软件路径比较。墙钟速度受服务器负载影响，不是NPU频率。512KiB DTCM是总容量；arena测量不是全内存峰值，最低64字节canary也不是完整栈水位。Depthwise继续保持官方默认注册。

本地7项新合成验收/构建复用/证据防篡改测试通过，连同Pool工具共19项；代码未在本机实际访问服务器模型或运行RTL。Linux执行结果仍由服务器日志确认。
