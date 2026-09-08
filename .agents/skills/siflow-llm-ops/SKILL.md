---
name: siflow-llm-ops
description: Install and use the SiFlow Python SDK, and operate or diagnose SiFlow LLM and SGLang diffusion/video inference, Router, HiCache, and Mooncake services. Use for SDK setup, creating or updating inference/Mooncake services, validating custom images and commands, inspecting pods and configuration, collecting logs and traces, analyzing cache hit/TTFT/restarts, and producing evidence-based deployment or incident reports.
---

# SiFlow LLM Operations

## SDK setup

If `from siflow import SiFlow` fails or the SDK must be installed/upgraded, read
`references/sdk-installation.md` before calling service APIs. Important invariants:

- SiFlow is not published on public PyPI. Download the official wheel from the SiFlow OSS URL template documented in the reference.
- Use an isolated virtual environment; do not uninstall or replace packages in the system Python.
- Install the `websocket` extra when log streaming or log collection may be needed.
- Verify the installed distribution version, import, and dependency consistency before using credentials.
- Do not confuse the SDK version in the wheel filename with examples for older releases. Keep the download and install versions identical.

## Core workflow

1. Identify `region`, `cluster`, tenant, owner, service ID, and requested mutation scope.
2. Snapshot the service and instances before any mutation with `scripts/inspect_service.py`.
3. Prefer a known-good service as the configuration source. Preserve fields that the user did not request changing.
4. For a custom image, prove that the exact image digest supports the intended command family and flags. Do not infer SGLang diffusion support from an LLM `sglang serve` CLI, a different virtual environment, or a similarly named image.
5. Create Mooncake before inference when inference depends on a dedicated Mooncake endpoint.
6. Treat service creation/update as destructive: prepare payloads first, show the meaningful diff, and require explicit user intent before applying. A failed create does not authorize an automatic retry.
7. Validate readiness, actual Pod image/command/environment, replica count, Router policy, endpoint, and Pod restart state. Platform-generated Router configuration can differ from the submitted role command.
8. Collect evidence from SiFlow logs first. Logs can be empty before the first container start and appear after a restart; poll once after the lifecycle transition before falling back to OmniObs. On Pisces, read `references/observability.md` for split-horizon DNS handling and complete-window downloads.
9. Correlate engine logs, Router logs, OTel traces, Kubernetes lifecycle, and replay results before assigning a root cause.
10. Save raw evidence and a concise Markdown report. Separate confirmed facts, likely mechanisms, amplifiers, and unknowns.

## Credentials and safety

- Read credentials only from environment variables or an approved secret store.
- Use `SIFLOW_ACCESS_KEY_ID` and `SIFLOW_ACCESS_KEY_SECRET` for the SDK.
- Use `OMNI_TOKEN` for OmniObs. Never write credentials or tokens into Skill files, reports, payload snapshots, or shell history.
- Use the account authorized for the object: engine-version administration may require a platform/engine tenant account; inference and Mooncake service operations may require the serving tenant account.
- Default to read-only inspection. Never delete, offline, recreate, restart, scale, or update a live service unless the user explicitly requests it.
- Snapshot before mutation and verify after mutation. Do not silently rebuild a failed service.

For private SiFlow/Router source repositories, read `references/gitlab-access.md` when SSH is
unreachable or GitLab token authentication is required. Keep tokens out of clone URLs, remotes,
Git configuration, reports, and command output.

## Service operations

Read `references/service-lifecycle.md` before creating or updating a service. Key rules:

- Mooncake first, inference second.
- For custom mode, configure image and command directly; do not create an engine version unless required.
- Keep engine and Router images aligned when the image is unified.
- Use Kubernetes Downward API for `MOONCAKE_LOCAL_HOSTNAME=status.podIP`; never use a literal placeholder.
- Give independent workloads distinct Mooncake namespaces/tags when isolation is required.
- For scaling, update only replica/resource fields and preserve commands, images, environment, and Router policy.

When enabling Mooncake on an existing inference service or bringing a Mooncake-backed service
Online, also read `references/mooncake-inference.md`. Treat configuration update and Online as two
separate state transitions, and require explicit authorization for both.

For a new SDK-created LLM Inference service, also read
`references/inference-deployment.md`. It covers resource discovery, split Engine/Router pools,
engine-version registration, payload validation, safe creation, queueing diagnosis, and acceptance.

