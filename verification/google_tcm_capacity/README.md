# 官方单核 ITCM/DTCM 容量实验（2026-10-14）

团队已选官方矩阵版本，不再运行fork对比。单位固定为KiB/MiB；本轮2M/4M分别是每个DTCM的2MiB/4MiB。先固定ITCM=8KiB，DTCM扫描32/128/512/1024/2048/4096KiB；不测试4核SoC，不修改团队已通过的单核SoC基线。

## 基线和本阶段范围

- 团队仓库固定`95e06e872bff13b3625721a837b4b739a93bed6f`，官方源码固定`8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，Bazel9.1.0。
- 保留团队CSR排序和cvfpu sticky位宽两个生成补丁，以Git对象读取并验证原始补丁SHA；不复制旧`870993f7`产物来冒充新基线。
- 保持RVV/VME/FP/BF16、VLEN128、外部取指true、FetchL0=false、verification=false和读一周期/128bit/byte mask。没有选择高容量verification目标改变ROB配置。
- **阶段1六档容量检查和阶段2a六档小工作集控制组均已收到Ubuntu实际RTL仿真PASS摘要，六份控制组完整日志也已在Ubuntu比较通过**，见[容量记录](STAGE1-results.md)与[计算控制组记录](CONTROL-results.md)。小控制组各档周期相同，尚无大工作集扩容收益结论。
- [阶段2b固定调度权重驻留实验](WORKSET.md)已收到32/128KiB及1MiB、T12、等待0的Ubuntu实际RTL PASS。32/128KiB两份完整日志已在Ubuntu通过跨容量比较器复核；同一prefix策略扩容后少29.32%周期，权重读取从120KiB降至48KiB。后补1MiB测试耗时292.4秒、内部CSR周期/流量与128KiB完全一致，等待halt窗口多3周期，原因未定位；没有额外容量收益证据。见[工作集结果及MiB级测试计划](WORKSET-results.md)。这不是整模型或2/4MiB收益结论。
- 2026-10-17新增[独立VCS包入口](../google_tcm_vcs/README.md)：1/2/4MiB均已实际导出并核对RTL/固件字节，服务器不需要Bazel。1MiB使用系统GCC与独立Conda DPI编译器后VCS编译通过；通过包外SGR兼容与加载段表示修复，现已收到T12/等待0的TCM_VCS_ACCEPT_PASS，原日志不改、原仿真不重跑，两条汇总与Verilator一致。VCS流程墙钟1185.423秒、Ubuntu测试292.4秒，不证明仿真器本身速度比，但建议大工作集主线优先使用Ubuntu。2/4MiB服务器编译/运行待验证。详见[导出记录](../google_tcm_vcs/EXPORT-results.md)；不修改本目录已安装的基线或旧结果。

本地验证：10项几何/独立向量/参数/BUILD语法/假fixture正反控制/日志解析及SSH入口、进度输出静态测试通过；另在临时稀疏Git副本用真实`8e4df09b`和团队真实补丁核验完整prepare、六package/22文件校验、拒绝覆盖和篡改检测；Git Bash `bash -n`通过。这些都不是实际SV编译或RAM仿真PASS，也不证明Ubuntu的SSH网络和账号权限已通过。

新增计算控制组后，本地测试共20项（包括合成fixture算术正反控制、低32KiB ELF布局、重复结果/哈希严格解析及不覆盖阶段1的安装校验），全部通过。已准备好的阶段1副本及其工具指纹没有改变，不必重跑容量检查。

修正RISC-V配置切换后的ELF输出路径定位后，本地测试增至26项并全部通过，Ubuntu六档控制组亦已回传PASS；详见[计算控制组说明](CONTROL.md)。

新增工作集实验后，本地共42项静态/合成检查通过；旧阶段的生成器、内核和已安装工具指纹保持不变。共享ELF解析器只增加可选`workset_program.elf`文件名，默认旧控制组行为不变。

补充Python缓存局部忽略和Git回归检查后共43项本地测试通过。只忽略本验证目录内的`__pycache__/`、`.pyc`、`.pyo`，保留真实源码修改的干净工作区检查，不需要删除缓存或改全局Git设置。

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

### 团队仓库改用SSH（2026-10-15）

脚本默认仅将团队私有仓库改为`git@github.com:cheshire-coral-soc/cheshire-coral-soc.git`，个人仓库pull、官方公共源码及Bazel下载仍走HTTPS。已有`team.git`即使origin是HTTPS，也通过显式SSH URL fetch固定提交，无需删除副本或修改全局Git配置。不是bare仓库的已有同名路径会停止并保留，不能直接删掉重试。

在**Ubuntu**生成专用密钥，已有同名密钥不覆盖：

```bash
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
if [ -e "$HOME/.ssh/id_ed25519_coral_tcm" ] || [ -e "$HOME/.ssh/id_ed25519_coral_tcm.pub" ]; then
    echo '同名密钥已存在；不覆盖，请先核查。'
