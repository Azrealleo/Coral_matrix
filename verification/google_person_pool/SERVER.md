# 新VME+RVV Pool包的服务器短验证

先在VM运行README的export.sh，回传归档路径/SHA，再按该实际SHA传输。不要覆盖旧默认包或旧VME包，不改包内manifest/SHA清单。新包内含已经测量的validate/fast整网ELF，但本节只验证真实RVV池化算术。

收到并校验解包后的新包后，把绝对路径填入 `pd_package`（末尾目录应是 `coral_person_vme_pool_i256_d512_v1`）：

```bash
(
set -eo pipefail
source "$HOME/coral_vcs_tools/miniforge3/etc/profile.d/conda.sh"
conda activate coral-verilator
unset WAVES GUI COCOTB_ENABLE_PROFILING
export CC="$CONDA_PREFIX/bin/gcc"
export CXX="$CONDA_PREFIX/bin/g++"

# 替换为本次实际解包目录，不是旧VME包的目录。
pd_package=/ABSOLUTE/PATH/coral_person_vme_pool_i256_d512_v1
test -d "$pd_package"
pd_python="$CONDA_PREFIX/bin/python"
pd_job=$(mktemp -d "$HOME/coral_vcs_tools/person_pool_probe.XXXXXX")
printf '[PERSON_POOL_CONSOLE_LOG] %s/console.log\n' "$pd_job"
{
  "$pd_python" -B "$pd_package/server_probe.py" --package "$pd_package" verify
  "$pd_python" -B "$pd_package/server_probe.py" --package "$pd_package" check
  "$pd_python" -B "$pd_package/server_probe.py" --package "$pd_package" build --jobs 2 --timeout 3600
  "$pd_python" -B "$pd_package/server_probe.py" --package "$pd_package" probe --cycles 2000000 --timeout 1800
} 2>&1 | tee "$pd_job/console.log"
)
```

这是显式前台运行，tee只记录日志。全新私有运行目录/构建身份，不占用旧包的current_build指针或写旧构建目录。首次编译可参考旧同RTL模型约8分钟，但只是估计；probe会自然结束，不一定跑满200万周期。不要把8组Pool检查与此前8组VME检查混为一谈。

必须有 `[PERSON_POOL_HARDWARE_PROBE_PASS] full_model_inference=NOT_RUN` 才是短Pool硬件通过，且需659输出/0错误/62向量块/签名642806987/自然halt/无fault/栈底canary等严格验收。XML或日志单个PASS字样不足。probe是重启后的短固件，不是旧长模型任务的checkpoint；栈检查只有最低64字节，并非完整水位。

`validate`用于整网逐层正确性，`fast`用于避免重复reference计算后的性能；**包内server_probe入口仍不支持两者的整网infer**。当前已新增[包外完整模型入口](MODEL.md)，使用已测量的两份ELF和通过短probe的同一编译模型，严格核对构建与结果，不需要重新导出/修改原包。不能用旧默认runner对新包强行换ELF。完整推理的两图分数仍应为有人[-113,113]、无人[57,-57]，Depthwise仍保持官方默认。
