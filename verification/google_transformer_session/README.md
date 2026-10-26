# Caller-owned Transformer KV session

Pinned Coral 8e4df09, unchanged RTL/ISA, single NPU, ITCM256KiB/DTCM512KiB.
The qualified FP32 Attention and GEGLU FFN arithmetic is retained. New code exposes
init/prefill/decode APIs with an explicit caller-owned State (K/V, length, geometry,
position base, guards). Each decode call receives ONLY the new token input and
returns before the next call. Cache survives function returns; core reset, host
relaunch, model switching, concurrency on one state and multi-layer KV are outside
this experiment. A state and its output workspace must remain allocated and paired.
Callers use immutable matching weights/RoPE table and cannot change state metadata.

Cases (P,H,F,T,RoPE base): (1,4,8,2,3), (2,6,13,3,7), (3,8,8,3,11),
plus zero safety (1,2,3,2,0). P prefill tokens followed by T one-token decode calls.
F=H in the third case keeps this diagnostic workspace below 1024 floats; these
are synthetic small shapes, not a claim about production FFN expansion ratios.

Every call completes Attention -> residual -> FFN -> residual. Official FP32
Linear on both RVV paths; candidate uses official RMSNorm/residual and qualified
high-order MLAS-derived GELU; project tanh and Attention exp remain scalar libm.
No pretrained model, embedding/tokenizer, generation loop, VME or DRAM timing.

All 19 stage tensors use unchanged atol=2e-5/rtol=2e-4 against an independent full
causal FP64 reference with FP32 storage boundaries. KV prefix retention is checked
at EVERY call; new rows match current K/V. Future cache rows are poisoned. An untimed
actual RTL bulk control and two interleaved contexts (x and -x) must match independent
references. Decode-before-prefill, duplicate prefill, wrong position, bad state guard,
and full-cache decode must reject without changing state or output. Explicit reset
must clear KV, then replay correctly. Software counts are not retired instructions.

Four rotated samples per path. Whole-session raw mcycle includes initialization,
all API calls, copies, intermediate snapshots, checks and phase timing probes.
Nested phase cycles measure only the individual prefill/decode API windows and
must fit inside their enclosing sample. Neither is pure production kernel latency.
Bulk and lifecycle/isolation controls are untimed. Input loads/readback and host
RoPE coefficient generation are excluded. Stack low-canary is not a full watermark.

`run.sh` prepares only; `resume.sh JOB quick|probe|0|1|2|all` explicitly simulates.
Rough initial ETA excluding first build: probe 2-5min; cases 3-8/5-12/7-16min;
all 17-41min, needs calibration on VM. Old frozen experiments remain unchanged.

Current generated package: transformer_session_v2. Preserved v1 raw observations
passed strict math, but its comparison serializer shadowed the quality Boolean with
a phase count. v2 uses a separate count variable and requires an actual Boolean in
the regression test. Arithmetic/state code is unchanged; v1 evidence is preserved.
