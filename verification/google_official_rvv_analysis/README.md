# 已有官方 RVV 结果的只读数值归因

不改官方内核、不降低验收阈值、不重跑 RTL、不改已验收目录。
通过原冻结汇总器重新检查探针、原始日志/XML/退出状态、ELF/模型/源码和证据哈希，
再对原有 GELU 输入做数学归因：系数舍入、截断、低阶有理函数各贡献多少误差。

参考保持现有 **tanh 形式 GELU**，不是另换成 erf 形式。
归因用 FP64 计算并在输出舍入 FP32，不是假装逐指令 FP32/FMA 仿真。
额外的 `[-8,8]`、步长 `1/512`、up=1 网格只是主机数值分析，
不能声称任意激活范围正确，也不是模型精度或新的 RTL PASS。

在虚拟机 coral-matrix 环境运行，输出必须是旧 job 外的新目录：

```bash
python -B verification/google_official_rvv_analysis/analyze.py \
  --job "$HOME/coral_tcm_capacity_8e4_v1/official_rvv.aI9wIK" \
  --output "$HOME/coral_tcm_capacity_8e4_v1/official_rvv_attribution.自选新名称"
```

主机数值检查预计几秒；旧证据重新验收另需读取文件，不运行仿真。
不自动更新全局进度文档或交接文档。
