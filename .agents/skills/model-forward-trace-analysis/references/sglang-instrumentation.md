# SGLang instrumentation

Use only the instruments needed for the requested claim. Verify flags against the installed SGLang and profiler versions; SGLang interfaces evolve.

## Evidence sources

| Source | Best use | Important limitation |
|---|---|---|
| Client timer | user-observed E2E | includes transport, polling, serialization |
| SGLang perf/stage dump | request and stage wall time | asynchronous CUDA work may shift between adjacent scopes without synchronization |
| SGLang logs/NVTX | phase and call-site boundaries | coverage depends on instrumentation |
| PyTorch profiler | CPU ops, CUDA kernels, shapes, stacks | large overhead; dtype and fused-kernel attribution may be incomplete |
| Nsight Systems | kernel timeline, streams, NVTX, NCCL | kernel duration sum is GPU activity, not necessarily critical-path wall time |
| Nsight Compute | selected-kernel instructions, memory traffic | expensive and unsuitable for whole-request tracing |
| Runtime hooks | module input/output dtype and shape | misses functional/fused internals and can perturb execution |
| Source/config inspection | exact branch, cache layout, accumulator types | proves intended code path only when runtime selection is also confirmed |

## Discover supported SGLang controls

Do not assume flags from another checkout. Inspect the current tree and CLI:

```bash
<python> -m sglang.launch_server --help
<sglang-cli> serve --help
rg -n "perf_dump|profiler|nvtx|enable_trace|torch.profiler|cudaProfiler" <sglang-checkout>/python/sglang
```

Save the resolved server arguments printed at startup. Confirm the worker ranks, selected backends, and any fallback messages.

## Request-level timing

If the target SGLang endpoint supports a request perf-dump path, use it for every measured request. Otherwise add the narrowest possible instrumentation around the relevant stage in a throwaway profiling branch. Never represent an asynchronously timed stage as exact GPU duration without synchronization evidence.

Run `scripts/summarize_sglang_perf.py` on produced JSON files. Its first-step warning is diagnostic, not proof; inspect the source scope and timeline before excluding data.

## Nsight Systems collection

Launch under Nsight Systems when a bounded process/request is available:

```bash
nsys profile \
  --trace=cuda,nvtx,cublas,cudnn,osrt \
  --sample=none \
  --cpuctxsw=none \
  --force-overwrite=true \
  --output=<artifact-prefix> \
  <sglang-command> <args...>
```

For a long-running server, prefer an NVTX or CUDA-profiler capture range around the measured request. Check `nsys profile --help` for the installed syntax, then instrument request boundaries in SGLang if the path lacks a usable range. Avoid treating startup compilation/loading as request work.

Export a queryable database and standard summaries:

```bash
nsys export --type=sqlite --output=<trace>.sqlite <trace>.nsys-rep
nsys stats --report=cuda_gpu_kern_sum,nvtx_sum <trace>.nsys-rep
```

Capture one file per rank when possible. Preserve rank IDs in filenames.

## PyTorch profiler

Use PyTorch profiler for operator-to-kernel stacks, shapes, and memory diagnostics when Nsight/NVTX attribution is insufficient. Restrict the schedule to warmup plus a few stable steps. Typical diagnostic settings include CUDA and CPU activities, `record_shapes=True`, `with_stack=True`, and `profile_memory=True`.

Profiler overhead changes latency. Use unprofiled runs for headline E2E performance and profiled runs for attribution unless the overhead is demonstrated negligible.

## Stable decode or denoise windows

- Synchronize all ranks before the selected window when measuring a synchronized phase.
- Record active batch, tokens per step, context length, and cache occupancy for decode.
- Record NFE index, latent shape, conditioning layout, and scheduler state for diffusion.
- Keep enough consecutive steps to expose steady behavior and rank imbalance.
- Do not average prefill and decode, or preparation and denoise, into a single “forward” number.

## Communication capture

Ensure NCCL kernels and NVTX ranges are present. Separate:

- all-reduce;
- all-gather;
- reduce-scatter;
- all-to-all;
- point-to-point/send-recv;
- synchronization or waiting.

Kernel duration alone does not prove network time is on the critical path. Inspect overlap with compute and compare rank timelines.

## Trace sanitation

Before sharing artifacts, review command lines, environment strings, NVTX labels, request payloads, hostnames, and filesystem paths for credentials or private data.

