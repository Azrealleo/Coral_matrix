# 独立高精度 RVV GELU 候选（不是官方原样内核）

保持 Coral 官方 8e4df09b、单 NPU ITCM256KiB/DTCM512KiB、原 tanh-GELU 数学参考、
atol=2e-5/rtol=2e-4。不改官方低阶近似、旧候选、Depthwise、RTL 或 ISA。

复用 ONNX Runtime MLAS v1.20.1 的高阶 tanh 有理函数系数/Horner 方案，
单独移植到 RVV FP32 m4，并融合 gate/up 运算。不是精确 libm；仍必须通过严格精度检查。
来源固定到 `5c1b7ccbff7e5141c1da7a9d963d660e5741c319`，原文件 SHA256 在 SOURCES.md；
Microsoft MIT 许可全文保留在 LICENSE-MLAS.txt，导出固件源码也包含该文件。

主机数值镜像检查 x=[-8,8]、步长1/1024、up∈{-2,-1,0,1,2}，共81925点。
这是有界有限值检查，不是任意 FP32/NaN/Inf 的通用数学库承诺，也不执行 RVV。

性能用例保持原 gelu32/gelu_tail37/gelu256 的输入和种子，索引改为0/1/2。
探针索引3，调用真实候选 GELU 的单元素零输入路径，可精确校验输出签名和guards；
只用于启动安全，不代替非零、bulk和tail的独立 FP64 正确性验证。

同一个新 ELF 比较标量、原项目 RVV（含 scalar libm tanh）、新候选；
不可拼接旧官方低精度候选周期宣称等精度加速。原样官方函数仅保留作链接/来源控制。
继承的原始 observation 中 official_* 字段是传输兼容槽位，此版本明确代表新候选；
comparison 对外使用 candidate_cycles/steady_*_over_candidate，并带独立 scope。

数据驻留TCM；不是模型/DRAM测试。首次+三次稳态，原始mcycle不扣空边界。
完整继承冻结框架的探针、前门读回、guards、calls、fault/halt、XML、退出状态、
工具/固件/源码/RTL/模型/结果哈希检查；任何严格数学精度失败均拒绝验收。
不自动更新全局进度与交接文档。

工具/源码包版本 v2：v1 正式构建成功，但错误要求未被调用的旧低精度 GELU
符号仍留在最终 ELF，被 gc-sections 移除后审计失败。v2 只审计真实被调用的
candidate_gelu_f32（必须存在且含向量运算/FP32向量除法）；旧控制源码仍逐字节封存。
候选算术和精度阈值未改。v1 失败目录/日志保留，不在原地修改工具或源码包。
