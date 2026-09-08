# Kernel and tensor dtype methodology

## Dtype is a boundary property

For each major component, report these separately when applicable:

| Boundary | Examples of evidence |
|---|---|
| Checkpoint storage | safetensors header, quantization metadata |
| Loaded parameter | `named_parameters()`, loader conversion source |
| Input activation | narrow runtime hook, operator schema/source |
| Temporary quantized input | quantization custom op and GEMM call site |
| Cache or recurrent state | allocation source, server args, runtime tensor |
| Kernel input/output | custom-op schema, Triton/CUDA signature, runtime tensor |
| Internal accumulator | CUDA/Triton/TileLang source, template type, or low-level instruction evidence |
| Inter-layer output | runtime hook or model source |

Never summarize this as one “model dtype” when the boundaries differ.

## Checkpoint inventory

Run:

```bash
python scripts/inspect_safetensors.py <model-or-shard-path> --group-depth 3
```

This proves storage metadata only. Quantization scale tensors, packed weights, indexes, and auxiliary state are not all trainable parameters; describe the script output as tensor elements and bytes unless model semantics establish parameter count.

## Runtime activation probe

For an eager diagnostic run, import `DTypeProbe` from `scripts/dtype_probe.py`, select only relevant modules, and limit recorded calls. Example:

```python
from dtype_probe import DTypeProbe

with DTypeProbe(model, output_path="dtype-rank0.json", module_pattern=r"attn|mlp|experts", max_calls_per_module=2):
    run_one_warm_request()
```

Forward hooks can change timing and may not work through compiled/fused/custom-op paths. Use them for dtype/shape evidence, not headline performance.

## Source inspection

Trace the exact runtime branch from the SGLang model forward into custom ops and backend kernels. Confirm:

- runtime backend selection and fallbacks;
- autocast or explicit casts;
- dynamic activation quantization and scale dtype;
- packed weight layout;
- KV/state write and read dtype;
- dequantization location;
- accumulation and softmax precision;
- epilogue/output cast;
- fused operation boundaries.

If source uses templates or generated kernels, identify the instantiated type from runtime arguments/configuration.

## Quantized paths

Use precise wording. For example:

```text
BF16 hidden state
  → dynamic FP8 quantization + FP32 scale
  → FP8 activation × FP8 checkpoint weight GEMM
  → FP32 accumulation (source-confirmed)
  → BF16 output
```

Do not say “the layer is FP8” when only storage or GEMM operands are FP8 and inter-layer activations remain BF16.

## Cache/state dtype

Separate cache capacity benefits from kernel-speed benefits. A lower-precision KV cache can:

- increase token capacity;
- reduce HBM or host-transfer bytes;
- add quantize/dequantize work;
- select a different backend/kernel;
- change numerical behavior.

When comparing dtypes, hold shape, backend, indexing/sparsity, and schedule constant. If a backend supports only one dtype, report that a clean A/B is unavailable rather than comparing different algorithms as a dtype-only result.

## Internal accumulation

PyTorch profiler and Nsight Systems usually do not prove accumulator dtype. Establish it from kernel source/template configuration or, where necessary, a narrowly targeted Nsight Compute/SASS analysis. Otherwise report `unknown`.

## Dtype report format

For every major path, include a compact flow plus an evidence table:

| Component | Weight storage | Activation input | Cache/state | Accumulator | Output | Evidence |
|---|---|---|---|---|---|---|

Use evidence labels:

- `measured`: runtime tensor or profiler observation;
- `source-confirmed`: exact selected source branch/kernel;
- `inferred`: architecture/config/shape inference requiring confirmation.

