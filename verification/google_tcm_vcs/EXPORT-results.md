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
- 用户回传升级成功：新版包`coral_tcm_vcs_d1024_svaext_v1`；父manifest SHA256为`c9baf6844763752bd302a63bb544792abf769be768303e69f30fdcc64990dcc5`，原包、RTL及固件均不变。
- 升级后第二次构建目录为`coral_tcm_vcs_d1024_svaext_v1_runtime/builds/b2ceeee4d376.mwfd6xxz`。已越过原SV语法错误，122个module被读取；VCS生成的rmapats.c在隐式函数声明处编译停止，不能当作NPU仿真失败。
- 用户检查确认：系统`/bin/gcc`为4.8.5，激活Conda后的默认gcc为15.3.0；CC/CXX及常见flags环境变量为空；生成规则使用`$(CC_CG) $(CFLAGS_CG)`。具体CC_CG变量定义未回传，不把推测当成完整编译跟踪。
- 单次子终端把`/usr/bin:/bin`置于PATH前，保留Conda Python与DPI G++的绝对路径，并显式设置VCS CC/CXX为系统工具后，输出`[TCM_VCS_BUILD_PASS] compile_seconds=60.523`。
- 成功构建目录：`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_runtime/builds/754330b47408.u824wjiz`。60.523秒仅是构建时间，不是仿真耗时。
- 后续T12/等待0运行目录：`/data/home2/lqq/Desktop/coral_tcm_vcs_packages/d1024_0e969183/coral_tcm_vcs_d1024_svaext_v1_runtime/runs/t12_r0.6xf7vakp`。
- 运行入口输出`[TCM_VCS_STOP] Extra data: line 1 column 1946 (char 1945)`。尚未取得`_test.log`、`_test-status.json`及`results.xml`的诊断输出，不预判额外字符来源，不修改原日志，不补写PASS记录。
- **VCS编译已实测PASS；完整仿真验收仍未PASS，不报告VCS速度提升。**

下一步：网络恢复后先读取1MiB现有T12原始日志、XML和状态文件，定位JSON解析异常，不能仅重跑或忽略异常。各容量先取得小工作集完整PASS再跑大工作集。每个DTCM容量单独编译和验证，不能拿1MiB包冒充2/4MiB。

本记录位于源码仓库，独立于已导出的不可变包；不要为更新状态而修改包内文件或其manifest。

## 后续回传：DTCM 2MiB导出

- 固定官方提交仍为`8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`；ITCM仍为8KiB。
- 顶层：`VmeCoreMini_ITCM8KB_DTCM2048KBAxi`。
- 工作目录：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d2048.T5HEGi`。
- 包目录：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d2048.T5HEGi/coral_tcm_vcs_d2048`。
- 归档：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d2048.T5HEGi/coral_tcm_vcs_d2048.tar.gz`。
- SHA256：`499a7c31d97d06cb39ff8dcebe1ac2c6232605943d044af5d2eaa83ebe27d768`。
- `[TCM_VCS_EXPORT_VERIFIED]`：`dtcm_kib=2048`，`control_rtl_bytes_equal=true`，`firmware_bytes_equal=true`，`vcs_simulation="NOT_RUN"`。
- Bazel构建28.024秒；两条Chisel枚举转换warning未阻止生成，不将其解释为完整设计已无问题。
- 状态：Ubuntu导出与字节核验已通过，尚未回传服务器传输校验、VCS编译或VCS仿真结果。

## 后续回传：DTCM 4MiB导出

- 固定官方提交及ITCM与2MiB一致。
- 顶层：`VmeCoreMini_ITCM8KB_DTCM4096KBAxi`。
- 工作目录：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d4096.W2JmMH`。
- 包目录：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d4096.W2JmMH/coral_tcm_vcs_d4096`。
- 归档：`/home/lqq/coral_tcm_capacity_8e4_v1/vcs_export_d4096.W2JmMH/coral_tcm_vcs_d4096.tar.gz`。
- SHA256：`272a4e81560856660801d9c7dbcf28b40d8d290b3d1886395aa5f0c46d5269a5`。
- `[TCM_VCS_EXPORT_VERIFIED]`：`dtcm_kib=4096`，`control_rtl_bytes_equal=true`，`firmware_bytes_equal=true`，`vcs_simulation="NOT_RUN"`。
- Bazel构建25.754秒；同样两条Chisel枚举转换warning未阻止生成。
- 状态：Ubuntu导出与字节核验已通过，尚未回传服务器传输校验、VCS编译或VCS仿真结果。

三档导出仅证明包内RTL与对应容量的已通过控制组产物一致、固件与已通过工作集一致；不代表这些独立VCS包已通过仿真。2/4MiB导出耗时不是容量性能数据，包内`vcs_simulation="NOT_RUN"`是导出时的声明，不因后来服务器编译而修改原包。
