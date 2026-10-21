# 服务器Conv单算子周期：复用现有编译模型

先按README在VM导出小包，再按实际归档SHA传输、校验和解包到独立目录。原Pool包`/data/home2/lqq/Desktop/coral_person_packages/pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1`与其runtime保持不变。新小包不含RTL；其qualified_model.py只读取原producer构建记录、配方和二进制身份，不运行完整模型入口。

把实际小包目录填入pd_packet；不要填成原Pool包或包内source目录：

```bash
(
set -eo pipefail
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-verilator
unset WAVES GUI COCOTB_ENABLE_PROFILING
export CC="$CONDA_PREFIX/bin/gcc"
export CXX="$CONDA_PREFIX/bin/g++"

pd_packet=/ABSOLUTE/PATH/coral_person_conv_v1
pd_rtl=/home2/lqq/Desktop/coral_person_packages/pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1
pd_probe="${pd_rtl}_verilator_runtime/runs/probe.46bl5uqr"
pd_python="$CONDA_PREFIX/bin/python"
pd_job=$(mktemp -d "$HOME/coral_vcs_tools/conv_pilot.XXXXXX")
printf '[PERSON_CONV_CONSOLE_LOG] %s/console.log\n' "$pd_job"
{
  "$pd_python" -B "$pd_packet/server_conv.py" --packet "$pd_packet" \
    --rtl-package "$pd_rtl" --probe-run "$pd_probe" check --case 0
  "$pd_python" -u -B "$pd_packet/server_conv.py" --packet "$pd_packet" \
    --rtl-package "$pd_rtl" --probe-run "$pd_probe" run --case 0 --cycles 2000000 --timeout 1800
} 2>&1 | tee "$pd_job/console.log"
)
```

这是前台运行，只跑id0，一次首次调用+三次steady，准备/检查也会执行但不计入各自Invoke窗口。没有Bazel、没有RTL重编、没有完整网络，不自动运行其他case。2百万周期与1800秒是停止上限，不是耗时承诺；预算不足会保留日志并停止，不当通过。

需同时验证native签名、逐项输出检查计数、4次VME调用/0fallback/0mismatch/0内部reference校验、8软件矩阵发射、原小模型/输入读回、自然halt/无fault、栈底64字节canary及4+4组实际NPU周期。XML单独PASS不足，parent最终需输出PERSON_CONV_RTL_PASS。

PERSON_CONV_CYCLE_COMPARISON中first_ref_over_vme是首次比值；steady_ref_over_vme是后三次reference周期之和除以VME周期之和，原始三次周期也保留。大于1才是加速，小于1表明该形状当前VME路径更慢，同样是有效数据。边界成本单独报告，不暗中扣除；矩阵计数为软件发射，不是独立退休。不要拿仿真墙钟或本片段周期去除整网190673191周期。

结果写在小包同级`coral_person_conv_v1_runtime/runs/case0.*`；原编译模型和指针不写。包/构建环境/短测证据变化或锁被占用则停止，请回传错误，不清缓存/改manifest/杀别人进程。其他4例是否跑、需要多大预算，等id0实际结果再决定。
