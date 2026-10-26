# Small synthetic Transformer layer

Pinned official Coral 8e4df09; single NPU, ITCM256KiB/DTCM512KiB, unchanged RTL/ISA.
For each invocation: prefill Attention + residual -> GEGLU FFN + residual, then
one decode Attention + residual -> GEGLU FFN + residual. FFN reads the actual
Attention residual. KV persists between these phases, not between invocations.

Three tiny FP32 shapes (P,H,F,RoPE base): (1,4,8,3), (3,6,13,7), (4,8,16,11),
plus zero-input safety probe (1,2,3,0). H is also the single head dimension.
Original scalar/project controls and official RMSNorm/Linear/residual remain
frozen. Candidate additionally uses the strict MLAS-derived RVV GELU candidate;
RoPE/Attention use the frozen project kernels, with scalar libm exp. Gemma RMSNorm
uses 1+gamma. No bias. Precomputed absolute-position cos/sin table is untimed.

Independent FP64 references round to FP32 at storage boundaries and feed the
Attention residual into FFN. All 19 intermediate tensors must pass the unchanged
atol=2e-5/rtol=2e-4 gate. KV prefix and appended tail, poisoned future position,
stage/buffer guards, software phase counts, and an untimed actual RTL full-sequence
causal control are checked. Host mirrors/static ELF audits are not RTL execution.

Timing covers both phases and all diagnostic snapshots/copies/counters, including
cache initialization and checks. It is a diagnostic integration comparison, not a
production layer latency. Four rotated samples; raw mcycle, no boundary subtraction.
No pretrained weights, full LLM, tokenizer, multihead/GQA, VME, DRAM timing or silicon
frequency claim. Depthwise and all old experiments are unchanged.

`run.sh` prepares only. `resume.sh JOB quick|probe|0|1|2|all` explicitly simulates.
Estimate excluding first build: probe 1-3min, three cases 2-6/4-10/7-18min;
all roughly 14-40min, needs VM calibration. Preserve raw logs, XML and manifests.
Any frozen-input change after installation requires a new version and job.

Current package: transformer_layer_v2. The preserved v1 preparation stopped before
RTL because the BUILD hdrs rule rejects .inc; v2 renames that included source to .h.
Arithmetic and phase scheduling are unchanged by this filename correction.
