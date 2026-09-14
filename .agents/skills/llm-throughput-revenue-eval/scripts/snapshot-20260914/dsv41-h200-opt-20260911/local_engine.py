"""Guarded local-only engine lifecycle. Never talks to a platform API."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
PYTHON = RUNTIME / "opt/sglang/bin/python"
SOURCE = RUNTIME / "sgl-workspace/sglang"
MODEL = "/volume/dev/models/DeepSeek-V4.1-Flash-fb2764a5cf32"
PORT = 30141


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def environment(host_table=True):
    env = {k: v for k, v in os.environ.items() if k in ("HOME", "USER", "LOGNAME", "TZ")}
    env.update(
        PATH=f"{RUNTIME}/opt/sglang/bin:/usr/local/cuda/bin:/usr/bin:/bin",
        LANG="C.UTF-8", LC_ALL="C.UTF-8", PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
        CUDA_VISIBLE_DEVICES="0,1,2,3,4,5,6,7", CUDA_HOME="/usr/local/cuda",
        LD_LIBRARY_PATH="/usr/local/cuda/compat:/usr/local/cuda/lib64:/usr/local/nvidia/lib64",
        CPATH="/usr/local/cuda/include/cccl", CPLUS_INCLUDE_PATH="/usr/local/cuda/include/cccl",
        SGLANG_CACHE_DIR=str(ROOT / "kernel-cache"), SGLANG_RUST_BUILD_MODE="never",
        SGLANG_IS_IN_CI="0", SGLANG_DSV4_FP4_EXPERTS="1",
        SGLANG_ENABLE_DSV41_ENGRAM_HOST_TABLE="1" if host_table else "0",
        SGLANG_ENABLE_DSV41_ENGRAM_DROP_PAGE_CACHE="0",
        HF_HUB_DISABLE_IMPLICIT_TOKEN="1", HF_HUB_DISABLE_PROGRESS_BARS="1",
        TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="8",
    )
    return env


def process_start(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return None


def cli(args):
    argv = [str(PYTHON), "-u", "-c", "from sglang.cli.main import main; main()", "serve",
            "--trust-remote-code", "--model-path", MODEL, "--tokenizer-path", MODEL,
            "--served-model-name", "deepseek-ai/DeepSeek-V4.1-Flash",
            "--tp", "8", "--ep-size", "8", "--attention-backend", "dsv4",
            "--moe-runner-backend", "flashinfer_mxfp4", "--enable-decoder-swa-bounded-replay",
            "--reasoning-parser", "deepseek-v41", "--tool-call-parser", "deepseekv41",
            "--host", "127.0.0.1", "--port", str(PORT), "--nccl-port", "30341",
            "--enable-cache-report", "--enable-metrics", "--load-snapshot-publish-interval", "15",
            "--kv-events-config", '{"publisher":"zmq","endpoint":"tcp://127.0.0.1:30142"}',
            "--enable-hierarchical-cache", "--hicache-ratio", "3", "--hicache-io-backend", "direct",
            "--hicache-write-policy", "write_through", "--hicache-mem-layout", "page_first_direct",
            "--cuda-graph-max-bs-decode", "32", "--mem-fraction-static", "0.78",
            "--max-total-tokens", "5000000", "--max-running-requests", "32", "--page-size", "256",
            "--random-seed", "42"]
    if args.chunk:
        argv += ["--chunked-prefill-size", str(args.chunk)]
    if args.dspark:
        argv += ["--speculative-algorithm", "DSPARK"]
        if args.block_size:
            argv += ["--speculative-dspark-block-size", str(args.block_size)]
    return argv


def start(args):
    assert (ROOT / "runtime-extracted.json").exists(), "Image extraction not finished"
    assert args.name.replace("-", "").replace("_", "").isalnum()
    run = ROOT / "runs" / args.name
    assert not run.exists(), "Use a fresh run name; never overwrite an attempted run"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", PORT))
    gpu = subprocess.check_output(["nvidia-smi", "--query-gpu=index,name,memory.used,utilization.gpu", "--format=csv,noheader,nounits"], text=True)
    rows = [row.split(",") for row in gpu.splitlines()]
    assert len(rows) == 8 and all("H200" in row[1] and int(row[2]) < 512 and int(row[3]) == 0 for row in rows), gpu
    argv, env = cli(args), environment(args.engram == "host")
    env["DSV41_LOCAL_RUN_DIR"] = str(run)
    run.mkdir(parents=True)
    save(run / "launch.json", {"time": datetime.now(timezone.utc).isoformat(), "argv": argv,
         "env": {k: v for k, v in env.items() if k not in ("HOME", "USER", "LOGNAME")},
         "gpu_before": gpu, "local_only": True,
         "source_override": json.loads((ROOT / "source-override.json").read_text()) if (ROOT / "source-override.json").exists() else None,
         "indexer_sha256": hashlib.sha256((SOURCE / "python/sglang/kernels/ops/attention/dsv4/sm90_fp4_indexer.py").read_bytes()).hexdigest()})
    with (run / "engine.log").open("w") as log:
        proc = subprocess.Popen(argv, env=env, cwd=SOURCE, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    record = {"name": args.name, "pid": proc.pid, "start_ticks": process_start(proc.pid), "run": str(run), "port": PORT}
    save(run / "process.json", record)
    save(ROOT / "active-engine.json", record)
    print(json.dumps(record), flush=True)


def stop(args):
    record = json.loads((ROOT / "active-engine.json").read_text())
    assert record["name"] == args.name, "Active engine name mismatch"
    pid = record["pid"]
    ticks = process_start(pid)
    if ticks is None:
        print("Recorded local engine already exited")
        return
    assert ticks == record["start_ticks"], "PID reused; refusing to signal"
    env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    assert ("DSV41_LOCAL_RUN_DIR=" + record["run"]).encode() in env
    assert os.getpgid(pid) == pid, "Unexpected process group"
    os.killpg(pid, signal.SIGTERM)
    save(Path(record["run"]) / "stop.json", {"signal": "SIGTERM", "time": datetime.now(timezone.utc).isoformat(), "pid": pid})
    print(f"SIGTERM sent only to local run {args.name}, process group {pid}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    launch = sub.add_parser("start")
    launch.add_argument("--name", required=True)
    launch.add_argument("--engram", choices=("host", "gpu"), default="host")
    launch.add_argument("--dspark", action="store_true")
    launch.add_argument("--block-size", type=int)
    launch.add_argument("--chunk", type=int)
    halt = sub.add_parser("stop")
    halt.add_argument("--name", required=True)
    args = parser.parse_args()
    (start if args.action == "start" else stop)(args)


if __name__ == "__main__":
    main()
