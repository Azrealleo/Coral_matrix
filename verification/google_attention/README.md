# 小型单头 Attention：prefill 接一个 decode token

固定官方 Coral `8e4df09b4ea7e065e02d14ce3ae033d40dfd973a`，单 NPU，
ITCM 256 KiB / DTCM 512 KiB。工具继承冻结提交
`4aa41e91f598959cb856e6bd58a1b7c79a4ea03f`，只新增包，不改变旧源码或 RTL。

流程：`RMSNorm → Q/K/V 三路 Linear → Q/K RoPE → 因果 Attention → O Linear → 加 x`。
同一调用先计算 P 个 prefill token，再投影最后一个 decode token，追加 KV 后计算该行。
旧 KV 前缀在两个阶段间保留，分配/初始化缓存和搬运也计入整条路径的 mcycle。
单头、FP32、无 bias，H 等于 head_dim；这是合成权重子模块，不是预训练模型。
不包含 FFN、多个注意力头、GQA、token 生成、VME 或 DRAM 搬运。

三条计时路径（同一 ELF、四次采样、轮换顺序）：

- scalar：原项目标量算子。
- project：已验证的项目 RVV；四个 Linear 使用官方 Gemma FP32 RVV。
- candidate：官方 RMSNorm/Residual、相同的官方 RVV Linear、项目 RVV RoPE/Attention。

RoPE/Attention 是已有项目实现，未宣称它们为官方优化内核。
Attention 中 exp 仍是标量 libm。本轮重点是实际数据依赖、因果关系和 KV 复用验证，
不预设 candidate 相对 project 必须更快。
RoPE 使用 split-half 布局及随输入提供的 FP32 cos/sin 表，生成这些表的成本不在计时内。

用例 `(P,H,绝对起始位置)`：`(1,4,3)`、`(3,6,7)`、`(4,8,11)`；
另有零输入 `(1,2,0)` 安全探针。每例总 token 数为 S=P+1。
decode 的 RoPE 使用绝对位置 base+P，因果可见范围按缓存索引 0..P 判定。

13 个张量读回：norm、Q、K、V、旋转后 Q/K、prefill K/V 快照、最终 K/V、
context、O 投影、残差输出。prefill 缓存中未来一行填入固定毒化值，不能影响可见输出。
缓存前缀在 decode 后要求逐位不变，且新一行必须逐位等于本次 K/V。
各阶段以独立 FP64 参考逐阶段取 FP32 校验，保持 `atol=2e-5, rtol=2e-4`。
阶段分隔区、外围区和缓存临时区逐位保护；低地址栈检查仅 64 字节。

另执行一次不计入性能比值的 candidate 整段计算，检查它与流式结果及独立参考一致。
两个控制都在真实 NPU RTL 上执行；这不要求回退到主机完成 Attention。
软件调用计数要求每次流式调用 norm/Linear/RoPE/Attention/append/Residual
分别为 2/8/4/2/2/2，四次总数另行验收。
这些是固件诊断计数，不是硬件退休指令计数。
计时路径包含这些计数、缓存保护检查和用于读回的中间输出/快照，
因此报告的是可观察集成路径，不能当作去除诊断后的生产内核周期。

准备：`bash verification/google_attention/run.sh`（不执行 RTL）。
仿真：`bash verification/google_attention/resume.sh JOB quick`，也支持 `probe|0|1|2|all`。
粗估 quick 1–5 分钟，全部 6–20 分钟，另计首次构建，待实测校准。
不自动更新全局进度或交接文档。原始 official_* 槽位代表 candidate，公开对比明确标识。
