# Image validation and handoff

Build success, content verification, local source tests, and serving acceptance
are distinct claims. Match the verification scope to the requested change and
available authorization; leave unperformed checks explicitly unverified.

## Reproduction before packaging

When a bug fix needs local before/after evidence:

1. Match the baseline engine/router to the affected image using immutable source
   identities and file hashes. Preserve the original failing payload.
2. Run potentially worker-fatal reproducers only on an authorized isolated target.
   Snapshot process identities, rank counts, logs, and restarts.
3. Exercise the fixed path and adjacent normal behavior. An expected unsupported
   request should fail in a controlled way without terminating other requests.
4. For streams, inspect terminal events and body errors. HTTP 200 followed by
   `response.failed` is a failed request, not a passing Responses test.
5. Record differences in weights, tokenizer, dependencies, topology, and launch
   configuration. Identical tokenizer hashes do not prove identical weights.
6. Freeze the tested source commit/bundle before packaging. Do not include later,
   untested changes in the claimed result.

Keep failed intermediate tests as evidence. Report a flaky rerun honestly; do not
delete or skip a failing case merely to satisfy the build gate.

## Content verification without a GPU

Use an authenticated OCI/Docker registry client or registry v2 APIs to inspect the
manifest and config. Keep authentication in the approved credential mechanism, not
in URLs, command output, committed files, or reports. Resolve a multi-platform
index to the intended platform manifest when necessary.

Check:

- final registry digest and expected base ancestry;
- config environment, entrypoint, command, labels, and platform architecture;
- actual source-file hashes and generated package/version metadata;
- imported module locations through the final image's Python environment;
- native extension and dependency compatibility;
- exact router binary/helper hashes when a unified image should preserve them;
- hard assertions and test result artifacts for the requested fix.

Config/history inspection does not execute imports. Claim import/test success
only when it ran in the build, a local matching runtime, or the final image, and
name which environment supplied the evidence.

Selected top layers can answer narrow file questions without a full image pull.
Account for later overwrites and OCI whiteouts; finding a file in an earlier layer
does not prove it survives in the final root filesystem. Extract only needed paths
into an isolated directory and reject unsafe archive paths.

## Runtime acceptance, when authorized

Start the intended image digest on an isolated target with a supported GPU/model
shape. Do not assume a fixed GPU count works for every model. Inspect the actual
container image, command, mounts, runtime environment, and imported source paths;
the submitted deployment payload alone does not prove what ran.

Require engine readiness plus healthy canonical endpoints, then send bounded
functional requests appropriate to the changed path. Check HTTP and response-body
success, streaming completion, expected controlled errors, process continuity, and
engine/router logs. Run the original reproducer when safe and required.

For metrics-enabled SGLang deployments, check scheduler inheritance of
`PROMETHEUS_MULTIPROC_DIR` and the presence of `sglang:num_running_reqs` and
`sglang:num_queue_reqs`, even when zero. Use equivalent names only after confirming
a version-specific metric change. Do not infer metrics for unexposed TP ranks.

For the external unified router, verify discovered worker count and, when exposed,
`vllm_router_active_workers` and
`vllm_router_backend_metrics_scrape_success_workers`. Test through both router and
worker when distinguishing forwarding failures from engine adapter failures.

Only require FlashBoot imports/cache artifacts or speculative acceptance metrics
when those features are part of the requested image. An enabled flag alone does
not prove successful cache reuse or useful speculative decoding.

## Completion report

Provide the image URL/digest, engine and router identities, and a compact account
of these separate results:

- baseline reproduction and fixed local regressions;
- image build and in-build tests;
- registry content/provenance checks;
- model runtime acceptance from the final image, if performed;
- online rollout, only if explicitly requested and actually performed.

List remaining limits such as different local weights, no final-image GPU run, no
long-context test, or no accuracy evaluation. A narrow regression pass does not
automatically clear every case in an earlier acceptance report.

State whether temporary validation resources remain running and their resource
use. Release them only within the user's authorization; a build-only task should
not create serving resources or change an existing service.
