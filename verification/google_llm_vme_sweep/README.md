# 单NPU INT8 Linear：M维度扫描候选

本候选仍为ITCM256KiB、DTCM512KiB、官方原RTL。K=N=64，M依次为1、2、4、8、12、16。
目的是测量这些离散M点上官方RVV与VME的交叉趋势，不是完整LLM或模型推理。

旧google_llm_vme_opt只有M=1/16进入直接写回快路径，其他M回退旧路径，不能直接拿来寻找矩阵快路径的切换点。
这里新建tests/cocotb/llm_vme_sweep_v1，让所有M1..16使用直接写回：
累加器有效token列得到正确补偿，矩阵命令限制有效列，msettn限制并恢复输出VL，仅存有效token。
M1初始化分支不变。原HardwareTile、旧候选、旧固件、已验收日志和RTL均不修改。

新代码**尚未经过RTL验证**。13组新候选探针覆盖M=2/4/8/12、M=7/15和K/N尾部，
通过前包装入口拒绝运行性能用例。既有9组探针不能替代本候选的新M快路径验证。
所有性能例必须fast_tiles命中、fallback_tiles=0，逐元素参考、签名、打包、guards、前门读回、无fault和自然halt均严格检查。

每个M在同一份新ELF中比较官方RVV、旧VME完整/复用、新VME完整/复用五条路径。
每路径首用一次、稳态三次；包含打包和复用排除打包分开，JSON另报告首用/四次摊销包含一次打包。
输入W[-127,127]、X[-128,127]，输出raw INT32；不含量化、激活或外部存储搬运。
每个形状的数据确定，同形状五条路径输入相同；不同M不是同一权重集的驻留复用实验。
不得拼接上一候选M1/M16的周期作为本次同ELF对照，也不插值宣称精确/通用切换阈值。

## 首次建议quick

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
git pull --ff-only origin main
bash verification/google_llm_vme_sweep/run.sh quick
)
```

quick先准备和构建，再运行13组新指令探针，最后只测M8。粗估20～45分钟仿真，准备/首次编译另计。
若通过，使用打印的LLM_VME_SWEEP_JOB_DIRECTORY继续，不重新准备：

```bash
bash verification/google_llm_vme_sweep/resume.sh /实际job目录 all
```

all为探针后6例串行，完整粗估80～180分钟，各例5～45分钟；已验收例重验后标记CASE_REUSED，不重复仿真。
单独选择probe或0..5；0=M1、1=M2、2=M4、3=M8、4=M12、5=M16。
失败保留原日志，修复需新版本；不中途放宽检查。默认每例3600秒超时不是预计耗时。
没有可靠VM墙钟测量前，上述ETA仅粗估。程序每次运行仍打印具体估计。

## 准备与溯源

run.sh不带参数或prepare仅执行native/链接/审计/导出/Bazel build，**不启动RTL仿真**。
materialize.py从固定个人仓库提交a2497c05e44e3e911c24a57e3100ab687992bf7d提取既有工具，
在唯一job/tools目录生成独立版本，严格匹配每处修改的模板，并保存父文件/生成文件SHA清单。
原依赖验证器、原RVV向量生成器、原模型只读复用证明不变；生成树不接受覆盖，恢复前后重新核验。
此方法避免复制和重新维护整套控制器，旧目录完全不改。生成工具树不可移除或单独挪动，否则无法复验旧结果。
服务器备用固件包由同一流程导出，仍不含RTL，必须独立新探针通过后才能测性能。

主机测试和目标机器码审计不是RTL正确性证明，任何性能结果都以用户实际运行后的严格PASS日志为准。
