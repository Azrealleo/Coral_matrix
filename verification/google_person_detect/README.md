# 当前主线：预训练二分类MobileNetV1 / Person Detection

2026-10-19。用户同意先跑完整预训练“有人／无人”网络，以降低完整RTL仿真成本，再考虑1001类网络。单官方NPU、DTCM512KiB、ITCM实际评估且<=512KiB、优先Verilator；外存未定时允许AXI行为存储。历史1001类模型、主机golden和容量实验保留，不覆盖。

**2026-10-20更新：用户在Ubuntu虚拟机完成原生TFLM两张图片测试及NPU固件交叉编译/ELF资源审计，均通过。** 桌面LiteRT加载失败仍保留；实际arena使用量、栈水位与NPU RTL推理仍未执行。详见[本轮结果](FIRMWARE-results.md)。下一步导出ITCM256KiB / DTCM512KiB的新RTL和原样ELF；本目录不是已有的NPU推理PASS报告。

## 固定来源与模型

选用CoralNPU固定提交`8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`本身依赖的TFLite Micro提交`b75c6ff4e2270047f2b48fa01f833c8101c31f43`，不浮动到另一套训练权重或更换运行时源码。

- [原始模型](https://github.com/tensorflow/tflite-micro/blob/b75c6ff4e2270047f2b48fa01f833c8101c31f43/tensorflow/lite/micro/models/person_detect.tflite)，300568字节（293.52KiB）。
- 模型SHA256：`808cfdfc0cf3a6fa6f6fa26bfa379ea97c16d5db7334637766e39c3408502e9d`。
- [官方测试及算子注册](https://github.com/tensorflow/tflite-micro/blob/b75c6ff4e2270047f2b48fa01f833c8101c31f43/tensorflow/lite/micro/examples/person_detection/person_detection_test.cc)，[模型类别约定](https://github.com/tensorflow/tflite-micro/blob/b75c6ff4e2270047f2b48fa01f833c8101c31f43/tensorflow/lite/micro/examples/person_detection/model_settings.h)。0=no_person，1=person。
- 输入INT8 `[1,96,96,1]`，9216字节，scale=0.007843137718737125、zero_point=-1。
- 输出INT8 `[1,2]`，scale=1/256、zero_point=-128。不是1001类模型直接删输出，也不是团队未训练诊断图。
- 31算子：DEPTHWISE_CONV_2D=14、CONV_2D=14、AVERAGE_POOL_2D/RESHAPE/SOFTMAX各1。首层是depthwise、depth_multiplier=8，其余depthwise倍率1；不能直接套用团队通道一一对应的depthwise代码。
- 去重常量buffer218928字节，最大特征INT8 `[1,48,48,16]`=36864字节，单算子非恒定输入输出不别名相加最大55296字节。这不是实际TFLM arena或运行内存峰值。
- 原始有人/无人BMP及SHA固定在`spec.py`。官方生成器将解码后的BMP字节直接memcpy到INT8输入；这些样本已经是张量编码，**不再减128**。不要把该规则套到任意普通照片的预处理上。

Windows原始资产缓存`.upstream-git/model-cache/person_detect_b75c6ff4`，与1001类缓存分开；二进制不提交。`fetch.py`校验三份原始文件，已有文件仅核验，不覆盖。

## 已发现的主机兼容问题（保留失败）

原模型14个depthwise bias张量为一维，但quantized_dimension=3。当前固定桌面LiteRT2.1.4在创建Interpreter时拒绝（Tensor33/36/40等；`quantized_dimension must be in range [0,1). Was 3`），尚未invoke，未产生参考PASS。官方主分支模型的Git blob也仍为`8159d01e5b5971605fbd2d8a22d16a74b4ec178b`，与本原始文件相同。

**没有改量化轴、权重或模型SHA，没有用另一个模型冒充原模型。** `reference.py`保留原始路径和明确NOT_ACCEPTED状态。2026-10-20模型配套固定TFLite Micro的官方原生C++测试已在VM实际通过：有人图的[no_person,person]=[-113,113]，无人图=[57,-57]。这证明该原生TFLM路径能运行原模型，不会把桌面LiteRT的旧失败改写为通过，也不是NPU RTL或数据集准确率验证。

## 固件及内存评估方案

`person_program.cc`先采用官方测试相同的五类INT8注册。一次启动只做一次完整Invoke，报告状态、两类原始分数、`arena_used_bytes()`及mcycle窗口。输入通过`.data`承载，避免主机预装载后被CRT的BSS清零擦除。没有新增Zvt矩阵调用，**这是功能基线，不是矩阵加速版**，也不能拿它的性能代表矩阵单元效率。

为测ITCM，固件先用512KiB链接上限；这不生成512KiB ITCM的RTL，也不等于实际需要512KiB。程序代码/只读辅助表在ITCM；原模型原字节放`.data.pd_model`、DTCM512KiB，避免300KiB模型占ITCM或产生数十万次外部元数据读取。arena预留160KiB、输入9KiB、栈16KiB；这些固定项合计约479KiB，仍需实际ELF核对剩余静态数据/堆和对齐，不能预先保证链接或运行内存足够。

`firmware_report.py`审计真实ELF32 RISC-V：

- 所有加载段在统一实验ITCM/DTCM地址范围内，入口在ITCM；不变更团队SoC地址图。
- 链接后的`pd_model`逐字SHA与原始模型相同，且位于DTCM；输入/输出有文件初始化而非NOBITS。
- arena符号163840字节、栈16384字节、堆/静态区边界不重叠。
- ITCM实际加载占用、最小8KiB块对齐容量、带25%容量余量的2次幂候选。候选仍须生成并验证其RTL；运行arena用量和栈水位标NOT_RUN。

包放在现有实验源新增`tests/cocotb/person_detect_baseline/`，独立manifest；验证原有几何实验指纹和真实512KiB几何PASS，不修改已验证的Core.scala、链接规则、旧测试或旧manifest。发现同名非本工具目录/身份变化时拒绝覆盖。同一source不得与其他Bazel任务并行；锁忙时立即停止，不杀进程。

## 已完成步骤：Ubuntu虚拟机主机测试与固件测量

代码同步到个人仓库后，从VM仓库根目录执行：

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
if [ -n "$(git status --porcelain)" ]; then
    git status --short
    echo "存在未提交修改，未更新。"
    exit 1
fi
git pull --ff-only origin main
python -m pip install pyelftools==0.32
bash verification/google_person_detect/build_firmware.sh
)
```

主机原生测试`@tflite_micro//tensorflow/lite/micro/examples/person_detection:person_detection_test`需同时出现一对正确有人/无人分数和`~~~ALL TESTS PASSED~~~`，严格检查不以退出码单独替代；之后才交叉编译ELF和核对资源。模型在C++固件中仍是未修改原始版本。下载通过终端已有HTTP(S)_PROXY代理；本脚本不写永久代理设置。日志安静、不反复输出Analyzing。

回传`PERSON_TFLM_NATIVE_HOST_REFERENCE`、`PERSON_FIRMWARE_RESOURCE_REPORT`和最终`PERSON_FIRMWARE_MEASURED`。任何失败保留新目录日志，不删除旧结果。初次编译依赖可能较久，没有可靠耗时承诺。资源脚本只编译固件，不启动VCS/Verilator，不占用服务器仿真任务。

## 后续验收

1. 官方原生主机测试和固件资源报告通过，选定<=512KiB ITCM；必要时调整arena/布局必须另记身份，不修改原模型。
2. 准备该ITCM/DTCM512KiB的独立RTL包、原始模型/样本、前门加载及fault/输出检查；先一张图、再两张。默认标量/向量基线的长仿真成本先小窗口采样，不直接启动过夜重复。
3. 保留正确性基线，接入通用分块矩阵pointwise/卷积内核；depthwise倍率8和倍率1分别验证，保留真正INT8逐通道量化、ReLU6和softmax。没有这一步就不声称矩阵加速。
4. 记录逐层输出、算子后端、周期/搬运和RTL身份；两张图分类正确不等于整套数据集准确率。

本机15项合成/静态检查通过（含ELF预算与拒绝反例、模型数组字节相同、原始样本编码、安装器只写新目录和拒绝覆盖改动）；不是主机原生C++或NPU RTL PASS。另有19项1001类工具回归通过。

## 当前下一步：仅生成并导出RTL，不重跑主机测试/固件编译

已测固件目录`/home/lqq/coral_tcm_capacity_8e4_v1/person_firmware.AD3nfw`。新导出器复核该目录的host参考、ELF/资源报告和原固件manifest，按实际段地址确认原ELF可装入256KiB ITCM；不改链接脚本、固件或模型，不覆盖既有包。

在Ubuntu VM运行（Windows工具提交后先同步）：

```bash
(
set -eo pipefail
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate coral-matrix
cd "$HOME/桌面/Coral_matrix"
if [ -n "$(git status --porcelain)" ]; then
    git status --short
    echo "存在未提交修改，未更新。"
    exit 1
fi
git pull --ff-only origin main
bash verification/google_person_detect/export_rtl.sh \
  "$HOME/coral_tcm_capacity_8e4_v1/person_firmware.AD3nfw"
)
```

只新增source包`tests/cocotb/person_detect_rtl_i256_d512`和独立manifest，顶层`VmeCoreMini_ITCM256KB_DTCM512KBAxi`，沿用旧实验8e4源/两补丁/地址图以及开启外部AXI取指的公共参数。不是prod配置，不能沿用旧ITCM8KiB的RTL仿真资格。

产物在新建`person_rtl_export.XXXXXX/coral_person_i256_d512.tar.gz`及`.sha256`；包含原始单文件SV、ZIP依赖、参数头、SRAM DPI、原ELF、两张BMP和无需Pillow的原始INT8输入、主机分数及资源证据。包内`portable.py`可只读校验，运行输出放包外；SHA校验不等于RTL通过，也不是数字签名。

**导出阶段没有启动VCS/Verilator。** 2026-10-20用户已回传真实新RTL导出通过，归档SHA `a83bd98bd92157163223b75d74a25e5f426a59937354fb3784d830be4f130726`。下一步是[服务器传包及Verilator短窗口](SERVER.md)：新独立runner只在包外运行，先前门加载/读回和20万周期观察，检查fault/状态/arena/栈底canary；这不是完整模型PASS，不拿旧TCM workset runner套用新ELF，不自动启动整网过夜重复。服务器实际运行尚未回传。

新增7项导出合成检查通过（与原有15项合计22项）：配置/路径拒绝、官方BMP解码与Pillow一致、证据配对、256KiB段边界、拒绝覆盖/篡改、归档及只读校验。这些合成包不是真实RTL产物；随后用户实际生成的新包与服务器下一步见上节及[SERVER.md](SERVER.md)，加入新入口后本地检查合计29项。
