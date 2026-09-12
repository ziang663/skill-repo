# FlashBoot compile-cache contract

Read this for a new SGLang/FlashBoot image, cache reuse decisions, or unexpected
cold-start compilation. Use the image-factory tooling checkout's `docs/PROCESS.md`,
`tools/flashboot_cache_guard.py`, and `templates/Dockerfile.flashboot-cache-final`.
Those tools are external dependencies, not files bundled with this skill.

## Freeze the runtime before capture

The cache-producing and cache-consuming environments must match:

```text
final SGLang + FlashBoot code, dependencies, and compiler configuration
  -> runtime-base image, FB_CACHE=none, digest frozen
  -> target-GPU cache/weight generation and functional checks
  -> artifact-only final image restores the cache
```

An older image with manually aligned package versions is not equivalent. Absolute
Python paths, headers, compiler flags, source bytes, and cache layout can differ.
The runtime-base must already contain the final source overlay/install, FlashBoot
extension, Torch/CUDA/kernel packages, system dependencies, compiler selection,
cache roots, and kernel-relevant configuration.

The final child must inherit that exact runtime-base. It may restore artifacts and
add launch/provenance files, but must not reinstall packages, overlay SGLang,
compile extensions, or apply runtime patches. Any such change requires a new
runtime-base and recapture. A genuinely router-only change need not invalidate an
engine cache, but verify that it does not change the engine environment.

Recipes declare `flashboot_contract.phase` as `runtime-base` or `final`.
The driver requires `FB_CACHE=none` for runtime-base and an artifact-only final
that inherits its declared runtime stage. Use the local final template instead of
running a complete upstream `Dockerfile.flashboot` again. The
`--allow-legacy-flashboot` escape hatch is for explicitly requested historical
reproduction, not new releases.

## Preserve timestamps and command identity

Ninja checks dependency mtimes and command identity, not just output bytes.
Common rebuild causes include:

- `cp -r` changing output mtimes relative to `.ninja_log`;
- restored headers/generated inputs being newer than archived `.o` or `.so`;
- different interpreter layouts changing absolute include paths;
- regenerated `build.ninja` changing link commands.

Restore caches with archive semantics such as `cp -a`. Pin only immutable Ninja
inputs after restore: FlashInfer data, TVM-FFI includes, and generated FlashInfer
source inputs. Resolve package paths from the actual interpreter, not a hardcoded
system `dist-packages` path in a virtual-environment image.

Never change timestamps on `cached_ops`, `.o`, `.so`, `.ninja_log`, or
`.ninja_deps` to force a cache hit. Use the existing guard's scoped operations
instead of broad recursive timestamp changes.

## Capture and verify

In the frozen runtime-base, after warming all required kernel paths:

```bash
python3 tools/flashboot_cache_guard.py capture \
  --runtime-base <registry-path>@sha256:<digest> \
  --cache-profile <profile> \
  --output compile-cache-contract.json
```

In the artifact-only final image after restoring the archive:

```bash
python3 tools/flashboot_cache_guard.py verify \
  --manifest compile-cache-contract.json \
  --runtime-base <registry-path>@sha256:<digest> \
  --cache-profile <profile>
python3 tools/flashboot_cache_guard.py pin
python3 tools/flashboot_cache_guard.py audit
```

The guard must be present at the shown path in the execution environment. The
contract fingerprints module versions and locations, compiler identity, and
compile inputs. Store the cache archive SHA256 next to the contract. Preserve the
exact runtime-base digest and artifact source commit in build provenance.

## Diagnose and accept on a fresh Pod

With authorization for runtime testing, snapshot `.o/.so` sizes, mtimes, and `.so`
SHA256 before launch and after Ready. Observe compiler processes rather than
relying only on log wording. Inspect `build.ninja` commands and embedded include
paths against the running interpreter when a rebuild occurs. New-file count is
not sufficient: Ninja often overwrites existing files.

Require the intended image/digest, contract verification, intended target/draft
FlashBoot loaders with fallback disabled, no CUDA compilation processes such as
`nvcc`, `cicc`, or `ptxas`, no `.o` mutations, healthy endpoints, and successful
deterministic plus sampling requests.

Ninja may still run to inspect its graph. A brief `.so` relink without `.o`
changes is not a full CUDA rebuild, but is not byte-for-byte reuse either; report
it separately. Time CUDA Graph capture, DeepGEMM warmup, weight I/O, and expert
layout conversion separately from compilation.
