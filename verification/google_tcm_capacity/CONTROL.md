# 阶段2a：同一小工作集的计算控制组

## 目的和状态

阶段1六档容量抽样检查已由用户在Ubuntu执行并回传PASS，见[结果记录](STAGE1-results.md)。本阶段先确认新团队基线能够执行signed-INT8矩阵程序，并建立同ELF、同输入、同数据地址的计算周期控制组。

**交付时状态：20项本地静态/合成测试通过，Bash语法检查通过；阶段2a的RISC-V交叉编译和实际RTL仿真尚未执行，不能提前声称PASS。** Windows没有可用的该交叉工具链/Verilator环境；最终以Ubuntu结果为准。

此控制组全部数据装得下32KiB，不测试容量阈值，不应据此得出“扩容没有意义”。扩容收益需要后续大工作集和实际NPU搬运策略实验；本阶段也不是完整模型推理。

## 不改已验证的实验源码

保留同一`source/`的官方提交、团队补丁、地址图、生成参数和ITCM=8KiB，不修改任何阶段1受校验文件或manifest。`prepare_control.py`在单独`tests/cocotb/tcm_control/`下增加测试包；原容量脚本仍可复查运行。

安装前要求六档都有匹配阶段1manifest、实际完整test.log和参数头的PASS记录。脚本不会以本说明表格或聊天摘要代替运行证据。已有控制组会检查指纹后复用；遇到残缺安装/篡改会停止，不删除或覆盖。

每档控制包以阶段1相同生成参数重新emit RTL及生成模型（不是复用旧870版本）。会有新的目标编译开销，但共用已下载依赖、Scala编译和Bazel9.1缓存。只跑一个单NPU容量，不是同时例化六个NPU。

## 工作负载与装载

- 固定16×16输出，Tk=4，signed A/B，K=16/64/256；另有signed边界值K=16用例，共4个用例，每个复位重跑3次。
- 同一`control_program.elf`目标服务所有容量，`-O2`，ITCM8KiB/DTCM32KiB链接配置。不是给每种容量重链接不同栈顶或数组布局。
- 输入A转置打包为K×16、B为K×16；累加和INT32输出与NumPy先扩展INT64再矩阵乘的golden逐元素比较，禁止INT8中间溢出。
- 两个保留输入数组各4160字节，输出1024字节，共9344字节；K=16/64/256的实际矩阵数据分别1536/3072/9216字节。ELF还包含状态/CRT/堆栈，不能把9344字节当作整个ELF占用。
- 检查所有ELF加载段局限于ITCM8KiB和DTCM低32KiB，核对数组/状态符号的大小、对齐及不重叠。保留ELF和运行日志中的符号表/加载段。
- `COCOTB_USE_FRONTDOOR=1`强制前门AXI装载ELF和数据，不依赖旧地址映射的DPI后门。装载前以合法32bit NOP填满ITCM，避免随机指令尾部影响前端预译码。输出预填毒值防止未写出结果误过。

## 周期口径

`wait_for_halt_cycles`来自固定官方fixture的`run_to_halt()`：先`execute_from()`写启动CSR，随后`wait_for_halted()`计数直到halt。包含计数窗口中的CRT/配置/向量加载/矩阵运算/读出存储/结束；**不包含主机装载ELF、写输入、读golden或全部启动CSR事务**，不是纯矩阵阵列延迟，也不是含数据搬运的模型端到端时间。

每次均须核心无fault、状态完成、mtype/vtype正确、256输出元素正确，三个重复周期完全一致。保留ELF SHA、输入golden哈希、符号地址和加载段；跨容量比较器强制这些相同，不默认取最小周期或混用不同软件布局。

不同容量周期若相同，是此固定小工作集/一周期行为RAM模型的控制结果；并不证明工艺宏大小对200MHz时序、功耗或大模型无影响。外部AXI事务/字节统计及带宽/延迟敏感性会在后续大工作集阶段加入，此控制组未交付那些指标。

## Ubuntu执行：先32KiB

保持原来可用的下载代理，串行执行。已保存的源码和容量日志都不需要重新clone。

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
if [ -n "$(git status --porcelain)" ]; then
    git status --short
    echo '存在未提交修改，停止，不自动覆盖。'
    exit 1
fi
git pull --ff-only origin main
python -B -m unittest discover -s verification/google_tcm_capacity -p 'test_*.py' -v
bash verification/google_tcm_capacity/run_control.sh 32
)
```

关闭频繁进度刷新，但保留阶段提示、警告和错误。先确认32KiB成功，再单档调用128/512/1024/2048/4096，不整段盲跑。

成功标志：4行`[TCM_CONTROL_SUMMARY]`、cocotb1/1 PASS、最后`[TCM_CONTROL_PASS]`。成功运行目录为`$HOME/coral_tcm_capacity_8e4_v1/control_d32.XXXXXX`等，保存阶段1/阶段2manifest、Bazel版本、构建命令与日志、参数头、ELF、SV/头/ELF hash、test.log和摘要。失败回传第一个错误和`[TCM_CONTROL_RUN_DIRECTORY]`；不要清空旧目录。

后续至少两档都有成功原始日志后，可显式传入各自的完整路径进行比较：

```bash
python verification/google_tcm_capacity/prepare_control.py compare \
  --logs /实际/control_d32.XXXXXX/test.log /实际/control_d128.XXXXXX/test.log
```

这里的`/实际/...`是占位符，必须替换为真实结果目录，不要直接照抄。比较器从完整日志重新检查算术验证标志、范围、次数、哈希和周期；同一容量重复传入会拒绝。
