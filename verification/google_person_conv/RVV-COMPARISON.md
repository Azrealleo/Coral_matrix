# VME / RVV Conv 比较前的适用性核对

核对日期：2026-10-22。这里只记录固定源码的分支审计与用户回传的既有实测；本轮没有新增RTL运行，也没有VME/RVV速度比。

## 已有小卷积的实际结果

用户回传服务器 `conv_fec8b002/coral_person_conv_v1_runtime/runs/case0.gqdyx8ir`：

| 项目 | 默认TFLM INT8 Conv | 当前VME Pointwise Conv |
|---|---:|---:|
| 首次Invoke周期 | 91475 | 42713 |
| 随后三次Invoke周期 | 91475 / 91475 / 91475 | 42713 / 42713 / 42713 |

用例 `op2_m16_k8_n16`，M16/K8/N16，每次2048 MAC；两条路径同ELF/原RTL、ITCM256KiB/DTCM512KiB。默认/VME周期比为2.141620，VME少用约53.3%的Invoke周期。空计时边界3周期，未扣除。

4次输出共1024项逐字节对照通过，签名3882088669；VME调用4次、软件矩阵发射8条，fallback/内部reference校验/mismatch均为0；自然halt、status3、无fault、栈底64字节canary完好。执行306.976秒，总322.72秒，不能据此声称整网提速。

固件SHA `b94e1da3b4f7f2693727395073e65f172344f15454bd01a7b7bb8c2832f259b2`；RTL SHA `477aa4d097b1ac7c35f98cb95fe9ba841082a8a10afde6f39dea70959300bfe2`。以上是用户回传日志证据，不表示本地已经取得服务器原始文件。

计时仅包围单算子Interpreter.Invoke，包含VME打包、零点bias修正、矩阵搬运与计算、重定量化、激活及写回；Prepare/输入装载/输出检查不在窗口内。默认注册为 `tflite::Register_CONV_2D_INT8()`，不是官方手工RVV Conv。

## 为什么不能直接把第三条路径称作RVV加速

核对固定官方提交 `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a` 的 `sw/opt/litert-micro/conv.cc`：

- `ConvPerChannel` 始于1161行；1213、1220、1226、1230、1235行的五个优化分支都要求 `filter_height == 4 && filter_width == 4`，并有各自的额外条件。不是所有4×4一定进入同一个实现。
- 1240行打印 `Fallback kernel`，1242行进入 `tflite::reference_integer_ops::ConvPerChannel`。
- 因此当前五个1×1 Conv片段即使注册 `coralnpu_v2::opt::litert_micro::Register_CONV_2D()`，也不会进入这些手工RVV卷积计算分支。
- 该入口回退前还会分配/复制filter和bias、准备shift数组；不能把其时间等同于裸reference时间，更不能把分配或复制中可能使用的向量指令当作RVV卷积MAC加速。
- 当前 `google_person_vme/conv_vme.cc` 70行则明确要求filter高宽均为1，否则 `Fallback(context,node)`。把用例改成4×4，会导致现有VME路径回退。

结论：**这两个现成内核没有共同的优化适用卷积形状。** 1×1下是VME计算对官方入口的reference回退；4×4下是官方RVV计算对当前VME入口的reference回退。两种都不能标成VME与RVV优化Conv的公平比较。这个结论针对固定提交和当前候选，不代表RVV硬件不能加速1×1，也不代表其他版本不存在相应实现。

可用以下只读命令在源码对应Git中复核：

```bash
git show 8e4df09b4ea7e065e02d14ce3ae033d40dfd973a:sw/opt/litert-micro/conv.cc | sed -n '1161,1250p'
```

## 下一步选择

1. 为当前1×1片段新增一个明确标识为**项目自研**的RVV内核，再将默认/RVV/VME放进同一新ELF。它不再是“官方现成RVV Conv”。先做逐字节量化差分、真实RVV短测及资源审计，再谈速度。
2. 若只比较RVV与VME硬件计算能力，另做共同INT8 GEMM微基准；输出为INT32原始累加值，结论仅限该矩阵微基准，不能代替包含打包/量化的Conv Invoke性能。

两者都需要新测试实现，而非简单切换注册。当前尚未选定或实现，不修改原候选/Depthwise/已封包固件，也不启动完整模型长任务。若选择小规模新用例，优先在Ubuntu VM执行，但首次构建模型时间应与实际运行时间分开记录；不能复用ITCM8KiB的旧控制模型冒充当前ITCM256KiB配置。
