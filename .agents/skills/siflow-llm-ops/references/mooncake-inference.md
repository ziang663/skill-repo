# Mooncake-backed LLM Inference

Read this reference when adding Mooncake to an existing SiFlow LLM Inference service, changing its
Mooncake-backed topology, or bringing that service Online.

## Preconditions

- Identify region, cluster, serving tenant, owner, service ID, resource pools, images, model, and
  intended Router/Engine replica counts.
- Confirm the Mooncake control endpoint and RDMA path are valid for the target cluster.
- Snapshot the service, current instances, and offline instances before mutation.
- Prefer updating an Offline service. Wait for old Pods to exit before changing cache identity or
  replica topology.
- Obtain explicit authorization for the update and for bringing the service Online. Do not infer
  either permission from a previous create, scale, or diagnostic request.

## Payload changes

Build `ServiceUpdateParams` from an allowlist of the service snapshot. Do not submit IDs, status,
URLs, timestamps, Pods, events, or rollout state.

Preserve unchanged images, commands, pools, volumes, Router policy, selectors, probes, and OTel
settings. Change only the authorized replica/resources and Mooncake fields.

The Engine needs L2 HiCache plus an L3 backend, for example:

```text
--enable-hierarchical-cache
--hicache-ratio <validated ratio>
--hicache-write-policy write_through
--hicache-mem-layout <layout>
--hicache-storage-backend mooncake
--hicache-storage-prefetch-policy timeout
--hicache-storage-backend-extra-config '{"extra_backend_tag":"<cache namespace>"}'
--enable-metrics
--enable-metrics-for-all-schedulers
```

Required environment varies by cluster, but typically includes:

```text
MOONCAKE_MASTER
MOONCAKE_PROTOCOL=rdma
MC_STORE_CLUSTER_ID
MOONCAKE_TE_META_DATA_SERVER=P2PHANDSHAKE
MOONCAKE_GLOBAL_SEGMENT_SIZE=0
MOONCAKE_LOCAL_HOSTNAME=<current Pod IP>
```

Inject the Pod IP with Kubernetes Downward API and derive `MOONCAKE_LOCAL_HOSTNAME` from it. Never
hard-code one node or Pod IP into a multi-replica service.

The `extra_backend_tag` is a cache compatibility boundary. Include the model/version, KV dtype,
memory layout, page size, and any parallel-sharding dimension that changes KV bytes. Use a new tag
when any compatibility dimension changes. Do not share a tag merely to increase hit rate.

Validate and serialize the canonical payload before applying:

```python
from siflow.types.inference import ServiceUpdateParams

params = ServiceUpdateParams.model_validate(payload)
canonical = params.model_dump(mode="json", by_alias=True, exclude_none=True)
```

Inspect the diff and verify that Router `service-id`, `service-name`, namespace, role selector, and
worker port still target the service being updated.

## Update and Online

Apply the intentional configuration update once:

```python
updated = client.inference.update_service(
    service_id=service_id,
    service_params=params,
)
```

Verify `updated == service_id`, fetch the service again, and confirm the stored spec matches the
canonical payload. Do not use repeated updates to retry queueing or to start the service.

If Online was authorized, start it explicitly:

```python
online = client.inference.online_service(service_id=service_id)
```

Record update and Online results separately. A successful update does not prove that an Offline
service was started.

## Startup acceptance

Poll service and instance APIs until the expected Router and Engine Pods are Ready. Validate:

- actual replica count, image, command, resources, volume mounts, environment, Pod IPs, and restart
  counts;
- FlashBoot target and draft loads, expected compile-cache reuse, MXFP4 layout, CUDA Graph, and
  Engine Ready;
- HiCache L2 allocation and Mooncake metadata/transfer-engine initialization;
- Router discovery of every Engine, KV Event subscribers, intended policy, and OTel initialization;
- `/health`, `/v1/models`, deterministic generation, and sampling generation through the Gateway.

For OTel, use an explicit W3C `traceparent` when a known trace ID is needed. A response
`x-request-id` is not automatically an OTel Trace ID. Confirm the injected ID in OmniObs before
using it as evidence.

Absence of `/v1/loads` in Router logs is not evidence that `cache_aware` is disabled. Validate the
policy with Router span attributes, selected worker distribution, KV Event subscription, and Engine
cache behavior.

## L3 correctness test

Do not judge Mooncake solely by aggregate write throughput. Content-addressed pages may already
exist and valid duplicate writes may be skipped.

Use a controlled sequence:

1. Send a never-before-seen random prefix and complete the request.
2. Confirm no metadata, RDMA, page-write, or transport error.
3. Flush local GPU/Host runtime cache without deleting the Mooncake namespace.
4. Repeat the identical prefix.
5. Confirm Storage/L3 cached tokens or load-back evidence and correlate it with TTFT.

If the first request writes nothing because the page already exists, use a new random prefix and a
new cache tag only when isolation is required. Distinguish duplicate-write skipping from a broken
write path.

Save the canonical payload, before/after service snapshots, instance snapshots, startup logs,
smoke-test responses, trace IDs, and cold/write/hot/read evidence without credentials.
