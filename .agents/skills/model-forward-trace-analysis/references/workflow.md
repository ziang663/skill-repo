# SGLang forward trace workflow

Use this workflow for a full analysis or comparison matrix. Skip collection steps when the user supplied sufficient artifacts and asked only for review.

## 1. Freeze the question and cases

Write a compact manifest before profiling:

| Field | Examples |
|---|---|
| Model phase | prefill, extend, stable decode, diffusion denoise NFE, VAE decode |
| Input/output | token lengths, batch/concurrency, image/video shape, frame count, output tokens/NFEs |
| Parallelism | TP, PP, DP, EP, CP/Ulysses/ring, CFG parallel |
| Data types | model activation, weight quantization, KV/state cache, VAE |
| Backends | attention, sparse attention/indexer, MoE runner, GEMM, communication |
| Cache policy | cold/warm, prefix hit/miss, chunking, retraction, offload/swap |
| Repetition | warmups, measured runs, stable steps, aggregation statistic |

Do not call two cases comparable until the model input, generated work, and cache state are equivalent. For distilled diffusion models, compare the same number of actual transformer evaluations (NFE), not an ambiguous CLI grid-point count.

## 2. Capture the environment

Preserve raw output for:

```bash
git -C <sglang-checkout> rev-parse HEAD
nvidia-smi --query-gpu=index,name,driver_version,memory.total --format=csv
python -c 'import torch; print(torch.__version__, torch.version.cuda)'
python -c 'import sglang; print(getattr(sglang, "__version__", "unknown"))'
```

Also save the full launch command and all relevant environment variables. Redact credentials, tokens, private prompts, and unrelated environment values.

## 3. Resolve the actual model path

Inspect configuration and source before assigning categories:

- model architecture and layer counts;
- attention layer variants and their layer indices;
- dense versus MoE layers, expert count, top-k, shared experts;
- head count/dimension after tensor or sequence parallelism;
- cache/state shapes and dtypes;
- selected SGLang attention, MoE, GEMM, quantization, and communication backends;
- backend fallbacks caused by head dimension, device capability, or dtype;
- compile, graph capture, fusion, offload, and custom-op branches.

Use `rg` against the exact checkout. Runtime logs and selected backend messages override assumptions based on defaults.

## 4. Establish correctness and repeatability

Run a correctness warmup and validate the output before timing. For each measured case:

- flush or preserve caches according to the manifest;
- keep the seed and request payload fixed;
- wait for a stable idle baseline;
- confirm no OOM, request retraction, unexpected batching, fallback, or cache hit;
- validate response shape, token count, media metadata, and errors;
- record peak memory with its definition: allocated, reserved, process used, or device used.

Use repeated measurements when run-to-run variance can affect the conclusion. Report median plus a range or percentile rather than silently selecting the best run.

## 5. Separate phases correctly

### Autoregressive models

- Profile full prefill/extend separately.
- After all requests finish prefill, capture stable decode steps.
- State tokens produced per decode step and active batch size.
- When estimating a full output from stable steps, mark it as an estimate and explain scheduler/batch-shape differences.

### Diffusion and multimodal-generation models

- Separate input/text/image/audio encoding, latent preparation, denoising NFEs, decoder/VAE, and serialization.
- Verify whether the first measured NFE contains one-time preparation or asynchronous timing effects.
- State whether LoRA is dynamically applied, pre-merged, or fused; exclude one-time merge/load cost from request latency unless deployment startup is the requested metric.

## 6. Collect a narrow GPU trace

Prefer a stable window that answers the question over tracing server startup and the entire request. Preserve per-rank trace files. See [sglang-instrumentation.md](sglang-instrumentation.md) for collection options.

GPU activity totals are useful for component shares but are not automatically wall time. Concurrent streams and multiple ranks can make summed kernel durations exceed elapsed time.

## 7. Attribute and validate

Create ordered component rules from NVTX ranges and confirmed source paths. Run `scripts/analyze_gpu_trace.py`, then inspect:

- unclassified GPU activity percentage;
- top unclassified kernels;
- per-rank total activity and imbalance;
- expected versus observed logical operation counts;
- fused kernels spanning multiple conceptual components.

Do not force generic GEMMs into categories without call-site evidence. See [component-attribution.md](component-attribution.md).

## 8. Build the dtype map

Start with `scripts/inspect_safetensors.py`, but complete the analysis with runtime observations and source inspection. Produce a boundary table for every major component. See [dtype-methodology.md](dtype-methodology.md).

## 9. Derive conclusions

Prioritize absolute time before percentages. A component can gain percentage only because another component became faster. For each conclusion, answer:

- What changed in absolute milliseconds?
- Does it scale with context, batch, NFE, or parallel degree?
- Is the bottleneck compute, memory traffic, communication, launch overhead, or fixed host work?
- Which evidence establishes the claim?

## 10. Package artifacts

Keep a reproducible directory such as:

```text
analysis/
├── manifest.json
├── environment.txt
├── launch/
├── requests/
├── logs/
├── perf/
├── traces/
├── summaries/
└── REPORT.md
```

Use [../assets/report-template.md](../assets/report-template.md) for the report. Link raw files rather than pasting enormous trace outputs into Markdown.

