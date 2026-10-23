# 直接测现成官方RVV内核，不重写优化实现

固定官方8e4df09b、单NPU ITCM256KiB/DTCM512KiB；不改RTL/ISA/Depthwise。
所有测试数据驻留TCM；不是完整模型或DRAM性能。

同一个新ELF比较三路径：原标量参考、之前的项目RVV基线、原样官方RVV。
官方`rvv_rms_norm.cc`、`rvv_residual_add.cc`、`rvv_tanh_gelu_mul.cc`及公共头文件
通过`git show`从固定官方提交逐字复制，源文件校验值写入manifest。
旧项目基线/参考也从固定个人提交读取，不覆盖LLM、Person或VME实验。
未引入新优化算法；只增加调用包装、计时和验证。
`rvv_matmul.cc`仅用于链接原样项目控制函数中已有的符号引用，本轮没有矩阵乘测试用例。

本地11项检查通过：官方/项目源码逐字节核对，三路径native镜像对独立参考，
原样官方RV32对象编译及合成资源链接，近似精度区分，损坏/缺失结果拒绝、
原始日志/XML/退出状态、导出包完整性和shell语法。
合成链接使用仅用于静态检查的数学占位符，绝不执行该ELF；native镜像也不执行RVV。
VM官方工具链正式交叉链接及真实RTL验证仍待执行，不能据本地检查宣称已加速。

## 先测什么

0=residual256，1=RMSNorm1x64，2=RMSNorm3x37，
3=GELU×Up32，4=GELU×Up37，5=GELU×Up256。
另有独立单元素残差safety probe，必须先通过，旧VME探针不能替代。
先quick（probe+case0），其余逐个执行，不默认长队列。

Softmax已有独立实现是BF16，不能和旧FP32数字直接做速度排名，留到独立同dtype测试。
现成FlashAttention不带因果掩码，不能冒充自回归causal attention，本轮不测。

## 近似精度必须单列

官方GELU用截断有理函数近似tanh；不是标量libm的逐位替代。
仍保留原数学参考atol2e-5/rtol2e-4，不放宽该标准：

- 标量及项目RVV必须满足原数学参考；
- 官方RVV必须匹配独立的其算法参考，并通过有限值/guards/输入输出前门/自然halt等检查；
- 同时报告官方结果相对原数学参考的误差、失败元素和`strict_math_quality_pass`；
- GELU若算法执行正确但严格数学质量失败，只允许记录诊断速度，明确标为
  `ALGORITHM_DIAGNOSTIC_ONLY_NOT_STRICT_MATH_QUALIFIED`，不得称可直接替换；
- RMS/残差没有刻意近似，数学质量失败就是失败，不豁免。

首次+三次稳态分别计时，三路径轮换顺序，空边界不扣除。
未测完整栈水位，只测底部64字节canary。Native官方镜像是标量模拟，不是RVV执行。

## 使用

等待当前Bazel仿真完成后，在Ubuntu coral-matrix环境执行：

```bash
bash verification/google_official_rvv/run.sh
```

默认仅native、官方交叉链接/ELF资源与向量指令审计、构建测试可执行程序，**不跑RTL**。
本地Windows工具链未必支持官方BF16入口；最终以VM固定官方工具链的构建审计为准。
保留打印的job目录。准备通过后才执行：

```bash
bash verification/google_official_rvv/resume.sh /实际job目录 quick
```

quick粗估3～13分钟（probe1～5，residual2～8），其余每例约2～15分钟，
构建另计、需首例校准；60分钟每例超时不是预测时间。
复用已有256/512KiB模型；不自动下载/加载LLM，不运行服务器任务。
旧Pool/VME模型检查器及其只读校验资源用于沿用严格导出框架，不作为本轮执行算子。
全局工作记录/交接文档按约定不自动更新。
