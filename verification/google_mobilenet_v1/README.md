# 完整MobileNetV1：单NPU、DTCM512KiB、ITCM不超过512KiB

2026-10-19新任务。当前模型静态盘点及完整原模型的主机参考推理已完成；交叉编译、ITCM测量和NPU RTL仿真未完成。主机合成输入检查不代表识别准确率，更不替代NPU结果。

**本日后续用户改为先运行[预训练二分类Person Detection](../google_person_detect/README.md)。本目录1001类模型与golden保留为后续，不再自动进行整网RTL。**

## 已确认的用户约束

- 只分析单个官方NPU。团队因综合面积暂定每核DTCM512KiB；不继续以2/4MiB作为本轮默认方案。
- 使用完整预训练MobileNetV1，输出1001分类，不能以团队的小型未训练诊断图代替。
- ITCM根据真实程序评估，最大512KiB；不是立即分配512KiB，也不是已有8KiB足够的结论。
- 仿真优先Verilator。原服务器T384同配置VCS37619.46秒、Verilator13979.842秒，观察快2.69098倍；这是旧工作集后端选择依据，不预测本模型耗时。
- 历史DTCM/ITCM实验、导出包及日志保留，旧的ITCM几何工具固定DTCM2MiB，不能直接作为本轮512KiB方案。
- 用户已确认实际SoC外存尚未确定，单NPU阶段先用外部AXI行为存储；不能将该仿真条件当成团队已选DDR/共享SRAM规格。

## 模型候选及实际静态盘点

