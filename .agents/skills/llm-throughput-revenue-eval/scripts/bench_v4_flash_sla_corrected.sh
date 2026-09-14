#!/usr/bin/env bash
# Native SGLang metrics/Poisson arrivals with audited input/cache targets.
# Default is offline validation; --execute is required to access the local worker.
set -euo pipefail

readonly SLA_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SGL_CORRECTED_RUNTIME="${SGL_SLA_CLIENT_RUNTIME:-/volume/dev/alan/deployments/five-model-cost-20260913/runtimes/latest/runtime}"

if [[ ! -x "$SGL_CORRECTED_RUNTIME/opt/sglang/bin/python" || ! -r "$SLA_SCRIPT_DIR/standard_sla.py" ]]; then
    printf 'Missing local runtime or adjacent standard_sla.py; see references/code-review-20260914.md.\n' >&2
    exit 1
fi

exec env PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
    PYTHONPATH="$SGL_CORRECTED_RUNTIME/sgl-workspace/sglang/python" \
    LD_LIBRARY_PATH=/usr/local/cuda/compat:/usr/local/cuda/lib64:/usr/local/nvidia/lib64 \
    HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
    SGLANG_RUST_BUILD_MODE=never SGLANG_IS_IN_CI=0 \
    "$SGL_CORRECTED_RUNTIME/opt/sglang/bin/python" -u \
    "$SLA_SCRIPT_DIR/standard_sla.py" --runtime "$SGL_CORRECTED_RUNTIME" "$@"
