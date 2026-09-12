# SDK build workflow and pitfalls

Read this before preparing a recipe or submitting a build. Commands and template
paths below belong to the separately obtained **image-factory tooling repository**.
Check its current CLI and `docs/PITFALLS.md` when a version differs.

## Dockerfile submission is not a local Docker build

The SDK image-build configuration uses `build_method="baseDockerfile"`,
`dockerfile_content`, and `dockerfile_arg` entries with `key`, `value`, and `hidden`.
The driver constructs that configuration and passes it to `client.images.create()`.

| Local Docker feature | SDK/driver handling |
|---|---|
| Local build context | Not submitted; package pinned source in a source image and use `COPY --from` |
| Named build context | Package it separately or remove it only if proven unused |
| `--target` | For transformed stages, append `FROM <target> AS factory_final` |
| Build arguments | Submit through `dockerfile_arg`; never inline credential values |
| Repository Dockerfile | Resolve its commit, read it, and transform in memory |

Do not infer builder CPU/RAM or GPU allocation from `resource_pool` / `instances`.
Those fields do not act as build-parallelism controls. If evidence identifies a
compiler OOM, adjust Dockerfile concurrency such as `MAX_JOBS` or
`CARGO_BUILD_JOBS`; do not change serving quota to address a builder failure.

## Recipe preflight

- Limit every platform image version to 64 characters. Preserve full commits in
  provenance, not an overlong tag.
- Preserve global `ARG` declarations before every `FROM`. An injected context
  stage belongs immediately before the original first `FROM`, after global ARGs.
- Require replacement anchors to match exactly once. A no-op patch can produce a
  successful but incorrect image.
- Inspect every resolved `@<stage>` URL against the current recipe's declared
  version, not merely its stage name. Stage names collide across recipes.
- The resolver interprets `@<stage>` throughout recipe fields, including prose.
  Avoid stage-reference syntax in descriptions unless it is intended to resolve.
- Confirm the final stage and all requested components. Do not silently replace
  an engine-only target with a unified image or add FlashBoot to a non-FlashBoot
  chain.
- Check credential handling in source acquisition, generated text, args, build
  logs, git configuration, and resulting image layers. `!tokenised:<host/path>`
  is a driver convention, not a security guarantee.

### Local templates and source overlays

The driver's `kind: local` reads a Dockerfile verbatim with optional `append`.
It rejects `ctx_image`, `replacements`, `insert_after`, `post_replacements`, and
`target`; it does not inject a final target automatically. Express stages directly:

```dockerfile
ARG BASE
ARG SRC_IMAGE
FROM ${SRC_IMAGE} AS newsrc
FROM ${BASE}
COPY --from=newsrc /src/python/sglang/ /opt/sglang-source/python/sglang/
```

This illustrates stage wiring only. The real destination must be the base image's
actual imported source path; the recipe may resolve `SRC_IMAGE: "@src-sglang"`.

For an editable SGLang source overlay:

- remove stale bytecode only under the explicitly overlaid package and compile
  the changed Python files;
- update generated version metadata and installed distribution metadata to agree
  with the pinned commit; swapping source alone can leave the base version;
- resolve real imported module paths and compare their SHA256 values with the
  intended source. `importlib.util.find_spec()` helps locate editable installs,
  but may import parent packages; account for their dependencies;
- assert dependency/native compatibility. A source-only layer is unsuitable when
  the change also requires rebuilt native extensions or new packages.

Do not weaken a borrowed Dockerfile's assertions merely to make another base
pass. For example, check the intended CUDA compiler and CCCL headers when pip and
system CUDA toolchains coexist. Repair the actual invariant, or remove a check
only when the associated feature is intentionally absent.

## Tracking the correct build

`images.create()` returns an image record, not just an ID. Retain `id`,
`image_build_job_name`, and `image_url` immediately. Record the submitted recipe,
resolved commits, and exact Dockerfile with secrets redacted.

The list API uses `images.list(page=..., pageSize=..., keyword=...)`; rows are in
`rows`. The client needs both `region` and `cluster`. Duplicate name/version rows
and unstable ordering are possible: follow the returned numeric ID, not the first
matching tag. For an ordinary lookup, the current driver chooses the largest ID.

Use `build ... --resume-id <id>` after an interruption, with the saved recipe and
inputs. Do not silently rerun a floating branch to reconstruct the old build. If
provenance must be reconstructed manually, label it and identify each field's source.

Image-version collisions may return `409 cannot register duplicate image`.
Prefer a new version; `--force` only bypasses the driver's local guard. Deleting
an existing record requires separately authorized, exact-target handling.

## Build logs and completion

The SDK raw GET endpoint for logs is:

```python
text = client.get(
    f"/aiapi/v1/image-sync-server/images-build/log/{image_id}",
    cast_to=str,
)
```

Handle the returned JSON envelope/escaped newlines before reading BuildKit steps.
The log endpoint has historically returned a fixed-size tail, not full history;
save successive redacted snapshots when full diagnostic evidence is needed.
Never echo raw credential-bearing log lines into reports.

Make build-time checks hard assertions in stages the final image actually depends
on. A marker `echo` may disappear from the tail, and checks in an unused stage may
never execute. Preserve machine-readable test results when applicable.

BuildKit's last `DONE` is not platform completion. Export, load, push, and image
registration can continue with `image_build_status=Running`. Follow the exact ID
until terminal status and inspect the registry result; an intermediate digest or
`message="job created"` is not sufficient.

Incremental builds can still export the entire uncompressed image through
docker-save/load before pushing. A tiny source diff does not imply a short build.
Estimate from base pull, real work, and export/registration costs. Do not select a
different cluster or publish another copy merely to chase a historical timing.

## Result and provenance

Select the destination's URL from `cluster_images_url_v2`; do not synthesize a
tenant namespace from an unrelated manual push example. Inspect the registry to
record the actual digest.

The driver writes `builds/<name>__<tag>.json` and the generated `.Dockerfile`.
Preserve source commits, base digest, patch/bundle hashes, redacted args,
transformations, returned ID, timings, destination URL/digest, and validation
evidence. Keep run-specific artifacts outside this reusable skill.
