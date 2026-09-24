---
name: router-token-kv-alignment
description: Verify that an LLM Router's prompt token IDs match SGLang's backend inputs and KV events, and diagnose cache-aware false hits or missed prefixes across Chat, Responses, colocated and prefill/decode deployments. Use for tokenizer/template/tool/reasoning alignment and KV routing audits, not general generation-quality or throughput benchmarking.
---

# Router Token / KV Alignment

Separate prompt rendering, cache identity, Router prediction, and actual engine reuse. HTTP success or equal token counts do not establish alignment.

## Establish the comparison

Record the exact Router/SGLang revisions, imported Python module paths and dependency versions. Capture model/tokenizer revision, template contents, parser settings, default template kwargs, environment-controlled encoders, page size, speculative token representation, and P/D roles. Inspect active code before adapting private native methods: their signatures are version-dependent.

Respect the requested endpoints, deployment modes, excluded cases, and mutation scope. Prefer existing artifacts and CPU-native rendering for deterministic differences. An audit does not itself authorize changing live services, forcing template semantics, or publishing raw prompts and credentials.

Read [references/workflow.md](references/workflow.md) for renderer, event-consumer, and real-engine procedures. Use the stages needed to resolve the question; do not claim a CPU fixture is a real GPU cache hit.

## Essential invariants

- Compare Router output with the **exact body it forwards**, after normalization and transport serialization. Compare that body with final backend prompt IDs after any truncation/transformation. Preserve the original request too.
- Build an independent native backend oracle. Reusing the Router's template loader on both sides can reproduce the same bug twice.
- Compare full ordered arrays, not lengths, decoded text, sorted IDs, or external block-hash numbers.
- Preserve cache namespaces, model/worker/DP identity, page size and token/bigram representation. Equal tokens do not imply reusable cache.
- Replay native events through the Router decoder, index and lookup. Inspect each worker, not only the globally best result. Control optimistic request-registry credit when isolating KV evidence.
- For P/D, inspect P and D IDs and their bootstrap pairing. Internal request IDs may differ. Decode may use a different routing policy from prefill.
- Tokenizer failure can fall back to load routing and still return HTTP 200. Check token-source/fallback diagnostics and the actual policy.
- Event delay, eviction, incomplete pages and load balancing can explain prediction/actual-hit differences without a rendering bug.

## Reusable comparator

`scripts/compare_token_ids.py` selects arrays from JSON using JSON Pointer and reports exact equality, first differing position, full-array digests, and complete shared pages. Exit codes: 0 equal, 1 different, 2 invalid input.

```bash
python scripts/compare_token_ids.py \
  --router router-preprocess.json --router-pointer /token_ids \
  --backend backend-request.json --backend-pointer /input_ids \
  --page-size 16 --encoding token --out comparison.json
```

For bigram events, reconstruct overlapping raw token sequences first and use `--encoding bigram`. The page count is theoretical, not measured reuse. The helper never silently crops arrays: separate generated output from prompt IDs using backend metadata first.

## Delivery

Give exact triggers, first divergence/page, routing effect and minimal reproduction. Distinguish CPU-native evidence, event fixtures, real HTTP/GPU measurements and source-confirmed limits. Include successful controls and rejected/skipped cases.

If a fix is requested, preserve endpoint/policy isolation and validate neighboring paths. State when backend protocol changes are required. Do not invent missing event metadata or describe load fallback as restored cache-aware support.
