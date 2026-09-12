---
name: siflow-image-factory
description: Build, rebuild, and validate SiFlow container images through the SiFlow SDK without a local Docker daemon. Use for SGLang engine, unified engine/router, source-overlay, or FlashBoot images; build provenance; build-log diagnosis; and cross-cluster image publication and validation. Not for ordinary operation of an unchanged service or standalone FlashBoot checkpoint export.
---

# SiFlow Image Factory

Use the existing image-factory driver to submit Dockerfile text to the platform,
track the exact build, and prove what landed in the image. Image construction runs
on platform builders; preparing source, checking recipes, and inspecting artifacts
still use the local workspace. GPU validation is a separate, scoped operation.

## Prerequisites

- An authorized checkout of the internal tooling repository:
  `https://gitlab.scitix-inner.ai/liyuhang/image-factory`. This skill does not bundle
  that repository's driver, recipes, or templates. Locate the existing checkout or
  obtain it through the user's approved Git authentication; do not invent a local
  path or publish the private source as part of a build.
- A working SiFlow SDK environment. SiFlow is not on public PyPI. If missing,
  install the official wheel in an isolated virtual environment, using a verified
  version consistently in both download and install commands. The official URL is
  `https://oss-cn-shanghai.siflow.cn/ai-infra-download/siflow-public/siflow-<VERSION>-py3-none-any.whl`.
  Verify `from siflow import SiFlow`, the installed version, and `pip check` before
  loading credentials. The sibling `siflow-llm-ops` skill, when available, has a
  fuller SDK installation guide.
- Credentials supplied through `SIFLOW_ACCESS_KEY_ID` and
  `SIFLOW_ACCESS_KEY_SECRET`, or a driver-compatible `SIFLOW_CREDS_FILE`.
  Private source resolution uses `GITLAB_TOKEN`; prefer repository-scoped,
  read-only access. Do not print credential files or values.
- Explicit image name/tag, destination region/cluster/tenant, source revisions,
  and whether the result is engine-only, unified with a router, or FlashBoot.
  Read the tooling checkout's `docs/PITFALLS.md` for current driver-specific details.

## Workflow

1. Establish immutable inputs: resolve source refs to commits, record base-image
   digests, fingerprint patches/local source bundles, and identify the exact router
   when one is included. Do not confuse an external `llm-router` / `vllm-router`
   binary with SGLang's bundled model gateway.
2. Choose the smallest existing recipe/chain that meets the request. Read
   [references/sdk-build-workflow.md](references/sdk-build-workflow.md) before
   editing recipes or submitting a build. Keep upstream Dockerfiles pinned; use the
   driver's transformations or an explicit local overlay template as appropriate.
3. If the user requires reproduction and regression before packaging, complete
   that gate on an authorized local/test service first. Record baseline failures,
   expected controlled errors, successful requests, and process/restart evidence.
   Do not start the build while the required gate remains incomplete.
4. Run `--dry-run` for every changed stage. Inspect the generated Dockerfile,
   resolved stage URLs, secret handling, final target, and hard assertions. A
   dry-run is not a platform build or a runtime test.
5. Submit the authorized build and retain the numeric image ID immediately. Poll
   that ID to terminal state; resume it after interruption instead of submitting
   a duplicate. Diagnose a failed build before changing its recipe or retrying.
6. Perform no-GPU content/provenance checks, then the authorized runtime checks in
   [references/image-validation.md](references/image-validation.md). Report each
   validation level separately; build success is not model-serving acceptance.
7. Return the platform-provided image URL and registry digest, source/router
   identities, evidence location, test results, and any remaining validation gap.
   State explicitly whether any service was actually updated.

Run the following from the **image-factory tooling checkout**, using its SDK-capable
Python interpreter. Angle-bracket values are task inputs, not literal arguments:

```bash
python3 tools/factory.py build --recipe recipes/<chain>.json --stage <stage> --dry-run
python3 tools/factory.py build --recipe recipes/<chain>.json --stage <stage>
python3 tools/factory.py status --name <image-name> --version <tag> --region <region> --cluster <cluster>
python3 tools/factory.py build --recipe recipes/<chain>.json --stage <stage> --resume-id <image-id>
```

## Scope and safety

- Building an image does not authorize updating a live service, altering Engine
  Configs or resource-pool ACLs, replacing a registry tag, or deleting an image.
  Obtain direction when one of those is required but not already authorized.
- Prefer a new tag. The platform can reject duplicate versions; the driver's
  `--force` does not make deleting or replacing the existing image safe.
- Keep secrets out of Dockerfile text, recipes, remotes, manifests, reports, and
  this skill. A hidden build argument can still leak when a build command expands
  it into logs or image history. Use supported secret-safe source acquisition;
  do not treat `hidden=true` as proof of confidentiality.
- Preserve unrelated source changes and image components. For a worker-only fix,
  prove router/helper/native bytes stayed unchanged when that is the requirement.
- Registry credentials and internal source access are prerequisites, not supplied
  by installing this skill. Stop at a genuine access boundary; do not probe admin
  APIs or change permissions to work around it.

## Conditional workflows

- For FlashBoot compilation caches, read
  [references/flashboot-compile-cache.md](references/flashboot-compile-cache.md)
  and the tooling repository's `docs/PROCESS.md`. Freeze the complete runtime
  before capture; the cache-restoring final image must be artifact-only.
- For cross-cluster builds, patched NCCL, or P/D + MTP + HiCache acceptance, read
  [references/sglang-engine-cross-cluster-validation.md](references/sglang-engine-cross-cluster-validation.md).
  Do not infer permission for multi-node workloads from a build-only request.
