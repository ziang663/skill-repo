---
name: model-forward-trace-analysis
description: Trace and explain SGLang model requests and forwards, including end-to-end stages, per-rank GPU kernel activity, component attribution, communication, logical call counts, and weight/activation/cache/accumulator dtypes. Use for SGLang performance profiling, Nsight or PyTorch trace analysis, kernel/dtype audits, and single-GPU versus parallel deployment comparisons. Do not use for LightX2V, vLLM, or other non-SGLang runtimes.
---

# Model Forward Trace Analysis

Produce an evidence-backed SGLang performance and dtype report that another engineer can reproduce. Analyze existing artifacts when available; collect new traces only when the user asks for execution or profiling.

## Select the workflow

- For a complete request or multi-case study, read [references/workflow.md](references/workflow.md).
- Before collecting SGLang, PyTorch profiler, or Nsight Systems data, read [references/sglang-instrumentation.md](references/sglang-instrumentation.md).
- When mapping kernels to model components or validating logical call counts, read [references/component-attribution.md](references/component-attribution.md).
- For checkpoint, activation, cache, quantization, or kernel-accumulator dtype analysis, read [references/dtype-methodology.md](references/dtype-methodology.md).
- Use [assets/report-template.md](assets/report-template.md) for the final Markdown structure.

## Required invariants

1. Record the exact SGLang checkout and commit, model path/revision, launch command, request payload, hardware, software versions, parallel configuration, cache dtype, attention/MoE backends, warmup policy, and output validation.
2. Hold prompt/input tokens, seed, shape, sampling schedule, output length, cache state, and prefix-cache behavior constant across performance comparisons unless the changed variable is the subject of the test.
3. Keep these metrics separate:
   - client wall time;
   - SGLang request/stage wall time;
   - GPU activity duration, which is the sum of kernel durations and can overlap across streams;
   - critical-path wall time, which is not the sum of all rank activity.
4. For multi-rank traces, report both per-rank results and the aggregation rule. Use rank maximum for synchronized critical-path latency and rank mean for average GPU-work distributions unless evidence requires another definition.
5. Never infer kernel dtype solely from checkpoint dtype or a kernel name. Distinguish storage dtype, loaded parameter dtype, activation dtype, cache/state dtype, GEMM input dtype, internal accumulator dtype, and output dtype.
6. Label conclusions as `measured`, `source-confirmed`, or `inferred`. State uncertainty instead of converting an inference into a fact.
7. Validate logical operator counts against model configuration. Do not equate one logical forward, module call, or layer with one CUDA launch.

## Execution outline

1. Define the comparison matrix and metric definitions before tracing.
2. Inspect the SGLang source/config to identify the actual execution path for the selected model, phase, backend, and dtype.
3. Run a correctness warmup, then a measured request. For autoregressive models, separate prefill/extend from stable decode; for diffusion models, separate conditioning, denoising NFEs, and decoder/VAE work.
4. Capture only the necessary steady window when possible. Preserve raw traces, request perf dumps, logs, configs, and environment metadata.
5. Attribute kernels using NVTX/module/source evidence, quantify unclassified activity, and cross-check expected layer/operator counts.
6. Build dtype flows from checkpoint metadata, runtime tensor observations, cache allocation/configuration, and kernel source. Treat internal accumulation as unknown unless source or lower-level evidence establishes it.
7. Generate the report, include limitations, and link every raw artifact.

## Deterministic helpers

- `scripts/summarize_sglang_perf.py`: summarize one or more SGLang request perf JSON files and detect suspicious asynchronous first-step timings.
- `scripts/analyze_gpu_trace.py`: aggregate PyTorch Chrome traces or Nsight Systems SQLite kernel activity using ordered component regex rules.
- `scripts/inspect_safetensors.py`: inventory checkpoint tensor elements, bytes, and dtypes without loading tensor payloads.
- `scripts/dtype_probe.py`: importable forward-hook helper for recording module input/output tensor dtypes and shapes during a narrowly scoped diagnostic run.

Scripts provide measurements, not final attribution truth. Review their unclassified output and reconcile it with the exact SGLang source path before reporting.

## Completion criteria

The final result must include environment and cases, timing definitions, end-to-end results, component activity with absolute times and percentages, per-forward/step latency, communication and rank imbalance, model call-count validation, a boundary-by-boundary dtype table, optimization priorities, limitations, and artifact paths. If trace coverage or dtype evidence is incomplete, identify the missing capture instead of filling gaps by assumption.
