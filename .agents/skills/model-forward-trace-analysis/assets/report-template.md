# <Model>: SGLang forward performance and kernel/dtype analysis

## Important conclusions

1. <Absolute-time conclusion with case and evidence>
2. <Scaling or bottleneck conclusion>
3. <Parallelism/communication conclusion>
4. <Dtype/cache conclusion>

## 1. Environment and cases

- SGLang checkout and commit:
- Model path/revision:
- Hardware and topology:
- Software versions:
- Exact launch command:
- Selected backends:
- Parallel configuration:
- Cache/state configuration:
- Warmup and cache policy:
- Request/input/output definition:
- Trace window and repetitions:

| Case | Input/shape | Output work | Concurrency | Parallelism | Notes |
|---|---:|---:|---:|---|---|

## 2. Timing and classification definitions

Define client wall time, SGLang request/stage wall time, GPU activity, stable-step latency, rank aggregation, and every component category.

## 3. Model structure and expected calls

| Component/layer type | Model count | Expected calls in window | Observed logical calls | CUDA launches | Status |
|---|---:|---:|---:|---:|---|

Explain fused or multi-launch operators.

## 4. Client and request end-to-end results

| Case | Client E2E | Server/request E2E | Throughput | Peak memory | Variance |
|---|---:|---:|---:|---:|---:|

## 5. Full phase component distribution

GPU activity duration unless stated otherwise.

| Case | Component | Activity ms | Share | Per-rank range | Evidence |
|---|---|---:|---:|---:|---|

Report unclassified coverage.

## 6. Stable forward/step latency

| Case | Step/forward latency | Work per step | Component absolute ms | Rank imbalance |
|---|---:|---:|---|---:|

## 7. Communication and overlap

| Collective | Calls | Activity ms | Message/shape evidence | Overlap/critical-path note |
|---|---:|---:|---|---|

## 8. Kernel inventory

| Component | Logical op | Representative kernels | Calls | Activity ms | Notes |
|---|---|---|---:|---:|---|

## 9. Dtype flow

```text
<input dtype>
  → <projection/quantization>
  → <kernel operands and accumulator>
  → <cache/state>
  → <output dtype>
```

| Component | Weight storage | Activation input | Cache/state | Accumulator | Output | Evidence |
|---|---|---|---|---|---|---|

## 10. Memory and IO

Separate allocated/reserved/device memory, cache capacity, HBM traffic, and host-device transfer. State whether traffic lies on the critical path.

## 11. Optimization priorities

Prioritize by workload regime and absolute time. Distinguish latency, throughput, memory-capacity, and long-context goals.

## 12. Limitations and evidence gaps

- profiler overhead:
- async timing limitations:
- unclassified activity:
- unsupported dtype/backend A/B:
- inferred dtype or attribution:

## 13. Artifacts

- manifest:
- launch logs:
- request/perf dumps:
- per-rank traces:
- component rules:
- generated summaries:

