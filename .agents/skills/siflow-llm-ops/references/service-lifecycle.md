# Service Lifecycle

## Contents

- SDK setup
- Snapshot and clone pattern
- Mooncake configuration
- Inference configuration
- Update and scale safety
- Validation checklist

## SDK setup

Use the Python environment containing `siflow`:

```python
from siflow import SiFlow

client = SiFlow(
    region=region,
    cluster=cluster,
    access_key_id=os.environ["SIFLOW_ACCESS_KEY_ID"],
    access_key_secret=os.environ["SIFLOW_ACCESS_KEY_SECRET"],
)
```

Current useful resources and methods:

- `client.inference.get_service(service_id=...)`
- `client.inference.list_service_instances(service_id=...)`
- `client.inference.query_logs(id, ...)`
- `client.inference.query_sys_logs(id, ...)`
- `client.inference.create_service(service_params=...)`
- `client.inference.update_service(service_id=..., service_params=...)`
- `client.inference.online_service(service_id=...)`
- `client.inference.scale_service(service_id=..., scale_params=...)`
- `client.inference.offline_service(service_id=...)`

Inspect method signatures at runtime because SDK versions differ.

## Snapshot and clone pattern

1. Fetch the source service and instances.
2. Convert SDK models with `model_dump(mode="json", by_alias=True, exclude_none=False)`.
3. Save snapshots with mode `0600`.
4. Build a new payload from an allowlist of create/update fields. Remove IDs, status, URLs, Pods, events, timestamps, rollout state, and other server-generated fields.
5. Change only explicitly requested values such as name, image, command, resource pool, replica count, Mooncake endpoint, or backend tag.
6. Validate with the SDK model type before applying.
7. Dry-run by default; apply only after explicit confirmation.

Do not clone a detail-page URL by hand. Fetch the service through the SDK so hidden defaults and role configuration are preserved.

## Mooncake configuration

For the complete workflow that updates an Offline inference service and explicitly brings it
Online, read `mooncake-inference.md`.

Create or identify Mooncake before inference. Validate:

- endpoint/master address is reachable from engine Pods;
- protocol and metadata mode match the cluster;
- each Pod has a unique transfer-engine identity;
- `MOONCAKE_LOCAL_HOSTNAME` uses Downward API:

```yaml
- name: MOONCAKE_LOCAL_HOSTNAME
  valueFrom:
    fieldRef:
      fieldPath: status.podIP
```

- shared workloads use the intended namespace/tag;
- isolated workloads use distinct `extra_backend_tag`, namespace, or store partition;
- old invalid metadata is excluded with a new backend tag when performing a clean verification.

Do not conclude that zero write throughput is a failure by itself. With write-through and content-addressed pages, existing L3 pages may legitimately skip duplicate writes. Use a never-before-seen random prefix to test the write path.

## Inference configuration

Validate all roles independently:

- engine/prefill/decode image and command;
- Router image and command;
- model and tokenizer paths;
- parallelism and replica topology;
- CPU/GPU package and resource pool;
- Router policy and service discovery selectors;
- HiCache policy, size/ratio, page size, storage backend, and backend tag;
- OTel endpoint and trace modules;
- readiness/liveness behavior;
- Mooncake environment.

For custom mode, image and command are supplied directly. An engine version is unnecessary unless the platform workflow requires one.

## Update and scale safety

- Snapshot before updates.
- Preserve source service fields not involved in the request.
- Use update models, not create models, for an existing service.
- Scaling must not rewrite images or commands.
- A Router-only update must not restart engines unless the platform requires it and the user accepts it.
- After update, poll until all expected Pods are ready and compare actual Pod configuration with the requested payload.
- Compare the actual Pod JSON even after creation succeeds. Platform-generated Router commands,
  environment values, ports, or defaults may not preserve the submitted role block verbatim.
- Updating an Offline service does not prove it is Online. Re-read status, then call
  `online_service` only when Online was explicitly authorized; record update and Online results
  separately.
- Record creation times and restart counts because rolling updates reuse logical Pod names.
- Do not call `update_service` merely to retry a service stuck in `queueing`. First inspect the
  instance-quota row and its nodes. An update can create a new workload version and, on some platform
  paths, a separate `-fork` service.
- Deletion requires the service to be Offline. Snapshot the service and instances, obtain explicit
  authorization, offline it, verify there are no running Pods, and only then delete it.

## Validation checklist

- Service status reports all Pods ready.
- Expected number of engine/prefill/decode/Router Pods exists.
- Images and commands match the intended version.
- The exact image digest has evidence for the intended command family and flags.
- Pod environment resolves dynamic values to actual IPs.
- Router discovers all healthy workers.
- No repeated restart, assertion, CUDA, NCCL, or page-retrieval errors.
- Gateway smoke test succeeds.
- A controlled cold/write/hot/read cache test produces the expected L3 behavior.
