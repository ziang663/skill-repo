"""Guarded task-local GLM deployment; never calls an online/platform endpoint."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PREVIOUS = ROOT.parent / "dsv41-h200-opt-20260911"
RUNTIME = PREVIOUS / "runtime"
SOURCE = RUNTIME / "sgl-workspace/sglang"
PYTHON = RUNTIME / "opt/sglang/bin/python"
MODEL = Path("/models/preset/zai-org/GLM-5.2-FP8/v1.0")
sys.path.insert(0, str(PREVIOUS))
from local_engine import save, process_start


def environment():
    env = {k: v for k, v in os.environ.items() if k in ("HOME", "USER", "LOGNAME")}
    env.update(PATH=f"{RUNTIME}/opt/sglang/bin:/usr/local/cuda/bin:/usr/bin:/bin",
               TZ="UTC", LANG="C.UTF-8", LC_ALL="C.UTF-8", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
               CUDA_VISIBLE_DEVICES="0,1,2,3,4,5,6,7", CUDA_HOME="/usr/local/cuda",
               LD_LIBRARY_PATH="/usr/local/cuda/compat:/usr/local/cuda/lib64:/usr/local/nvidia/lib64",
               CPATH="/usr/local/cuda/include/cccl", CPLUS_INCLUDE_PATH="/usr/local/cuda/include/cccl",
               SGLANG_CACHE_DIR=str(ROOT / "kernel-cache"), SGLANG_RUST_BUILD_MODE="never",
               HF_HUB_DISABLE_IMPLICIT_TOKEN="1", HF_HUB_DISABLE_PROGRESS_BARS="1", HF_HUB_OFFLINE="1",
               TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="8")
    return env


def command(kv_cache_dtype="fp8_e4m3", mem_fraction_static=0.8,
            tp=8, pp=1, with_eagle=True):
    assert 0 < mem_fraction_static < 1
    assert tp > 0 and pp > 0 and tp * pp == 8, "This task only owns the local eight GPUs"
    assert not (pp > 1 and with_eagle), "Current SGLang forbids PP with speculative decoding"
    argv = [str(PYTHON), "-u", "-c", "from sglang.cli.main import main; main()", "serve",
            "--model-path", str(MODEL), "--tp", str(tp)]
    if pp != 1:
        argv += ["--pp-size", str(pp)]
    if with_eagle:
        argv += ["--speculative-algorithm", "EAGLE",
                 "--speculative-num-steps", "5", "--speculative-eagle-topk", "1",
                 "--speculative-num-draft-tokens", "6"]
    argv += ["--mem-fraction-static", str(mem_fraction_static),
             "--host", "0.0.0.0", "--port", "30000", "--kv-cache-dtype", kv_cache_dtype]
    return argv


def preflight():
    cfg = json.loads((MODEL / "config.json").read_text())
    index = json.loads((MODEL / "model.safetensors.index.json").read_text())
    shards = sorted(set(index["weight_map"].values()))
    assert all((MODEL / p).is_file() for p in shards)
    assert cfg["max_position_embeddings"] == 1048576
    assert cfg["architectures"] == ["GlmMoeDsaForCausalLM"]
    with socket.socket() as s:
        s.bind(("0.0.0.0", 30000))
    row = {"time": datetime.now(timezone.utc).isoformat(), "model_path": str(MODEL),
           "config_sha256": hashlib.sha256((MODEL / "config.json").read_bytes()).hexdigest(),
           "config": {k: v for k, v in cfg.items() if k != "quantization_config"},
           "quantization": {k: v for k, v in cfg["quantization_config"].items() if k != "modules_to_not_convert"},
           "shards": len(shards), "shard_bytes": sum((MODEL / p).stat().st_size for p in shards),
           "mtp_tensor_count": sum(k.startswith("model.layers.78.") for k in index["weight_map"]),
           "runtime_provenance": str(PREVIOUS / "runtime-check.json"), "argv": command(),
           "scope": "Local 8 H200; replacing only our idle DSV41 process. No online changes."}
    save(ROOT / "preflight.json", row)
    print(json.dumps({"model_path": str(MODEL), "shards": len(shards), "max_context": cfg["max_position_embeddings"]}))


def start(args):
    assert args.name.replace("-", "").replace("_", "").isalnum()
    run = ROOT / "runs" / args.name
    assert not run.exists(), "Never overwrite a previous run"
    with socket.socket() as s:
        s.bind(("0.0.0.0", 30000))
    gpu = subprocess.check_output(["nvidia-smi", "--query-gpu=index,name,memory.used,utilization.gpu", "--format=csv,noheader,nounits"], text=True)
    rows = [r.split(",") for r in gpu.splitlines()]
    assert len(rows) == 8 and all("H200" in r[1] and int(r[2]) < 512 and int(r[3]) == 0 for r in rows), gpu
    processes = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"], text=True)
    assert not processes.strip(), processes
    env = environment()
    env["GLM52_LOCAL_RUN_DIR"] = str(run)
    argv = command(args.kv_cache_dtype, args.mem_fraction_static,
                   args.tp, args.pp, not args.without_eagle)
    save(run / "launch.json", {"time": datetime.now(timezone.utc).isoformat(), "argv": argv,
         "env": {k: v for k, v in env.items() if k not in ("HOME", "USER", "LOGNAME")}, "gpu_before": gpu,
         "source_commit": "0162bc47049fdbad8483f20a93bfeb565640f012", "note": "Reusing extracted dependencies. Existing DSV4-only indexer patch is not on the GLM execution path."})
    with (run / "engine.log").open("w") as log:
        process = subprocess.Popen(argv, env=env, cwd=SOURCE, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    record = {"name": "glm52-" + args.name, "pid": process.pid, "start_ticks": process_start(process.pid), "run": str(run), "port": 30000}
    save(run / "process.json", record)
    save(ROOT / "active-engine.json", record)
    print(json.dumps(record), flush=True)


def stop(args):
    record = json.loads((ROOT / "active-engine.json").read_text())
    assert record["name"] == "glm52-" + args.name
    pid = record["pid"]
    ticks = process_start(pid)
    if ticks is None:
        print("Recorded process has already exited")
        return
    assert ticks == record["start_ticks"], "PID reused"
    assert os.getpgid(pid) == pid
    assert ("GLM52_LOCAL_RUN_DIR=" + record["run"]).encode() in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    os.killpg(pid, signal.SIGTERM)
    save(Path(record["run"]) / "stop.json", {"time": datetime.now(timezone.utc).isoformat(), "signal": "SIGTERM", "pid": pid,
                                               "reason": args.reason})
    print(f"SIGTERM sent only to GLM task process group {pid}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["preflight", "start", "stop"])
    parser.add_argument("--name", default="cookbook-kvfp8")
    parser.add_argument("--kv-cache-dtype", choices=["fp8_e4m3", "bfloat16"], default="fp8_e4m3")
    parser.add_argument("--mem-fraction-static", type=float, default=0.8)
    parser.add_argument("--tp", type=int, default=8)
    parser.add_argument("--pp", type=int, default=1)
    parser.add_argument("--without-eagle", action="store_true")
    parser.add_argument("--reason", default="User requested stopping this local GLM instance")
    args = parser.parse_args()
    if args.action == "preflight":
        preflight()
    else:
        (start if args.action == "start" else stop)(args)
