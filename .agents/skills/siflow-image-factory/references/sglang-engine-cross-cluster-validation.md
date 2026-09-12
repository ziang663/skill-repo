# Cross-cluster images and P/D acceptance

Read this when the requested image needs publication across clusters, patched
NCCL, or prefill/decode disaggregation (P/D), multi-token prediction (MTP), and
hierarchical cache (HiCache) validation. Apply only the requested features and
authorized deployment scope.

## Immutable inputs and destination choice

Record SGLang/router commits, the engine target and Dockerfile, destination
region/cluster/tenant, intended tags, base digests, patch hashes/semantic IDs,
and exact NCCL commit when replaced. For runtime acceptance, additionally record
model paths, topology, resource pools, mounts, and known-good launch configuration.

Choose the publication mechanism deliberately:

- Independent per-cluster builds need distinct recipes/manifests and must preserve
  identical intended source and patch inputs. Dry-run every changed stage and
  follow each returned image ID independently.
- An authorized registry-to-registry copy, such as `crane copy`, can preserve
  manifest identity. Verify the destination digest and target pull access rather
  than assuming success from a source-side record.
- A target-cluster build with `ARG SRC_IMAGE` / `FROM ${SRC_IMAGE}` can reuse a
  source-cluster image when builder authentication permits it. Assert a marker
  unique to the source image. This path pays the export cost again and may change
  registry digests through recompression; compare content, not digest equality.

The documented SDK has no cross-cluster sync operation: `images.share` grants
project-group access, not a registry copy. Tenant-wide image listing does not prove
pullability in a destination cluster. Use the platform's per-cluster URLs and
actual registry/pull evidence. Do not probe forbidden admin routes or silently
change destinations after an authorization failure.

## Prove a custom NCCL build

Do not infer runtime loader selection from compilation alone. Require:

- exact NCCL commit and patch SHA256;
- `git apply --check` against that commit, followed by a semantic patch anchor;
- successful production of the patched library for the target architecture;
- provenance for engine/NCCL commits and patch identity;
- runtime loading of the intended library and expected `ncclGetVersion()` value.

Python wheels can carry another library under `nvidia.nccl`. Verify both system
and wheel-visible paths, loader search order, and the actually loaded file.
Matching the version number alone does not prove the patched bytes were loaded.
Changing the NCCL release is acceptable only with justified patch semantics and
the required build/runtime tests.

## Classify before rebuilding

Rebuild only when evidence identifies an image-content defect. Queueing,
insufficient quota, fragmented GPU placement, absent Engine Config permissions,
image rewriting by a service template, mount/network configuration errors, or
an active but slow model load are not by themselves reasons to increment a tag.

For each failed attempt, identify whether the evidence points to build, registry,
deployment configuration, scheduling, startup, or request serving. Change only
the implicated layer. Stop for direction when the necessary action requires new
authority, such as an ACL change or shared Engine Config update.

## Preserve the image under test

Prefer a standard service when authorized and when it actually retains the
requested role images. Re-read service and instance state; the platform may apply
an Engine Config image instead. Administrative permission and serving quota can
belong to different accounts.

If a standard service cannot preserve the requested image, propose isolated VSCS
instances using the known-good bare-Pod topology. Confirm authorization and quota
before creating them; this fallback validates the image/topology, not the standard
service template. Do not implicitly allocate a fixed number of full GPU nodes.

Check aggregate quota **and** complete-node placement for the intended shape.
Pool visibility or `avail > 0` does not imply `authorized=true`; resource-admin
status may also be insufficient. Do not modify `authorizedUsers` as an automatic
repair. If separately authorized, snapshot the ACL and preserve unrelated entries.

Enumerate InfiniBand devices from each target node and use the appropriate ACTIVE
ports. Do not copy another cluster's device list verbatim.

Audit `PYTHONPATH` shims and source mounts. Prefer incorporating needed changes
into the pinned image for acceptance. If deliberately retained, fingerprint them
and describe the result as **image plus override**, not the unmodified image.
Record actual imported module paths.

## Startup and scoped acceptance

A quiet log is not sufficient evidence of a hang. Correlate process state, CPU
activity, GPU memory/utilization, log movement, Pod restart count, and events.
Avoid restarting an engine that is making progress. Require the version-specific
ready signal plus `/health`, then inspect effective server configuration.

| Area | Evidence when applicable |
|---|---|
| Identity | Engine/router/NCCL commits, patch hashes, actual image and loaded library match provenance |
| Runtime source | Imported modules come from the intended image; overrides are absent or fingerprinted |
| Resources | GPU/model shape, weights, mounts, network interfaces, and active IB devices are correct |
| Readiness | Every required P/D rank is ready; health/server-info succeed without a restart loop |
| P role | Intended topology and `disaggregation_mode=prefill`; role-specific counters/logs show prefill work |
| D role | Intended topology and `disaggregation_mode=decode`; role-specific counters/logs show decode work |
| MTP | Required target/draft/NextN ranks load and effective speculative settings/behavior are observed |
| HiCache | Hierarchical cache is enabled and repeated long prefixes produce cached-token evidence |
| Router | Healthy discovery of expected P/D workers and correct model exposure |
| Requests | Deterministic smoke and bounded concurrent requests pass HTTP, body, and stream-terminal checks |
| Logs | No unclassified CUDA/NCCL/OOM/scheduler/fatal errors during the measured window |

Configuration flags alone do not prove P/D separation, MTP effectiveness, or cache
reuse. For reasoning models, a tiny output budget may end before final content;
repeat with an appropriate bounded budget before calling that an engine defect.

Successful startup and a short burst do not validate a low-probability collective
hang. Use a dedicated reproducer or separately authorized soak for that claim.
Keep redacted deployment payloads, server-info, requests, and logs with the build
evidence. Report untested cases and remaining resource consumption; release
validation instances only within the user's authorization.