For SGLang diffusion or video-generation workloads, also read
`references/sglang-diffusion-deployment.md`. These workloads can use a different CLI parser,
request API, startup sequence, cache footprint, and observability surface from SGLang LLM serving.
Use `scripts/smoke_video.py` for an authorized minimal asynchronous video smoke test.

Important deployment invariants:

- The account that manages an Engine Config can differ from the serving tenant that owns quota.
  Create the service with the serving tenant's credentials.
- In pool-list responses, `id` is the instance-quota ID used by node/quota inspection APIs, while
  `resourcePoolId` is the pool ID used by an inference-service payload. Do not interchange them.
- Check both aggregate quota and per-node placement. Eight free GPU units do not prove that a
  schedulable 8-GPU node exists.
- A Router may use a different CPU pool through `roleConfig.server.routerConfig`; do not consume a
  GPU package for a CPU-only Router merely because the Engine's top-level pool is GPU-only.
- Do not use `update_service` as a retry mechanism for a queueing create. Some platform paths can
  create a `-fork` service or a new workload version. Diagnose capacity first.
- A service must be Offline before deletion. Never offline or delete it without explicit authority.
- Use `scripts/deploy_inference.py` for payload validation and guarded creation. It dry-runs unless
  `--apply` is supplied and refuses exact duplicate names.
- SiFlow requires a non-empty HF token field even for public repositories. Use the literal
  `anonymous` for a public model; never place a real Hugging Face token in a payload or evidence.
- If creation fails, query the exact service name and report the error. Do not retry, update, fork,
  offline, or delete unless the user explicitly authorizes the next mutation.
- Treat `usage:` followed by `unrecognized arguments` and a restart loop as an image/CLI
  incompatibility. Stop waiting for model download and report the unsupported flags.

## Logs and traces

Read `references/observability.md` for API details and field interpretation.

When the console shows a Pod `Terminal` action but the SDK has no exec method, read
`references/pod-terminal.md`. Use `scripts/pod_terminal.py` for authenticated,
read-only inspection inside a live Pod. Treat arbitrary shell commands as live
production mutations according to what they do; never write to a CUDA corepipe merely
to test it.

Useful commands:

```bash
python scripts/inspect_service.py \
  --region us-west --cluster volans --service-id 87 --out evidence/service-87

python scripts/fetch_omni_logs.py \
  --from-ms 1786520400000 --to-ms 1786524000000 \
  --pods pods.json \
  --filter 'cluster="volans" AND namespace_name="t-simaas-user"' \
  --outdir evidence/raw

python scripts/query_omni_traces.py \
  --start-ms 1786520400000 --end-ms 1786524000000 \
  --resource-tag k8s.namespace.name=t-simaas-user \
  --out evidence/traces.json

python scripts/summarize_prefill_cache.py \
  --input 'evidence/raw/*prefill*.ndjson.gz' \
  --instances evidence/service-87/instances.json \
  --output evidence/cache-hit.md
```

## Diagnosis standards

- Cache hit: exclude health checks and count one canonical scheduler rank only. Prefer token-weighted `cached / (cached + new)`.
- TTFT: separate Router wait, engine queue, model prefill, L2/Host load-back, and L3/Mooncake load-back.
- Restarts: distinguish application assertion, CUDA/NCCL allocation failure, OOMKilled, SIGKILL/137, liveness kill, and graceful exit.
- Mooncake: distinguish “page already exists, skip duplicate write” from “write path broken.” Prove with a new-prefix cold-write/hot-read experiment.
- Router: compare Router cache-map match with engine actual cached tokens and selected prefill/engine IP.
- Rolling restart: use each Pod's actual creation time; never aggregate old and new containers with the same Pod name.

## References

- `references/sdk-installation.md`: official wheel download, isolated installation, validation, upgrade, and offline reuse.
- `references/service-lifecycle.md`: creation, update, scaling, Mooncake configuration, and validation.
- `references/inference-deployment.md`: guarded SiFlow SDK deployment and queueing diagnosis.
- `references/sglang-diffusion-deployment.md`: image/CLI preflight, persistent HF cache, MiniMax-H3 deployment, asynchronous video smoke testing, and diffusion-specific acceptance.
- `references/mooncake-inference.md`: Mooncake payload changes, Offline update, explicit Online, and L3 acceptance.
- `references/observability.md`: SiFlow SDK logs, OmniObs logs/traces, cache and restart analysis.
- `references/pod-terminal.md`: authenticated WebSocket Pod terminal access, protocol, safety, and ephemeral-versus-shared evidence.
- `references/gitlab-access.md`: safe, transient GitLab HTTPS authentication when SSH is blocked.
