# SiFlow SDK LLM Inference deployment

Read this reference when creating a new LLM Inference service through the Python SDK.

## Identity and target

Resolve these before preparing the payload:

- region and cluster;
- serving tenant and owner;
- the account allowed to create Engine Configs;
- the account that owns CPU/GPU quota and volumes;
- Engine and Router images;
- model and shared-volume paths;
- Engine and Router replica topology.

Engine Config administration and service creation may require different identities. Never infer that
an account able to register an Engine Config also owns serving quota.

## Resource discovery

Use the serving tenant's credentials. Query:

```python
client.pools.list(page=1, page_size=100)
client.pools.list_visible_instances()
client.inference.list_resource_packages(resource_pool_id=POOL_ID)
client.volumes.list(page=1, page_size=100)
client.admin.get_instance_quota_info()
```

Pool-list rows expose two different IDs:

- `id`: instance-quota ID. Pass this to `pools.get`, `pools.list_nodes`, and
  `user_quotas.list_typed`.
- `resourcePoolId`: pool ID. Put this in `ServiceCreateParams.resourcePoolId` and Router
  `resourcePoolId`.

For each selected package, inspect:

```python
client.pools.get(INSTANCE_QUOTA_ID, pool_type="exclusive")
client.pools.list_nodes(INSTANCE_QUOTA_ID, page=1, page_size=100)
client.user_quotas.list_typed(instance_quota_id=INSTANCE_QUOTA_ID)
```

Separate these quantities:

- tenant/user quota remaining;
- unavailable quota from cordoned or unhealthy nodes;
- schedulable full-node capacity;
- pending reservations and existing workloads.

An aggregate `avail >= 8` is insufficient for an 8-GPU Pod if the scheduler cannot place all eight
units on one eligible node.

## Engine Config

List existing versions and compare the version name exactly before creating one:

```python
versions = client.inference.list_engine_versions(page=1, page_size=100)
match = [item for item in versions if item.version == desired_version]
```

For a unified image, keep `image` and `routerImage` aligned. Save the validated
`EngineVersionCreateParams` payload with mode `0600`; never include credentials.

## Service payload

Build `ServiceCreateParams` from an allowlist. Do not copy status, IDs, URLs, timestamps, Pod data,
rollout state, generated labels, or stale role configuration from a service detail response.

Validate independently:

- top-level Engine GPU pool and package;
- Router CPU pool in `roleConfig.server.routerConfig` when different from the Engine pool;
- Engine and Router image, command, environment, replicas, ports, and probes;
- shared volume ID, mount path, model path, and shard path;
- Router selector, namespace, backend, policy, and intra-node DP size;
- OTel endpoint and trace flags for both roles;
- target and speculative-draft load formats;
- HiCache layers and the deliberate presence or absence of Mooncake.

When Mooncake is disabled, recursively reject `MOONCAKE_*`, `MC_*`, and
`--hicache-storage-*` from the payload.

Use `scripts/deploy_inference.py` to validate and save a canonical payload. It does not contact the
API unless `--apply` is explicitly supplied.

## Create and monitor

Before creation, search all returned services and compare names exactly. Do not rely on a fuzzy
`name`/`search` result alone.

After creation, poll both:

```python
client.inference.get_service(service_id=service_id)
client.inference.list_service_instances(service_id=service_id)
```

Record each transition: `queueing`, Pod creation, image pull, container start, Engine startup,
Router registration, readiness, and smoke-test result.

## Queueing and retry safety

For `quota check error`:

1. Identify the clause that contains the actual failure, such as
   `test/sci.g21-3: Resource fragmentation cannot be scheduled`.
2. Treat following `Please visit ...` clauses as resource-detail links, not independent proof that
   every listed resource is insufficient.
3. Re-read pool, user quota, and node distribution using the correct instance-quota ID.
4. Do not use `update_service` as a retry. It may create a new version or a `-fork` service.
5. Do not delete a queueing service directly. Deletion requires Offline state and explicit authority.
6. If recreation is approved, snapshot, offline, verify no Pods remain, delete, re-check capacity,
   then create once. Stop if a same-name or forked service already exists.

## Acceptance

Require all of the following before declaring success:

- expected Router and Engine Pod counts are Ready with zero restart loops;
- actual images, commands, environment, pools, and volume mounts match the payload;
- Router discovers the expected workers;
- Engine logs prove the intended loader and no forbidden fallback;
- no unexpected compilation for an image whose compile cache is expected to hit;
- OTel export is healthy for Engine and Router;
- `/health`, `/v1/models`, and deterministic and sampling requests succeed;
- raw snapshots and logs are saved without secrets.
