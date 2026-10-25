# CoralNPU 当前交接指南：继续软件与 RTL 验证

更新：2026-10-25（香港时间）。对象是接替本项目软件/RTL验证工作的同学或后续助手；综合人员的旧RTL说明另见[专用交付](HANDOFF-simulated-rtl.md)。
当前状态以[进度](PROGRESS-current.md)、[证据索引](EVIDENCE-current.json)为准；全过程见[工作记录第30节](WORKLOG-and-handover.md#section-30)。旧版完整保留在[10月22日交接快照](HANDOFF-archive-20261022.md)，更早内容仍见[此前历史快照](HANDOFF-archive-before-llm-20261022.md)。

## 1. 接手后先读的结论

1. 团队已确定官方版本，当前只处理单NPU，ITCM256KiB/DTCM512KiB，不负责团队四核SoC签核。
2. 当前已通过高精度GELU、三算子链、真实投影的GEGLU FFN、单头Attention的prefill→一次decode；**Attention和FFN尚未连接为一层Transformer**。
3. 当前模型权重为合成FP32数据，不是完整预训练LLM；没有tokenizer、长序列生成、tokens/s或DRAM带宽结论。
4. 主机测试、ELF/指令审计、探针、性能例、严格数学质量是不同证据。原官方GELU三例只允许算法诊断，不能称等精度可替换。
5. 当前能从Windows直接SSH操作VM，一小时内仿真可在VM完成；旧“VM只导出、服务器必须仿真”的分工已解除。
6. 本次仅只读重新校验10个作业36条性能记录，没有新增仿真。先读已有结果，不默认重跑all或续旧容量扫描。

## 2. 固定身份与 RAM

| 项目 | 当前值 |
|---|---|
| 个人仓库 | [Azrealleo/Coral_matrix](https://github.com/Azrealleo/Coral_matrix)，最近代码`445c3d8`；本次文档提交另查git log |
| 团队仓库 | [cheshire-coral-soc/cheshire-coral-soc](https://github.com/cheshire-coral-soc/cheshire-coral-soc)，本工作不向其写入 |
| 官方实验源 | `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，不自动跟踪新上游 |
| 团队算子阅读快照 | `fa4b83e43bb0b1d58b18eb5f4c31d98ee4054123`，与实验源/个人工具提交分开 |
| 顶层 | `VmeCoreMini_ITCM256KB_DTCM512KBAxi` |
| RTL SHA256 | `477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2` |
| VM Verilator可执行文件SHA256 | `827680a52a5d3107cfaa3d123af533b9e9d208acf1b44d23a880833bbb09de6c` |
| ITCM | 256KiB，`0x00000000`～`0x0003FFFF` |
| DTCM | 512KiB，`0x01000000`～`0x0107FFFF` |
| CSR基址 | `0x02000000`，不等于团队最终SoC地址图 |
| 预留栈 | 16KiB，`0x0107C000`～`0x0107FFFF` |
| 数据通路 | XLEN32、RVV VLEN128、LSU/AXI数据128bit、AXI ID6bit |
| 开关 | RVV/VME/FP/BF16开启，AXI取指允许，FetchL0关闭，verification=false |

SRAM使用原逻辑/行为模型及原DPI语义，不是真实工艺宏或门仿；逻辑1RW、128bit数据、16bit字节mask、读响应一周期，不保证上电清零。具体bank组织以生成RTL/参数为准。bench行为时钟1.25ns只用于仿真周期计数，不能证明芯片800MHz或200MHz达标。

当前数据驻留TCM，未用完整LLM外部权重衡量DDR。栈底只查64字节canary，不是完整水位。改容量、开关、顶层/接口或RTL后，必须建立新模型、固件/探针身份；不能复用旧PASS冒充新配置。10月4日8/32KiB及prod包与当前配置不同。

## 3. 环境、目录与访问

| 环境 | 角色/路径 |
|---|---|
| Windows工作区 | `E:\Projects\矩阵二选一`；证据/导出在`handoff_output`，不将大构建放C盘 |
| Windows Codex数据 | 用户已迁至`D:\CodexData`；不把聊天附件当唯一长期证据 |
| VM入口 | `lqq@192.168.58.131:22`，地址可能随VM网络变化 |
| VM个人工具仓库 | `/home/lqq/桌面/Coral_matrix` |
| 本会话专用study | `/home/lqq/coral_tcm_capacity_8e4_v1`，其`source`为固定源及实验包 |
| VM工具 | `$HOME/miniforge3`的`coral-matrix`；study中Bazel9.1.0、既有bazel-user缓存 |
| Python依赖 | cocotb2.0.0、numpy1.26.4、pyelftools0.32、find-libpython0.5.1；以封存环境记录为准 |
| RTL仿真 | Verilator5.052；使用已验证模型，不因文档更新重编 |
| EDA152备选 | `lqq@172.27.127.152:22`，`/home2/lqq`解析到`/data/home2/lqq`，CentOS7/glibc2.17 |
| 服务器环境 | `$HOME/coral_vcs_tools/miniforge3`中的`coral-verilator`，旧VCS与其编译器配置分开 |

同一VM还有另一个聊天。用户已指定上述个人仓库、study及source供本会话使用；不停止其他人的进程，Bazel锁忙时等待/退出，不杀服务或清缓存。

Windows已可用的私钥文件名为`$env:USERPROFILE\.ssh\coral_npu_vm_ed25519`。它不在仓库/交接包中；接手人应取得自己的访问授权，不能指望clone后自动拥有密钥。

已有授权和known_hosts的机器可在PowerShell连接：

```powershell
ssh -i "$env:USERPROFILE\.ssh\coral_npu_vm_ed25519" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 lqq@192.168.58.131
```

Windows GitHub连接曾需当前本机代理`http://127.0.0.1:7908`。只在该代理确实运行时用逐命令`git -c http.proxy=http://127.0.0.1:7908 ...`，不关闭TLS验证、不改全局配置。该loopback地址不是VM/服务器可照抄的代理地址。

## 4. 接手第一步：只读重验最新作业

预计几秒至数十秒，**不构建、不启动RTL、不生成新summary目录**。以下在VM运行：

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
attn_job="$HOME/coral_tcm_capacity_8e4_v1/attention.iMVr0T"
attn_tools="$attn_job/tools/verification/google_attention_v1"
PYTHONPATH="$attn_tools" python -B - "$attn_job/prepared" <<'PY'
import sys
from pathlib import Path
import summarize
rows, _ = summarize.collect_vm(Path(sys.argv[1]), partial=False)
assert len(rows) == 3
for item in rows:
    row = item['observation']
    assert len(row['attention_stage_math_pass']) == 13
    assert all(row['attention_stage_math_pass'].values())
    assert row['cache_prefix_bitwise_retained'] and row['bulk_stream_math_pass']
    print(row['case'], item['comparison']['candidate_cycles'])
print('READ_ONLY_ACCEPTED: 3 cases; no new simulation')
PY
)
```

collector重新核对原始日志/XML/退出状态、探针关联、实际ELF、模型二进制、源码清单、调用/guard/输入输出及自然halt。失败就保留原目录排查，不手改manifest、SHA、fault或门限。

直接运行`summarize.py --vm-prepared ...`也不仿真，但会新建summary目录；只读审计优先用上面的collector。索引/E盘下载副本不是原始证明的替代。

## 5. 已验收作业及证据位置

根目录为`/home/lqq/coral_tcm_capacity_8e4_v1`，完成范围见[进度总表](PROGRESS-current.md)。

| 作业 | 冻结工具目录（job/tools/verification下） | 已验收性能case ID |
|---|---|---|
| `llm_vme_opt_session.cjfZc9` | 特例：使用个人仓库`verification/google_llm_vme_opt` | 0,1,2,3 |
| `llm_vme_m_sweep.AahVsZ` | `google_llm_vme_sweep_v1` | 0～5 |
| `llm_vme_large.UDDMQw` | `google_llm_vme_large_v1` | 0（共8例） |
| `llm_vme_mature.sdcZkW` | `google_llm_vme_mature_v1` | 0,3,4,5（共6例） |
| `llm_vme_pair.kudXJL` | `google_llm_vme_pair_v2` | 3,4,5（共6例） |
| `official_rvv.aI9wIK` | `google_official_rvv_v1` | 0～5；3～5仅算法诊断 |
| `gelu_rvv_mlas_v2.4yHOrK` | `google_gelu_rvv_mlas_v2` | 0,1,2 |
| `transformer_chain_v2.33mKyq` | `google_transformer_chain_v2` | 0,1,2 |
| `ffn.DkKE4z` | `google_ffn_v1` | 0,1,2 |
| `attention.iMVr0T` | `google_attention_v1` | 0,1,2 |

opt_session没有自含tools快照；需同时保留原个人仓库控制器及相应Git对象/提交。其余作业也依赖prepared记录中的原路径、source包、编译模型，不能只搬一个summary就宣称可复现。

每个job保留整个`tools`、`prepared/preparation.json`、`prepared/firmware`、`probe-proof.json`、`case*-proof.json`、`runs/*`及summary。run应含原始log/XML/退出状态、前后模型身份、probe关联和result。来源/包/模型变更必须新建身份。

最新四组精确目录：

| job短名 | 探针与三例runs短名 | 已有完整summary | E盘副本（handoff_output下） |
|---|---|---|---|
| `gelu_rvv_mlas_v2.4yHOrK` | `probe.wukje328`；`case0.zybppj9v`、`case1.07uc_qig`、`case2.qfb7re71` | `prepared/summary.g0elal4z` | `gelu_rvv_mlas_v2_4yHOrK` |
| `transformer_chain_v2.33mKyq` | `probe.s1sxdqk1`；`case0.67skppwj`、`case1.3k592no5`、`case2.gdiwxck6` | `prepared/summary.t_3bkqn8` | `transformer_chain_v2_33mKyq` |
| `ffn.DkKE4z` | `probe.j3t1x57d`；`case0.haqj125h`、`case1.d7bjm2n1`、`case2.3ume305b` | `prepared/summary.3sbrr2wx` | `ffn_DkKE4z` |
| `attention.iMVr0T` | `probe.z29k_brm`；`case0.6m84kfjn`、`case1.dhhqoj9q`、`case2.zwpqiuuy` | `prepared/summary.5ubqfxla` | `attention_iMVr0T` |

runs短名均在`prepared/runs/`下。GELU的E盘副本主要为summary/控制台；链和FFN有证据归档；Attention还备份固件源包及含实际ELF的证据归档。不能把这些副本笼统写成“所有历史完整日志均已下载”。

### 5.1 最新固件与ELF身份

| 模块 | ELF SHA256 | 固件归档SHA256 |
|---|---|---|
| 高精度GELU | `0a9d427597056b709cb7362eaac7eae6be29ae8b996419c9f09b8402987b7d47` | `79cefb956002469a4e7e609f656d22f6d94ae6f8f34e5b76d27c76814c05e769` |
| 三算子链 | `69cc3f8316715fce915af0a57ad56ec7d588d9ca74cac881b57e8856c827e955` | `0ed2267a1229b322bde002389ee20a3aa4e1e2b7e7b934b35d421496541b0cde` |
| FFN | `bf4040b8888d5250f294377caa9e0886e455e1e88899ac93c79c6f08b8a9501b` | `d8c2526d1aa8f92edf62bb3d0582f631f541dc639366ebd6b943b95449e5498d` |
| Attention | `4bca2e8f0229e5830d6cff0b64fd0ba9d73b296a294c6c32c9a40706f516526b` | `e8704de105aca92ce31531968d33d3b3de3ebe382391dbfcbbedff99423659e7` |

归档均在各job的`prepared/firmware/`下：`coral_gelu_rvv_mlas_i256_d512_v1.tar.gz`、`coral_transformer_chain_i256_d512_v1.tar.gz`、`coral_ffn_i256_d512_v1.tar.gz`、`coral_attention_i256_d512_v1.tar.gz`。前两者工具/源码版本为v2但包信封/文件名保留v1，两种版本维度不同。

这些小包不含RTL，准备manifest仍标NOT_RUN；PASS由后续独立证明承载，不回写旧包。其他作业的ELF身份见[EVIDENCE-current.json](EVIDENCE-current.json)。

### 5.2 最新资源

| 模块 | ITCM占用范围/字节 | DTCM静态范围/字节 | heap剩余/字节 |
|---|---:|---:|---:|
| 高精度GELU | 13808 | 26208 | 481696 |
| 三算子链 | 14864 | 33472 | 474432 |
| FFN | 16064 | 33536 | 474368 |
| Attention | 18272 | 37264 | 470640 |

各例另外预留16KiB栈；这些是当前benchmark ELF资源，不是完整模型arena或动态栈峰值。不要据小例直接缩减团队SRAM配置。

## 6. 当前下一项：连接一层Transformer

1. 新建独立包，不原地改attention/ffn已封存源码。两者目前只分别通过，没有现成整层PASS。
2. 让FFN消费Attention的残差输出，采用各自明确的RMSNorm参数；保留真实数据依赖、KV与绝对位置。
3. 建独立整层参考，校验中间张量/缓存/guards，保留同ELF scalar/project/candidate对照。
4. 准备只做native、交叉链接、资源/指令/RTL身份审计。新探针通过再跑单个小性能例。
5. 每次启动前先给ETA、编译是否另计和不确定性；整层尚未构建，不能直接承诺沿用5分钟。

大尺寸VME、BF16/INT4、外部AXI/DRAM、真实权重/tokenizer、长序列、PPA和门仿各自另立验证。不要自动恢复large剩余7例、mature的M2/4、pair的M1/2/4或旧TCM长队列。

## 7. 可选复现与恢复规则

现有PASS无需重跑。若明确需要新一轮Attention复现，VM个人仓库干净且网络可用时先`git pull --ff-only origin main`，完整历史需含固定父提交；再执行仅准备命令：

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
export PYTHONDONTWRITEBYTECODE=1
bash verification/google_attention/run.sh
)
```

这会产生新的ATTENTION_JOB_DIRECTORY，只做构建/导出，不仿真。保留打印路径；之后若决定运行新job的quick，估计1～5分钟，编译另计；三性能例参考本VM实测约5分10秒，整套加探针/核验可先预留6～12分钟，负载和变更需重估。

```bash
# 仅用于明确决定复现后打印出的新job，不是默认接手第一步。
bash verification/google_attention/resume.sh /替换为新job目录 quick
```

其他新候选入口同样为各自`run.sh`准备、`resume.sh JOB ...`显式仿真。接受证明存在时序列会重验并复用；不能把旧已通过job当复测空壳。中断后的新attempt从固件入口重跑，不是CPU checkpoint。

保留失败目录。身份失配先检查路径、source、控制器和模型；不要修改哈希绕过。数值/fault失败先定位，不反复碰运气。`WAVES`、`GUI`、profiling保持unset，字符串0也可能触发无trace模型错误。不要混用VCS与Verilator编译器配置。

## 8. 必须随交接保留的材料

- 个人仓库、Git提交历史，以及`.upstream-git/coralnpu-google.git`的锁定源对象；私有访问凭据通过授权渠道处理，不写进Git。
- VM整个专用study的source/生成manifest、所有相关job/tools/prepared和失败记录。准备记录中的绝对路径暂保持。
- 原Verilator可执行文件和构建记录。实际模型路径从`prepared/preparation.json`的`model`读取，SHA应匹配第2节；不要清bazel-user导致模型丢失。
- 所有源包/ELF/参数/资源、原始日志/XML/状态、probe/case证明、summary。E盘副本按第5节范围交付，不以summary代替完整证据。
- 服务器历史21例、Pool编译模型/probe、Person/Conv/TCM的原文件若要继续相关任务，需另外归档，不是本次已全部回收。
- 若给综合/门仿组员交付，另给对应参数的RTL/约束/存储模型及该配置测试报告。当前小固件包不含RTL，旧8/32KiB包不能替代256/512KiB。

接手成功最低标准：能解释当前范围及缺口、定位准确job/ELF/模型/probe，运行第4节只读重验三例；知道当前没有整层/完整LLM PASS，不将旧官方GELU算法诊断当严格精度通过；能新建实验而不改旧包。

本机尚有与本次无关的`.gitignore`修改、旧RTL归档、SRAM说明、rtl_handoff和材料目录，不批量git add/clean或删除。只提交明确的本次文件。

## 9. 历史材料与常见误读

- [全程记录](WORKLOG-and-handover.md)保留早期错误、TCM、服务器后端、Person以及旧任务的当时状态；最新以第30节为准。
- [原21例](google_llm_ops/RESULTS-20261022.md)来自用户服务器输出，本次未重新登录EDA152验收其原始文件。服务器根目录仍为`/data/home2/lqq/Desktop/coral_person_packages`。
- 21例完整job为`llm_fab74b4f/coral_llm_ops_i256_d512_v1_server_runtime/jobs/operators.cgtja4_x`；`operators._jxei5s3`只是旧单例pilot。
- 原服务器Pool模型在`pool_7c8e0fe5/coral_person_vme_pool_i256_d512_v1_verilator_runtime/builds/7a54106b3148.z558xni8`。服务器使用新候选仍需该宿主机的新探针，不能拿VM probe冒充。
- 微基准CPU墙钟、NPU mcycle、假设频率换算和DC/STA是不同口径。没有tokens/s或200MHz签核结论。
- 部分原始字段沿用official_*，在独立候选中代表candidate；Attention的kind=GEGLU也是旧Case标签，不用于实际调度。以scope、stage和入口代码为准，没有偷偷执行GELU。
- 候选README可能参与冻结输入身份，保留准备时文字；日常结果新增在独立RESULTS/作业证据。只有用户要求时集中更新本组总文档。

<a id="server-verilator-2m-pilot"></a>
<a id="server-verilator-t384"></a>

旧TCM链接仍有效，请转到[历史2MiB步骤](HANDOFF-archive-before-llm-20261022.md#server-verilator-2m-pilot)或[历史T384步骤](HANDOFF-archive-before-llm-20261022.md#server-verilator-t384)，不要将它们当当前默认任务。
