#!/usr/bin/env bash
# Local DeepSeek V4 Flash 0731, H200 x2, TP2 + DSPARK + FP8 KV.
# This is V4 Flash, not V4.1 Flash. Runs in the foreground; never kills services.
# Runtime commit: 0bcd822377da7b5718e674eaf9c870d349424dd1.
set -euo pipefail

readonly SGL_REPRO_RUNTIME=/volume/dev/alan/deployments/five-model-cost-20260913/runtimes/latest/runtime
readonly SGL_REPRO_SOURCE="$SGL_REPRO_RUNTIME/sgl-workspace/sglang"
readonly SGL_REPRO_PYTHON="$SGL_REPRO_RUNTIME/opt/sglang/bin/python"
readonly SGL_REPRO_MODEL=/volume/dev/models/DeepSeek-V4-Flash-0731
readonly SGL_REPRO_CACHE=/volume/dev/alan/deployments/five-model-cost-20260913/kernel-cache/latest

if (( $# > 1 )) || { (( $# == 1 )) && [[ "$1" != --dry-run ]]; }; then
    printf 'Usage: bash %s [--dry-run]\n' "$0" >&2
    exit 2
fi

if [[ ! -x "$SGL_REPRO_PYTHON" || ! -d "$SGL_REPRO_SOURCE/python/sglang" ]]; then
    printf 'Local SGLang runtime is missing: %s\n' "$SGL_REPRO_RUNTIME" >&2
    exit 1
fi
if [[ ! -r "$SGL_REPRO_MODEL/config.json" ]]; then
    printf 'Model config is missing: %s/config.json\n' "$SGL_REPRO_MODEL" >&2
    exit 1
fi

# Do not attach this manual launch to the already-finished benchmark lifecycle.
# Explicit settings below match the effective configuration of the recorded run.
readonly -a SGL_REPRO_COMMAND=(
    env -u FIVE_MODEL_COST_RUN
    "CUDA_VISIBLE_DEVICES=0,1"
    "OMP_NUM_THREADS=8"
    "SGLANG_DEFAULT_THINKING=false"
    "SGLANG_RUST_BUILD_MODE=never"
    "SGLANG_IS_IN_CI=0"
    "SGLANG_CACHE_DIR=$SGL_REPRO_CACHE"
    "HF_HUB_OFFLINE=1"
    "HF_HUB_DISABLE_IMPLICIT_TOKEN=1"
    "HF_HUB_DISABLE_PROGRESS_BARS=1"
    "TOKENIZERS_PARALLELISM=false"
    "PYTHONNOUSERSITE=1"
    "PYTHONDONTWRITEBYTECODE=1"
    "CUDA_HOME=/usr/local/cuda"
    "CPATH=/usr/local/cuda/include/cccl"
    "CPLUS_INCLUDE_PATH=/usr/local/cuda/include/cccl"
    "PATH=$SGL_REPRO_RUNTIME/opt/sglang/bin:/usr/local/cuda/bin:/usr/bin:/bin"
    "PYTHONPATH=$SGL_REPRO_SOURCE/python"
    "LD_LIBRARY_PATH=/usr/local/cuda/compat:/usr/local/cuda/lib64:/usr/local/nvidia/lib64"
    "LANG=C.UTF-8"
    "LC_ALL=C.UTF-8"
    "TZ=UTC"
    "$SGL_REPRO_PYTHON" -u
    -c 'from sglang.cli.main import main; main()' serve
    --model-path "$SGL_REPRO_MODEL"
    --served-model-name deepseek-v4-flash
    --trust-remote-code
    --tp 2
    --attention-backend dsv4
    --moe-runner-backend flashinfer_mxfp4
    --flashinfer-mxfp4-moe-precision fp8
    --speculative-algorithm DSPARK
    --speculative-num-steps 1
    --speculative-num-draft-tokens 6
    --mem-fraction-static 0.906
    --kv-cache-dtype fp8_e4m3
    --page-size 256
    --max-running-requests 256
    --chunked-prefill-size 8192
    --cuda-graph-max-bs-decode 256
    --enable-metrics
    --enable-cache-report
    --host 127.0.0.1
    --port 30480
    --nccl-port 30580
)

cd "$SGL_REPRO_SOURCE"
if [[ "${1:-}" == --dry-run ]]; then
    printf 'Working directory: %s\n' "$PWD"
    printf '%q ' "${SGL_REPRO_COMMAND[@]}"
    printf '\n'
    exit 0
fi

printf 'Starting V4 Flash 0731 on GPU 0,1 at http://127.0.0.1:30480 (foreground).\n'
exec "${SGL_REPRO_COMMAND[@]}"
