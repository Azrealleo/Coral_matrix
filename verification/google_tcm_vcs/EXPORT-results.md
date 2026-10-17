# 固定RTL包实际导出记录

## 2026-10-17：DTCM 1MiB

依据：用户回传的Ubuntu导出终端输出；Windows工作区未直接读取该归档。服务器传输、校验和VCS仿真结果尚未回传。

- 固定官方提交：`8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`。
- 导出工具提交：`088b836`；Bazel 9.1.0二进制校验输出为OK。
- 单NPU顶层：`VmeCoreMini_ITCM8KB_DTCM1024KBAxi`；ITCM 8KiB，DTCM 1024KiB。
- 导出工作目录：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d1024.yzU5z6`。
- 包目录：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d1024.yzU5z6/coral_tcm_vcs_d1024`。
- 归档：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d1024.yzU5z6/coral_tcm_vcs_d1024.tar.gz`。
- SHA256：`0e969183cd48d3f7a9eaa062e31aded9d89b011fa8fcddee58febd69823b8cb8`。
- 校验文件：同目录的`coral_tcm_vcs_d1024.tar.gz.sha256`。
- `[TCM_VCS_EXPORT_VERIFIED]`确认：`control_rtl_bytes_equal=true`、`firmware_bytes_equal=true`、`vcs_simulation="NOT_RUN"`。
- Bazel构建耗时59.043秒、1366项缓存命中；这是缓存构建/导出耗时，不是RTL仿真耗时。

结论：已导出与已有控制组PASS产物字节一致的RTL、与完整T12工作集PASS记录字节一致的固件。**不代表VCS编译或VCS仿真通过，也不能据此评价VCS速度。**

下一步：传归档及外部SHA文件到服务器个人目录，核对上述SHA，解包并校验内部SHA256SUMS，再按包内PACKAGE-README准备环境、check、build及T12小工作集。先取得小工作集完整PASS再跑大工作集。每个DTCM容量单独导出、编译和验证，不能拿1MiB包冒充2/4MiB。

本记录位于源码仓库，独立于已导出的不可变包；不要为更新状态而修改包内文件或其manifest。
