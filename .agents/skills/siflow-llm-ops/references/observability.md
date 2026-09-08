# Observability

## Contents

- Evidence directory
- SiFlow logs
- OmniObs logs
- OTel traces
- Cache-hit analysis
- Restart analysis

## Evidence directory

Keep raw and derived evidence separate:

```text
evidence/
  service.json
  instances.json
  syslogs.json
  raw/*.ndjson.gz
  traces/*.json
  summary.md
```

Record UTC windows and convert UI UTC+8 timestamps explicitly.

## SiFlow logs

Try `query_logs`, `download_logs`, and Pod container log methods first. On some overseas clusters, aggregate logs may return zero and Pod WebSocket access may fail because cluster context is missing. Treat this as an observability-path failure, not proof that the application emitted no logs.

## OmniObs logs

Endpoint:

```text
POST https://omniobs.scitix.ai/api/query/logs/query?project=default
Authorization: Bearer $OMNI_TOKEN
```

Body fields include `kind`, `start_time`, `end_time`, `query`, `limit`, `offset`, `sort_field`, and `sort_order`. Use `query`, not `q` or `filter`. The service caps pages at 5000 rows; bisect time windows when necessary.

Filter by exact cluster, namespace, and Pod. Pod names can be reused after rolling restart, so filter rows by each current Pod's `createTime` or container ID.

### Pisces access and complete log downloads

The same OmniObs hostname can resolve differently across clusters:

- Aries has resolved `omniobs.scitix.ai` to the reachable internal VIP `10.208.2.223`.
- Pisces has resolved it to a public IP whose TCP/443 path times out.

Before blaming the API or token, check both DNS and HTTPS:

```bash
getent ahostsv4 omniobs.scitix.ai
curl --connect-timeout 10 -I https://omniobs.scitix.ai/
```

On Pisces, use the known internal VIP for a temporary query without editing `/etc/hosts`:

```bash
python scripts/fetch_omni_logs.py \
  --resolve-ip 10.208.2.223 \
  --from-ms 1787647980000 --to-ms 1787648220000 \
  --pods pods.json \
  --filter 'cluster="pisces" AND namespace_name="t-simaas-user"' \
  --outdir evidence/raw
```

The script still connects with the `omniobs.scitix.ai` HTTPS hostname, so TLS SNI and certificate validation remain intact. Treat the VIP as a temporary workaround and re-check it if connectivity changes.

For incident correlation, download the complete bounded window for every relevant Engine and Router Pod rather than querying only the warning text. Then search by RID and inspect preceding request completion, disconnect, timeout, and abort lines. The API caps each page at 5000 rows; `fetch_omni_logs.py` recursively splits large windows and saves gzip-compressed NDJSON plus a row-count manifest.

## OTel traces

Trace endpoints use the same OmniObs bearer token:

- `/api/query/traces/search`
- `/api/query/traces/detail`
- `/api/query/traces/services`
- `/api/query/traces/operations`

Important attributes vary by image. Discover keys first when needed. Common evidence includes:

- input/prompt tokens and cached tokens;
- Router selected worker/prefill IP;
- Router cache-map matched blocks;
- `gen_ai.latency.time_in_queue`;
- `gen_ai.latency.time_in_model_prefill`;
- `gen_ai.latency.time_to_first_token`;
- L2/L3 hit lengths and load-back timing;
- request/session/turn correlation attributes.

## Cache-hit analysis

Use canonical scheduler lines such as `PP0 ... TP0` to avoid rank duplication. Exclude health checks, often `#new-token: 64, #cached-token: 0`.

Compute token-weighted hit:

```text
hit = sum(cached_tokens) / sum(cached_tokens + new_tokens)
```

Report by 5-minute window and worker/prefill group. Also record queue depth, pending tokens, token-pool usage, Mooncake read/write throughput, page-get failures, and local Host eviction.

Zero Mooncake write can be valid when pages already exist. Distinguish cases:

- Existing page + successful reads + high later hit: duplicate writes were skipped.
- New random prefix + no writes + second run misses: write path is broken.
- Heavy reads + low hit under queue pressure: investigate prefetch timeout/cancellation, partial-prefix availability, or Router migration.

## Restart analysis

For each Pod, capture restart count, previous exit code/reason, current start time, and the first application exception before shutdown.

Classification:

- `OOMKilled`: Kubernetes-confirmed cgroup OOM.
- exit `137` without `OOMKilled`: SIGKILL; OOM is possible but unconfirmed.
- Scheduler assertion followed by exit `0`: application fail-stop and cleanup.
- NCCL/CUDA allocation failure: GPU-memory or communication allocation failure.
- liveness termination: health failure; find the upstream blocked process or collective.
- graceful signal/cleanup only: not enough evidence; inspect earlier logs and traces.

Do not treat shutdown-time `CancelledError`, `SystemExit`, or async-generator errors as the first cause when a preceding Scheduler/CUDA/NCCL error exists.