else
    ssh-keygen -t ed25519 -C 'Azrealleo-coral-tcm-vm' -f "$HOME/.ssh/id_ed25519_coral_tcm"
fi
```

建议设置密钥口令。把`cat "$HOME/.ssh/id_ed25519_coral_tcm.pub"`显示的**公钥**加入个人账号Azrealleo的[SSH keys](https://github.com/settings/ssh/new)，Key type选Authentication Key。不要上传无`.pub`的私钥或贴到聊天中；这是个人账号认证，不需要审批那个Pending PAT，但账号必须已有团队仓库读权限，组织启用SAML SSO时还需授权SSH key。

然后在同一Ubuntu终端执行：

```bash
eval "$(ssh-agent -s)"
ssh-add "$HOME/.ssh/id_ed25519_coral_tcm"
export GIT_SSH_COMMAND="ssh -i '$HOME/.ssh/id_ed25519_coral_tcm' -o IdentitiesOnly=yes -o ConnectTimeout=15"
ssh -i "$HOME/.ssh/id_ed25519_coral_tcm" -o IdentitiesOnly=yes -o ConnectTimeout=15 -T git@github.com
# 上一条成功认证通常仍返回1，因此不要放进set -e串行区块。
git ls-remote git@github.com:cheshire-coral-soc/cheshire-coral-soc.git HEAD
```

首次连接必须核对[GitHub官方指纹](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)，ED25519为`SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`，匹配后才输入yes。`Hi Azrealleo! ... successfully authenticated`只证明个人SSH认证；`ls-remote`输出HEAD哈希才证明该仓库访问也通过。

如果22端口超时，可按[GitHub官方443方案](https://docs.github.com/en/authentication/troubleshooting-ssh/using-ssh-over-the-https-port)单独检查：

```bash
ssh -i "$HOME/.ssh/id_ed25519_coral_tcm" -o IdentitiesOnly=yes -o ConnectTimeout=15 -T -p 443 git@ssh.github.com
export TCM_TEAM_URL='ssh://git@ssh.github.com:443/cheshire-coral-soc/cheshire-coral-soc.git'
git ls-remote "$TCM_TEAM_URL" HEAD
```

443成功后保持上述环境变量再运行容量脚本；不改`~/.ssh/config`。SSH不会自动使用`HTTP_PROXY/HTTPS_PROXY`；443也超时则先诊断网络，不清理缓存或更改仓库可见性。新终端需重新设置`GIT_SSH_COMMAND`；若选443还需重新设置`TCM_TEAM_URL`，有口令的key可重新加入当前ssh-agent。

### 启动控制组

确认上述`git ls-remote`成功，在**同一终端**执行：

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

构建和测试统一使用`--noshow_progress`，关闭频繁重复的Analyzing/进度刷新，保留警告、错误、工具输出和最终结果。每个阶段开始打印一次`[TCM_STAGE]`，没有新输出不等于任务卡住。此调整只涉及运行脚本，不改RTL或实验源码指纹；已启动的命令不会自动改变输出，下一次拉取并运行才生效。

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
