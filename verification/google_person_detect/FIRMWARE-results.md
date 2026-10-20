# 预训练Person Detection：主机参考与固件资源结果

记录日期：2026-10-20。依据用户回传的VM输出；没有直接读取远程ELF/完整日志。原始目录：

`/home/lqq/coral_tcm_capacity_8e4_v1/person_firmware.AD3nfw`

## 已通过

固定TFLM `b75c6ff4e2270047f2b48fa01f833c8101c31f43`，未改模型SHA `808cfdfc0cf3a6fa6f6fa26bfa379ea97c16d5db7334637766e39c3408502e9d`。

原生主机测试构建380.413秒，测试本身0.4秒；1/1通过。严格host checker得到：

| 官方样本 | 输出0：no_person | 输出1：person | 判断 |
| --- | ---: | ---: | --- |
| person.bmp | -113 | 113 | person |
| no_person.bmp | 57 | -57 | no_person |

这是量化INT8分数，不是负概率。主机日志原列顺序为person、no_person，本表按模型输出顺序排列。

host日志SHA256：`d04c93fb6c3a140cb5c38ee2dd96a0beb54828c3d6f4e9fccad303a56931e19e`。

随后RISC-V固件编译341.416秒，ELF审计`LINK_RESOURCE_AUDIT_PASS_NOT_INFERENCE`：

| 项目 | 字节 | 说明 |
| --- | ---: | --- |
| ITCM加载占用末地址 | 136080 | 约132.89KiB，128KiB放不下 |
| 推荐ITCM候选 | 262144 | 256KiB，满足所用25%余量规则，尚待生成/RTL运行 |
| DTCM静态范围 | 474432 | 包括原模型、arena预留及静态状态等，不是实测运行峰值 |
| 剩余堆空间 | 33472 | 约32.69KiB |
| 预留栈 | 16384 | 16KiB，尚无运行水位证据 |
| 上述DTCM布局合计 | 524288 | 512KiB |
| arena预留 | 163840 | 已包含在静态范围内，不能重复相加 |

检查确认链接后的原始模型字节相同、输入/输出初始化不被CRT BSS清零擦除，静态/堆/栈不重叠。ELF的SHA未在本次回传摘要中列出，保存在该目录的`resources.json`，不得猜填。导出器会重新读取ELF并逐项重算审计。

## 尚未通过/尚未执行

- NPU实际执行、完整单图Invoke、NPU输出与主机参考精确对照。
- 服务器Verilator新模型编译/运行。256KiB ITCM新配置的RTL生成及归档导出随后已实际完成，见[服务器入口与导出身份](SERVER.md)。
- 运行时`pd_arena_used`、栈水位、实际推理周期及仿真墙钟。
- 数据集准确率与VME矩阵算子加速。当前后端为`pinned_TFLM_INT8_not_VME_offload`，不能用此基线证明矩阵加速效果。

桌面LiteRT2.1.4对原模型量化元数据的旧加载失败保留；本次是配套原生TFLM路径通过，不是修改模型后的替代测试。下一步命令见[专题入口](README.md#当前下一步仅生成并导出rtl不重跑主机测试固件编译)。
