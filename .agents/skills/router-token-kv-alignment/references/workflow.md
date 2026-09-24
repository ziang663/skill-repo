# Investigation workflow

## Capture the active boundaries

Record Git HEAD/status, imported Python `__file__`, relevant package versions, CLI arguments and model/tokenizer/template fingerprints. Keep secrets and production prompts out of published artifacts.

Trace the real path:

```text
HTTP JSON → validation/normalization → Router tokenizer → cache key/selection
         → forwarded JSON → backend endpoint/template → scheduler prompt IDs
         → radix pages → KV event wire payload → Router index → next lookup
```

Determine whether the endpoint forwards `input_ids` or makes the backend render again. Shared policy does not imply shared preprocessing. History-dependent fields may be rejected before tokenization.

Compare tokenizer files/revisions, Jinja vs named/JSON conversation templates, HF named-template selection, default kwargs, reasoning/tool parser overrides, native encoder profiles, dynamic template values, automatic truncation, and cache namespaces. Parser differences may affect output only; require evidence before assigning them a prompt effect.

## Select cases

Start with a compact matrix, expanding where differences appear:

- string/messages/text-parts; instructions/system/developer; Unicode and assistant/output replay;
- explicit/omitted thinking and effort, conflicting request kwargs and server defaults;
- function/custom tools, strict/nested schemas, property/tool order, auto/required/none/named choice;
- multiple calls, reversed results, dict/string/truncated arguments, segmented results and opaque reasoning replay;
- output constraints and sampling/metadata as controls;
- namespaces, ordinary/speculative event representation, actual P/D roles.

Respect exclusions for multimodal or hosted-tool execution. Invalid requests are controls, not supported cases. Changes in tools between rounds can legitimately change a cached prefix even when each request aligns perfectly.

## CPU-native rendering

1. Run the exact Router preprocessor and save IDs plus normalized body. Reproduce its transport/schema boundary; do not automatically sort object keys.
2. Construct an independent native backend renderer from the exact SGLang revision and backend config. Use SGLang's `TemplateManager` for explicit templates, not the Router loader. Ordinary text rendering needs tokenizer/config files, not weights/GPU.
3. Render the forwarded body via the backend endpoint adapter. Depending on version, Responses may call `_make_request`/`_process_messages` or Harmony methods. Inspect source rather than assume names.
4. Compare complete ordered arrays and effective kwargs. Alternate Chat/Responses calls to detect shared mutable tokenizer/template state.
5. Inspect stages after rendering: truncation, TokenizerManager transforms and model-specific encoding can still change the final prompt.

Private methods can bypass validation in `create_responses`; equal rendering is not an HTTP-success claim. Identify simulated configuration/clock inputs explicitly. Tool-description fixtures validate rendering, not external tool execution.

## Event-consumer verification

Prefer captured events. Otherwise build labeled fixtures with the native SGLang event recorder from controlled backend tokens.

- Preserve parent links, worker/rank, storage tier, page size and namespaces. Cached pages exclude incomplete tails; generated tokens may extend the chain beyond the prompt.
- Bigram events may contain adjacent pairs. Reconstruct raw sequences without duplicate boundary tokens and distinguish logical page length from raw token count.
- Feed actual wire payloads through the Router decoder/importer/policy. Do not substitute an imitation of its hash algorithm.
- Engine external hashes can identify parentage/removal while local Router hashes are recomputed from event tokens; numeric inequality between hash families is not a defect.
- Inspect all workers/ranks/tiers. Test each representation independently before mixed-pool tests.
- Test same tokens with same, different and absent/empty namespaces according to engine semantics. Missing event metadata cannot be recovered by assuming a default.
- Control optimistic request-registry credit: repetition may earn credit before events arrive. Keep token-based load accounting when verifying conservative fallback.

Historical hypotheses, not universal defects: omitted request salt; unidentifiable `extra_key`; ordinary matches suppressing bigram lookup; one model index assuming one page size; manual vs native template loading; independent server defaults or dates. Confirm against the current version and requested deployment.

## Real-engine validation when needed and authorized

Use independent test services or approved request scope. Record resource identity and clean up only resources created for the test. Follow operational snapshot/authorization requirements before changing existing services.

Capture preprocessing output, forwarded body, final backend prompt IDs, event stream, selected worker/rank, routing costs and actual backend cached-token counters. Direct-engine controls should use the same normalized body to isolate routing from default/thinking semantics; separately track changes from original JSON.

Use a synthetic long-prefix cold/warm pair spanning several pages. Observe event ingestion rather than rely on an arbitrary sleep. Account for prior cache warming. Cover colocated/P/D, JSON/SSE, mixed endpoints as requested. Join P/D by verified bootstrap room/host/port rather than assuming response IDs match.

Check response semantics, terminal events and input IDs together. Small reasoning budgets can cause normal output truncation. Compare tool/schema rejections with direct backend behavior before blaming the Router.

## Evidence and completion

Keep fingerprints, synthetic cases, original/normalized bodies, arrays, comparisons, wire events, consumer results and commands. Link raw artifacts from a concise report. State what aligns/diverges, the first differing page, namespace/worker effect, actual reuse only where measured, skipped cases, and whether changes are proposed/implemented/verified/published.

After a fix, rerun the failing case and appropriate endpoint-isolation controls. Do not expand the repair into unrelated policies or user-authored template semantics.
