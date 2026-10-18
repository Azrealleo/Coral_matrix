# 官方单NPU：ITCM容量实验

状态：仅新增阶段1工具，尚无本轮真实RTL PASS；Windows上的单元测试不能替代Ubuntu仿真。

本地验证：新增14项静态/合成检查通过，包含直接运行测试协程的正常、地址镜像和错误字节掩码反例；原DTCM工具64项通过，原VCS工具38项检查完成（其中2项可选依赖检查跳过）。新runner通过Git Bash语法检查。没有在Windows生成/仿真本轮RTL，也没有修改服务器任务。

沿用官方提交`8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`、团队两个补丁、单NPU和原实验地址图。DTCM固定2MiB，ITCM扫描8/16/32/64/128KiB，AXI外部取指开启，FetchL0关闭，其他RVV/VME/浮点参数与DTCM实验一致。这里的档位是本轮候选，不是宣称官方最大容量。

## 隔离和复用

默认复用`$HOME/coral_tcm_capacity_8e4_v1/source`、其Bazel9.1.0和缓存。只新增`tests/cocotb/itcm_capacity/`及独立`itcm_geometry_manifest.json`，不修改旧Core.scala、固件、DTCM测试文件或旧manifest，也不修改团队SoC仓库。避免再复制一整套依赖占满虚拟机磁盘。

安装前验证原DTCM实验指纹及同一实验2MiB阶段1实际PASS日志。新增文件与工具单独指纹化；已有目录没有manifest、已安装文件或工具发生变化均拒绝覆盖。运行目录`itcm_geometry_i<KiB>.XXXXXX`独立保存头文件、RTL哈希、日志、时间和失败退出状态。

同一source不可与其他生成/测试任务并行操作。请等虚拟机DTCM队列结束再更新个人仓库、启动本轮。`--noblock_for_lock`在Bazel忙时立即停止；不终止已有任务。不动服务器上已经运行的2MiB/T384。

## 阶段1：前门访问几何

通过原fixture顶层AXI访问，核保持停止：

- 每个8KiB ITCM切片的首/中/尾16字节，含首尾和各切片边界。
- DTCM首尾各一个16字节保护位置，检测ITCM/DTCM别名。
- 所有位置先全部写完再读回，检测高地址截断/镜像。
- ITCM首尾、DTCM首尾四处各做7字节非对齐写，验证字节掩码和相邻未写字节。
- 不发送跨4KiB非法burst、不访问未映射区、不假设RAM复位为零、不用DPI后门。

这不是March/MBIST，不是全地址穷举，没有启动指令执行，PASS仅代表选定位置的前门几何与掩码检查，不证明完整取指正确、性能收益、综合时序或真实SRAM宏可用。

先运行8KiB建立新包基线，通过后逐档执行：

```bash
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
bash verification/google_itcm_capacity/run.sh 8
# 收到完整PASS后再运行：16、32、64、128，一次一档。
```

6小时是每档测试保护上限，不是时间预测；首次生成/编译模型可能较久。关闭波形，Bazel不反复打印进度，错误不隐藏。

## 后续阶段（尚未实现/执行）

1. 小代码常驻控制：固定同一ELF、地址、输入和DTCM，记录内部周期。
2. 跨容量阈值代码工作集：8KiB内、跨8/16/32/64KiB的代码布局，设计本地/外部放置对照和输出校验，记录取指AXI事务、字节和执行窗口。ITCM不是自动缓存，不能简单假设8KiB之外会自动搬入ITCM；外部代码必须显式链接/装载到有效外部可执行地址，避免小ITCM下落入未映射空洞。
3. 明确外部取指延迟与带宽假设，后续用模型软件或真实SoC条件核对。

已有工作集固件指令加载段只有1664字节，能放入8KiB。单纯放大ITCM重跑同一小程序，通常只能作为控制，不能验证更大ITCM的性能价值。不改变时钟、DTCM、FetchL0或AXI取指开关后把差异归因于ITCM容量。