用户选择了V1，未另指定宽度/分辨率/模型文件。本轮先采用官方 **MobileNetV1 1.0/224量化版**作为候选，不擅自缩小网络或重训/改权重。来源为[TensorFlow模型说明](https://github.com/tensorflow/models/blob/master/research/slim/nets/mobilenet_v1.md)。

- [原始归档](https://storage.googleapis.com/download.tensorflow.org/models/mobilenet_v1_2018_08_02/mobilenet_v1_1.0_224_quant.tgz)
- 归档SHA256：`d32432d28673a936b2d6281ab0600c71cf7226dfe4cdcef3012555f691744166`
- 模型文件：`mobilenet_v1_1.0_224_quant.tflite`
- 模型SHA256：`ecc3a67c47c5a609ec35f6a58a7d97532834e43df4cb7d3f1204a8164b7d20dd`
- 模型4276352字节，约4.078MiB；去重常量buffer总4257900字节。
- 输入`[1,224,224,3]`、UINT8、150528字节，scale=0.0078125、zero_point=128。
- 输出`[1,1001]`、UINT8、1001字节，scale=0.00390625、zero_point=0。
- 单子图31个算子：CONV_2D=15、DEPTHWISE_CONV_2D=13、AVERAGE_POOL_2D=1、RESHAPE=1、SOFTMAX=1。分类头也是CONV_2D，不另有FULLY_CONNECTED节点。
- 最大非恒定张量`[1,112,112,64]`为802816字节（784KiB），自身超过512KiB DTCM。
- 单算子非恒定输入/输出按不别名直接相加的最大值1204224字节；不含scratch、其他存活张量、对齐、栈和运行时状态，**不是TFLM arena测量、通用内存下界或整个网络实际峰值**。
- 某些1×1权重张量为1048576字节，分类头权重1025024字节，需要分块/外存，不能逐层整份驻留DTCM。

模型归档和完整inventory缓存在被忽略的`.upstream-git/model-cache/mobilenet_v1_2018_08_02/`，不提交二进制；同名报告拒绝覆盖。

## 对实现路线的影响

1. **外部存储是已获准采用的仿真假设。** 用户确认单NPU阶段先用外部AXI行为存储保存模型和部分特征图；实际SoC的DDR/共享SRAM/Flash、容量/地址/带宽尚未确定。不能把行为存储当作已经存在的SoC硬件。模型本身也超过官方默认链接模板EXTMEM4MiB，不能直接把全模型塞进原`.extdata`而忽略链接/代理边界。
2. **量化不能沿用诊断图。** 此模型是UINT8、非对称量化；权重zero_point并不统一为128，例如首层151、分类头74。不能将权重直接重解释为INT8，也不能假设减去自身零点就总能装入INT8。必须保存原始数值语义，核对偏移补偿、padding零值、累加、固定点重缩放/舍入/饱和、池化和softmax。不能用简单右移+clamp(0,127)替代。
3. **团队代码可借鉴但不可直接套用。** 已只读审查团队main `fa4b83e43bb0b1d58b18eb5f4c31d98ee4054123`：`sw/models/h4-resnet8/npu.cc`提供优化后的im2col、权重打包复用、bias/tile初始化、真实VME调用。其固定K<=144、小通道、固定数组和简化量化不覆盖本模型；需要沿输出通道、空间和K分块。depthwise的M=1矩阵路径也不默认是最优。
4. **ITCM按ELF/map实测。** 先交叉编译候选最小运行程序，分别统计`.text`、只读辅助常量、启动段/链接间隙和加载段，再选择有余量且<=512KiB的档位；模型权重显式放外部，不算进ITCM。DTCM还要预算静态区、栈、工作缓冲和暂存。不能从`.tflite`体积、旧诊断固件8KiB或默认1MiB示例推导需求。
5. **先正确性后整网性能。** 建立可信TFLite主机参考和预处理/标签约定，再对单层及尾块验证矩阵/向量内核，最后运行完整图并比较1001维输出、逐层中间值。冻结模型、输入、参考、RTL参数、ELF和编译器身份。完整模型不要求每个节点都走矩阵，但必须记录实际后端和回退。

## 盘点工具

依赖Python、`tflite`和`flatbuffers`（本次Windows已存在，未修改系统环境）。

```bash
python -B verification/google_mobilenet_v1/inspect_model.py /path/to/mobilenet_v1_1.0_224_quant.tflite --dtcm-kib 512 --output /path/to/NEW-inventory.json
python -B -m unittest discover -s verification/google_mobilenet_v1 -p 'test_*.py'
```

工具只读取FlatBuffer，不执行推理或生成RTL；拒绝变量/动态/稀疏/外部buffer和多子图，避免把不支持的布局静默记成已评估。

本机12项检查通过，包含实际已下载模型的SHA/算子/输入输出/张量容量核对，以及动态/变量/错误文件拒绝和报告不可覆盖检查；不是推理或RTL PASS。

## 后续待做

- 确认模型候选及参考图像/标签，增加图像预处理及识别演示；实际外存参数以后与团队对接，不阻塞行为仿真。
- 审计固定TFLM与UINT8模型兼容性，选择/实现可保持原模型语义的运行方案；不能假定现有INT8优化注册能覆盖UINT8。
- 实现/验证通用分块、量化与算子调度，交叉编译并提交ITCM/DTCM实际预算。
- 新建DTCM512KiB及选定ITCM的独立RTL/固件包，先单层再整网Verilator验证；此处尚无RTL PASS。
- 记录完整执行、分层周期、外部读写量及主机仿真耗时，必要时用VCS交叉验证。先不要启动旧2/4MiB扫描或将旧T384周期用作本模型性能。

## 完整模型主机参考（2026-10-19）

独立环境`.upstream-git/model-cache/host-reference-venv`以`--system-site-packages`只读复用原Python库，仅在该环境安装`ai-edge-litert==2.1.4` Windows轮子，未改系统Python/服务器。使用原始模型字节、`BUILTIN_REF`、无外部delegate、单线程并保留中间张量。

实际执行`reference.py`：neutral128、全字节ramp、0/255 checker三组合成输入，每组独立invoke两次，31个算子输出全部逐位一致，完整1001维输出已保存。这里的中性128仅表示输入量化的实数零；这些都不是照片，top5仅类别索引，不声称ImageNet准确率或标签识别正确。

| 输入 | 1001维输出原始字节SHA256 |
| --- | --- |
| neutral128 | `d774b12dd13e4e78511b5a928cd561b385fb37bc696e5bc68f11d747f93fef56` |
| ramp | `b82420ef75a814e653396e08f2b5bbda5c70e28dc27af1d935ae5acca6c526af` |
| checker | `571124c573909de54345577cc971485c08792865a3e67958603c1c24b21ddae2` |

结果在忽略目录`.upstream-git/model-cache/mobilenet_v1_2018_08_02/reference_builtin_ref_v1/`，含manifest、每组输入/输出和逐算子npy及其原始数据SHA。脚本先核对固定模型SHA；新目录独占，异常留下INCOMPLETE，不复用/覆盖历史结果。当前主机六次invoke及核对/保存过程约3.725秒（进程启动/分配另计），**不是NPU时间，不可和RTL仿真墙钟或200MHz换算相比较**。固定其他runtime或优化内核如出现末位差异须单独解释，不静默替换参考。

本次实际Python3.12.1、NumPy1.26.3、flatbuffers25.12.19、tflite2.18.0、LiteRT2.1.4，固定主机依赖见`requirements-host.txt`。19项本地测试全部通过，包含三组实际golden所有93份算子输出文件SHA及模型身份检查；不启动RTL。

复现时在有Python依赖的环境中指定新目录：

```bash
python -B verification/google_mobilenet_v1/reference.py /path/to/mobilenet_v1_1.0_224_quant.tflite --output /existing/parent/NEW-host-reference
```

`reference.py`明确不用默认delegate，保存31节点输出供后续分层定位。当前只完成参考生成；NPU/矩阵内核与这些golden的对比尚未执行。
