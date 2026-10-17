# 固定RTL包实际导出记录

## 2026-10-17：DTCM 1MiB

依据：用户回传的Ubuntu导出及实验室服务器终端输出；Windows工作区未直接读取该归档。

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

### 服务器实际进展

- 归档校验输出`coral_tcm_vcs_d1024.tar.gz: OK`，解包后输出`[TCM_VCS_SERVER_PACKAGE_CHECK] PASS`。
- 包位置：`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024`（`/home2/lqq`路径解析到`/data/home2/lqq`）。
- `[TCM_VCS_PACKAGE_VERIFIED]`通过；`[TCM_VCS_ENV_CHECK]`通过：独立Python3.11、cocotb2.0.0、NumPy1.26.4、pyelftools0.32、find-libpython0.5.1，主机glibc2.17；向量与ELF检查通过。
- VCS：`/opt/Synopsys/vcs/Q-2020.03-SP2-7/bin/vcs`。
- 首次构建目录：`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_runtime/builds/ad64e2610e46.ioqlvkyn`，日志`_build.log`保留。
- 原始SRAM DPI编译及C-ABI读写/byte mask自检通过，输出`[TCM_VCS_DPI_SELFTEST_PASS]`；这不是RTL仿真PASS。
- VCS解析SV第167036行elaboration `$fatal`时停止：`Using elaboration system tasks requires option -assert svaext`。当前证据是启动器漏加工具选项，不是已证明DivSqrt WIDTH非法。
- 旧启动器在提交088b836中未加该选项；现编译入口补入`-assert svaext`，为旧包提供保留父包的`upgrade_svaext.py`。只更改启动器编译参数，新manifest记录父包身份，不重新基准化RTL/固件哈希。
- **修正后的VCS编译及完整仿真仍待服务器实测，不报告速度提升。**

下一步：升级生成同级`coral_tcm_vcs_d1024_svaext_v1`，校验并编译；编译成功后运行T12/等待0完整小工作集，先取得小工作集完整PASS再跑大工作集。每个DTCM容量单独导出、编译和验证，不能拿1MiB包冒充2/4MiB。

本记录位于源码仓库，独立于已导出的不可变包；不要为更新状态而修改包内文件或其manifest。
