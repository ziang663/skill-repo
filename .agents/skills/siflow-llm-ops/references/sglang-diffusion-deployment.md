# SGLang diffusion and video deployment on SiFlow

Read this reference for SGLang diffusion pipelines such as MiniMax-H3. Do not apply its API schema
or command flags to ordinary SGLang LLM serving.

## Why the workload needs a separate preflight

An image containing `sglang serve` is not necessarily capable of serving diffusion models. SGLang
LLM and diffusion images can expose different parsers under the same command name. Prove the exact
image digest accepts the intended model variant and flags before treating GPU placement or model
download as the next problem.

Preferred evidence, in order:

1. A healthy service using the same image digest and command family.
2. `sglang serve --help` or a non-GPU parser smoke inside the exact image.
3. Image source/commit metadata that unambiguously contains the diffusion CLI.
4. A deliberately authorized smallest-topology compatibility deployment whose first container
   logs are the stopping gate.

If logs print CLI `usage:` followed by `unrecognized arguments`, stop. No weight download or warmup
will occur until the image/command mismatch is corrected. Snapshot the failure and obtain approval
before updating or replacing the service.

## Model source and persistent cache

SiFlow requires a non-empty HF token field even for public repositories. Use the literal
`anonymous` public-source marker and keep real tokens out of payloads and evidence.

Use a persistent volume for large diffusion checkpoints and set cache locations explicitly:

```text
HF_HOME=/volume/dev/hf-cache/minimax-h3
HF_HUB_CACHE=/volume/dev/hf-cache/minimax-h3/hub
```

Continue passing the Hugging Face repository ID as `--model-path`; the cache environment controls
where blobs and snapshots are stored. Verify the actual Worker Pod contains both the mount and the
resolved environment values.

At the MiniMax-H3 FL2VA revision used in the cetus deployment, the cache contained 81 files and
occupied about 135 GB. Treat this as an observation, not a stable model invariant: inspect the
current revision and leave meaningful free-space headroom before deployment.

Keep startup phases distinct:

- `ContainerCreating` before image pull/start is infrastructure setup.
- A parser restart loop is command incompatibility, not slow model download.
- Weight download starts only after application logs show Hub/checkpoint activity.
- A growing persistent cache with no restart is evidence of progress.
- Readiness is not complete until component loading and warmup finish.

## Known-good MiniMax-H3 pattern

The following Worker combination passed FL2VA T2VA on two H200 GPUs. Pinning the digest makes the
evidence reproducible, but revalidate it before adopting it as a production standard:

```text
image: lmsysorg/sglang:v0.5.19-cu130@sha256:d6e7288627be8b02be88e4bba38e73f6d50e2826869f753c13a4c4385ab3eda9
```

```bash
sglang serve \
  --model-path MiniMaxAI/MiniMax-H3 \
  --served-model-name MiniMaxAI/MiniMax-H3 \
  --model-variant fl2va \
  --num-gpus 2 \
  --ulysses-degree 2 \
  --encoder-parallel auto \
  --performance-mode speed \
  --enable-torch-compile false \
  --host 0.0.0.0 \
  --port 30000
```

The initially selected `deepseekv4-flash-0811-metricsfix-v8` image exposed the SGLang LLM CLI but
not the required MiniMax-H3 diffusion options. Replacing it with the pinned diffusion-capable image
resolved the parser failure.

The diffusion CLI above does not accept `--enable-metrics`. Remove the flag instead of waiting
through a restart loop. In this configuration `/metrics` returns HTTP 404. This is compatible with
functional inference acceptance only when metrics were not a stated requirement; otherwise select
or build an image with the required instrumentation before declaring the deployment complete.

Use a CPU Router when that matches the requested topology. `power_of_two` successfully forwarded
the asynchronous video endpoints in the observed deployment. Verify the actual Router Pod image,
generated command, service-discovery selector, policy, and Ready state because SiFlow may normalize
the submitted Router configuration. Router 503/readiness failures are expected while no Worker is
healthy; diagnose the Worker first.

## Startup and functional acceptance

For MiniMax-H3, verify:

