# Component attribution and call-count validation

## Attribution hierarchy

Assign a kernel to a component using the strongest available evidence:

1. a request/phase-specific NVTX range around the exact call site;
2. PyTorch operator stack or custom-op name tied to SGLang source;
3. model module hooks plus source-path confirmation;
4. distinctive backend kernel names;
5. shape/timeline inference, explicitly labeled as inferred.

Do not classify a generic GEMM, elementwise kernel, or memcpy solely by its name. One generic kernel can serve projections, FFNs, routers, codecs, or LoRA updates.

## Suggested logical categories

Choose only categories present in the actual model:

- embedding and output/logits head;
- attention projections;
- dense, sparse, MLA, or linear-attention main kernels;
- indexer/retrieval/top-k candidate selection;
- KV/state cache writes and updates;
- RoPE/position encoding;
- norm, residual, gating, and elementwise operations;
- dense FFN;
- MoE router, dispatch, expert GEMMs, combine, and shared experts;
- quantize, dequantize, activation scaling, and packing;
- communication by collective type;
- VAE/audio/video codec and serialization for SGLang multimodal generation;
- runtime/memory operations;
- unclassified.

Define each category before presenting a table. State inclusions and exclusions, especially for projections, indexers, fused shared experts, and communication.

## Ordered mapping rules

`scripts/analyze_gpu_trace.py` accepts an ordered JSON rule set:

```json
{
  "rules": [
    {"component": "Communication", "pattern": "nccl|all[_ -]?reduce|all[_ -]?to[_ -]?all"},
    {"component": "MoE", "pattern": "deepgemm|grouped_gemm|moe|expert"},
    {"component": "Attention", "pattern": "flash.*attn|fmha|attention"}
  ],
  "default": "Unclassified"
}
```

Rules are first-match-wins. Put specific patterns before broad patterns. Treat the bundled example as a starting point, then replace or augment it with model-specific NVTX/operator names.

## Coverage requirements

Always report:

- classified and unclassified GPU activity;
- top unclassified kernels by absolute duration;
- kernels matching multiple conceptual components;
- whether activity is rank mean, rank maximum, or one rank;
- whether overlapping streams exist.

High unclassified activity is a result, not permission to guess. Add instrumentation or narrow the claims.

## Logical calls versus CUDA launches

Build an expected-call table from the model config and measured window:

```text
expected calls = layer count × forwards/steps × active branches × batch-specific multiplicity
```

Then compare with NVTX/module/operator observations. Examples:

- autoregressive stable decode: layer count × captured decode steps;
- diffusion: transformer layer count × captured NFE count;
- MoE: router called per MoE layer, but expert grouped GEMM launches depend on backend and token routing;
- tensor/sequence parallel: each logical layer appears on every participating rank;
- fused operators can combine multiple logical operations in one launch;
- one logical projection can launch quantization, scale, GEMM, epilogue, and communication kernels.

Report both logical call counts and CUDA launch counts; never substitute one for the other.

## Multi-rank analysis

For each component calculate per-rank activity and imbalance:

```text
imbalance ratio = max(rank activity) / mean(rank activity)
```

For synchronized iterations, the slowest rank often bounds wall time, but verify barriers/collectives on the timeline. A rank can show less compute activity yet still determine latency through wait or communication ordering.

## Percentages and optimization claims

Present absolute milliseconds before percentages. Compare like-for-like windows and normalize by produced tokens/NFEs where appropriate. When a component percentage rises, determine whether its absolute time grew or other work shrank.

