# 官方单核 ITCM/DTCM 容量实验（2026-10-14）

团队已选官方矩阵版本，不再运行fork对比。单位固定为KiB/MiB；本轮2M/4M分别是每个DTCM的2MiB/4MiB。先固定ITCM=8KiB，DTCM扫描32/128/512/1024/2048/4096KiB；不测试4核SoC，不修改团队已通过的单核SoC基线。

## 基线和本阶段范围

- 团队仓库固定`95e06e872bff13b3625721a837b4b739a93bed6f`，官方源码固定`8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，Bazel9.1.0。
- 保留团队CSR排序和cvfpu sticky位宽两个生成补丁，以Git对象读取并验证原始补丁SHA；不复制旧`870993f7`产物来冒充新基线。
- 保持RVV/VME/FP/BF16、VLEN128、外部取指true、FetchL0=false、verification=false和读一周期/128bit/byte mask。没有选择高容量verification目标改变ROB配置。
- **当前交付是阶段1：容量配置及正面AXI RAM检查，不是矩阵性能结果。** Windows只执行本地静态/合成自测；Bazel9生成、Verilator冷编译和实际RTL仿真需要Ubuntu执行。还没有新容量PASS。

本地验证：8项几何/独立向量/参数/BUILD语法/假fixture正反控制/日志解析测试通过；另在临时稀疏Git副本用真实`8e4df09b`和团队真实补丁核验完整prepare、六package/22文件校验、拒绝覆盖和篡改检测；Git Bash `bash -n`通过。这些都不是实际SV编译或RAM仿真PASS。

## 实验地址图

原生成器非默认容量的highmem图DTCM始于1MiB，CSR在2MiB，因此DTCM2MiB/4MiB会覆盖CSR。实验副本将所有容量（含32KiB控制组）统一为：

| 区域 | 起点 | 容量 |
| --- | --- | --- |
| ITCM | `0x00000000` | 8KiB |
| DTCM | `0x01000000` | 扫描容量，最大4MiB |
| CSR | `0x02000000` | 4KiB |
| 仿真外部memory | `0x20000000` | fixture默认4MiB |

这些是**单核实验地址，不是Cheshire接口修改提案**。`Core.scala`只改EmitCore生成区域，计算核逻辑不改；`rules/linker.bzl`同时改default/highmem DTCM原点，未来实验ELF必须与之相同。此前SoC主窗口仅256KiB、NPU主口白名单仅共享SPM128KiB，不能把本轮扩容配置直接塞进原SoC，也不据隔离仿真声称已经加速SoC/DDR。

默认每个bank仍512×128bit=8KiB；2MiB为256bank，4MiB为512bank。这是容量组织实验，不代表一颗2/4MiB工艺宏，不增加独立访问端口。宽mux/fanout的实际时序及不同宏延迟以后由综合和工艺验证评估，行为仿真不会自动体现这些代价。

## 阶段1判据

通过顶层AXI访问ITCM首尾和DTCM**每bank首、中、尾**16字节。所有位置先写完再全部读回，地址值编码在数据中，检测高地址截断/镜像；首/末bank分别做7字节掩码写并检查相邻字节不变。bank边界用分开的合法AXI事务，不发送跨4KiB非法burst。复位不假定RAM为零；不启动计算核、不用DPI后门装载、不把这些AXI读写耗时作为计算性能。

必须Bazel test PASS、cocotb1/1且FAIL/SKIP=0、完整marker、正确容量/顶层/检查数；生成参数头也必须吻合。程序对已有实验源码/工具指纹变动拒绝复用，不清理或覆盖旧结果。修改实验工具后要指定新的实验目录。

## Ubuntu运行（先32KiB）

在此前Ubuntu虚拟机，保留可用代理；需要当前账号能用Git读取团队私有仓库（两个补丁来源）。不在EDA152/CentOS上执行，也不要在Windows大小写不敏感文件系统生成官方源码。

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
if [ -n "$(git status --porcelain)" ]; then
    git status --short
    echo '存在未提交修改，请先核查，不自动覆盖。'
    exit 1
fi
git pull --ff-only origin main
python -B -m unittest discover -s verification/google_tcm_capacity -p 'test_*.py' -v
bash verification/google_tcm_capacity/run.sh 32
)
```

脚本在`$HOME/coral_tcm_capacity_8e4_v1`建立新官方源码实验副本、团队只读bare副本、单独Bazel9.1.0和缓存。不会覆盖此前`coralnpu-google/`或改Conda里的Bazel8.6。首次下载/编译可能较慢，jobs和make都限制2；Java堆2GiB，Bazel本地memory预算4096MiB。此预算不是峰值内存保证，若VM资源不足可降低并行或扩内存，不能清空历史日志掩盖OOM。

32KiB实际通过后再逐档运行，**一档成功后才运行下一档**：

```bash
bash verification/google_tcm_capacity/run.sh 128
bash verification/google_tcm_capacity/run.sh 512
bash verification/google_tcm_capacity/run.sh 1024
bash verification/google_tcm_capacity/run.sh 2048
bash verification/google_tcm_capacity/run.sh 4096
```

不要整段粘贴后忽略中间失败。每次run有独立目录，保存来源manifest、实际源diff、Bazel版本、命令/生成日志、参数头、SV/ZIP参数头hash、test.log、严格摘要。将`[TCM_GENERATED_PARAMETERS]`、`[TCM_CAPACITY_SUMMARY]`、`[TCM_STAGE1_PASS]`回传；失败则回传第一个错误和`[TCM_RUN_DIRECTORY]`。

## 接下来才测性能

容量资格通过后，增加同一signed-INT8矩阵内核及正确INT32 golden的三类工作集：全部容量都装得下的小控制组；跨容量阈值的大数据；重复使用权重的多输出tile。软件需要显式选择驻留/分块搬运；不能固定`.extbss`仍全在外部，就把扩容无收益当结论。按同源/编译选项/输入比较，记录ELF布局、tile/K、实际驻留字节、分块策略、复制开销、执行周期、外部读写事务/字节、重复一致性。区分预载后compute窗口与包含NPU搬运的端到端窗口。

外部memory先采用相同理想模型作控制，再加明确的延迟/带宽敏感性；例如不同读响应延迟是实验假设，不代表真实SoC SRAM/DDR。ITCM扩容另开一轮独立变量，不能与DTCM同时变化后归因。频率固定假设下可换算周期时间，但200MHz可达性、RAM面积和能耗没有因本轮仿真得到证明。