- the expected Worker and Router replicas are Running and Ready without a restart loop;
- the Worker uses the diffusion-capable image and intended command;
- the persistent cache and volume mount are present;
- all pipeline components load and warmup completes;
- `/health` returns HTTP 200;
- `/v1/models` reports `MiniMaxH3Pipeline`, the intended GPU count, and expected DiT/VAE precision;
- an authorized video Job reaches `completed`, its content endpoint downloads successfully, and
  bounded server logs contain the same Job ID.

The cetus trial loaded six components and warmed up in about 61 seconds after the checkpoint was
available. These timings are evidence from one revision and cache state, not universal timeouts.

## Minimal asynchronous video smoke

The SGLang diffusion API is asynchronous:

1. `POST /v1/videos`
2. Poll `GET /v1/videos/{job_id}` until `completed` or `failed`
3. Download `GET /v1/videos/{job_id}/content`

Use `scripts/smoke_video.py` after the user has authorized an inference request. Its default payload
is a minimal 4-second, 768P, two-step T2VA functional smoke. Two steps establish wiring and runtime
health; they are not a production-quality or throughput benchmark.

```bash
python scripts/smoke_video.py \
  --base-url https://example/siflow/cluster/tenant/user/service \
  --model MiniMaxAI/MiniMax-H3 \
  --out-dir evidence/video-smoke \
  --require-audio
```

Use the isolated SiFlow SDK environment's `httpx`; do not assume `requests` is installed. Follow
HTTP redirects because the external gateway can redirect service paths. Create the local evidence
directory before opening a shell `tee` target.

The request schema above is SGLang's `/v1/videos` schema, not MiniMax's hosted
`/v2/video_generation` API. If a newer image rejects it, inspect that service's `/openapi.json` and
adapt the smoke payload without changing unrelated deployment settings.

Validate the downloaded artifact with `ffprobe` and, when available, a full FFmpeg decode. For an
audio-video task such as T2VA, require both a decodable video stream and an audio stream. Preserve
the request, create response, final Job response, media metadata, elapsed time, and content hash.

## Failure map

| Symptom | Likely cause | Action |
| --- | --- | --- |
| LLM-style `usage:` and unknown `--model-variant`/parallel flags | Exact image lacks the diffusion CLI | Stop, snapshot logs, and change the image only with authorization |
| Unknown `--enable-metrics` | Diffusion parser lacks that flag | Remove it; record `/metrics` as unavailable unless instrumentation is required |
| No download logs plus repeated restarts | Parser or early startup failure | Diagnose the first exception; do not describe it as weight download |
| Public HF model rejected for empty token | SiFlow requires a non-empty source marker | Use `anonymous`, never a real token in the payload |
| Checkpoint downloads again after restart | Cache is ephemeral or cache variables/mount are wrong | Mount persistent storage and verify `HF_HOME`/`HF_HUB_CACHE` in the actual Pod |
| Router is unready/503 while Worker starts | No healthy backend is registered yet | Follow Worker readiness and Router discovery logs |
| `/metrics` returns 404 but `/health` and generation work | Selected diffusion CLI has no metrics endpoint | Treat as a documented limitation unless metrics are required |
| Smoke client cannot import `requests` | SDK venv does not include it | Use installed `httpx.Client(follow_redirects=True)` |
| Local `tee` fails before the Job runs | Evidence directory did not exist when the shell opened it | Create the directory before starting the pipeline |

## Evidence and reporting

Save, with mode `0600` where appropriate:

- pre- and post-mutation service/instance snapshots;
- actual Pod JSON, Kubernetes events, and startup logs;
- bounded logs covering the smoke Job, plus a Job-ID keyword query;
- health and model-discovery responses;
- smoke payload, create response, final Job response, media file, `ffprobe` output, and SHA-256;
- a concise report separating functional success from unavailable metrics or untested quality.

An `ERROR` keyword query returning zero is supportive but not sufficient. Correlate Job status,
HTTP responses, Job-ID logs, Pod restarts, and media decode results. Expected `/metrics` 404 lines
may not contain the word `ERROR`.
