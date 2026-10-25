# 小型 pre-norm GEGLU FFN：合成数据、真实 RTL

固定官方 Coral `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，单 NPU，
ITCM 256 KiB / DTCM 512 KiB。父工具冻结到
`198cf34dc460ea96fcb56e3a2edfa491884d57a3`；不修改旧工具、官方算子、RTL 或 ISA。

数学数据流：

```
norm = RMSNorm(x, gamma)                  # 官方 Gemma 的 1+gamma 约定
gate = norm @ Wgate                      # [M,H] @ [H,F]
up = norm @ Wup
activation = tanh_GELU(gate) * up
down = activation @ Wdown                # [M,F] @ [F,H]
output = down + x
```

这是有实际数据依赖、无 bias 的小型 pre-norm GEGLU FFN 子模块。
使用确定性合成 FP32 权重，不是预训练模型；没有 Attention、token 生成或 DRAM 搬运。
M 为 token/行数，H 为隐藏维度，F 为 FFN 中间维度。
用例：M1/H8/F16，M3/H7/F13，M4/H8/F32；另有零输入 M1/H1/F1 安全探针。
这些小维度用于接口/尾部/数值和周期验证，不代表真实大模型性能。

同一 ELF 的三条路径：

- scalar：原项目标量算子。
- project：原项目 RVV RMSNorm、GELU、Residual，三次 Linear 均调用官方 Gemma FP32 RVV。
- candidate：官方 RVV RMSNorm、三次官方 FP32 RVV Linear、已验收的高精度 RVV GELU、
  官方 RVV Residual。GELU 是 MLAS 高阶 tanh 的项目 RVV 移植，不是原样官方 GELU。

两个 RVV 路径的 Linear 相同，project 的 tanh 仍是标量 libm。
不使用 VME，不宣称跨算子融合，不用旧周期拼接比值。
四次采样（首次+三次稳态）轮换路径；测整条 FFN 的原始 mcycle，
包括三次 Linear、调用切换及中间存储，不扣空边界。输入加载与检查在计时外。

六个中间/最终张量独立读回，以 Python FP64 参考逐阶段取 FP32 检查。
严格门限为 `atol=2e-5, rtol=2e-4`；五个阶段分隔区及外围保护区逐位检查。
栈保护仅检查低地址 64 字节，不构成完整栈高水位证明。
主机镜像不是 RVV 执行证据。MLAS 许可随冻结父工具导出。

准备（只构建，不执行 RTL）：`bash verification/google_ffn/run.sh`。
仿真：`bash verification/google_ffn/resume.sh JOB quick`。
支持 `quick|probe|0|1|2|all`；粗估 quick 1–5 分钟，全部 6–20 分钟，
另计首次构建，待实测校准。不会自动更新全局工作记录/交接文档。

兼容 observation 中 `official_*` 槽位代表 candidate；公开 comparison 使用 candidate。
固件包 envelope schema 为 v1，源码/工具版本单独标识。
