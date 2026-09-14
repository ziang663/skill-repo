"""Scoped local launch/stop utility. No platform calls and no untracked process kills."""
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
import urllib.request

ROOT = Path(__file__).resolve().parent
DEPLOYMENTS = ROOT.parent
sys.path.insert(0, str(DEPLOYMENTS / "glm52-h200-1m-20260911"))
from local_glm import environment, PYTHON, RUNTIME, process_start
from engine_lifecycle import wait_for_release

SOURCE = DEPLOYMENTS / "sglang-dsv41-acceptance-fix-20260912"
PORT = 30480
PROFILES = json.loads((ROOT / "profiles.json").read_text())


def utc():
    return datetime.now(timezone.utc).isoformat()


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def query(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=5) as resp:
        return json.load(resp)


def start(args):
    profile = PROFILES[args.model]
    run = ROOT / "runs" / args.name
    assert args.name.replace("-", "").replace("_", "").isalnum()
    assert not run.exists(), "Use a new run name"
    runtime = Path(args.runtime) if args.runtime else RUNTIME
    source = Path(args.source or (runtime / "sgl-workspace/sglang" if args.runtime else SOURCE))
    python = Path(args.python or runtime / "opt/sglang/bin/python")
    gpu = subprocess.check_output(["nvidia-smi", "--query-gpu=index,name,memory.used,utilization.gpu", "--format=csv,noheader,nounits"], text=True)
    rows = [r.split(",") for r in gpu.splitlines()]
    assert len(rows) == 8 and all("H200" in r[1] for r in rows)
    assert all(int(r[2]) < 512 for r in rows[:profile["gpus"]]), gpu
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", PORT))
    env = environment()
    tf = runtime / "sgl-workspace/transformers/src"
    env.update(PATH=f"{runtime}/opt/sglang/bin:/usr/local/cuda/bin:/usr/bin:/bin",
               PYTHONPATH=str(source / "python") + (":"+str(tf) if tf.exists() else ""),
               CUDA_VISIBLE_DEVICES=",".join(str(i) for i in range(profile["gpus"])),
               SGLANG_CACHE_DIR=str(ROOT / "kernel-cache" / runtime.parent.name) if args.runtime else str(DEPLOYMENTS / "inspect-cetus-788-acceptance-20260912/fix-23-local/kernel-cache"),
               SGLANG_DEFAULT_THINKING="false", SGLANG_IS_IN_CI="0", FIVE_MODEL_COST_RUN=str(run))
    argv = [str(python), "-u", "-c", "from sglang.cli.main import main; main()", "serve",
            "--model-path", profile["model_path"], "--served-model-name", profile["served_model"],
            *profile["common"], *profile[args.strategy],
            "--enable-metrics", "--enable-cache-report", "--host", "127.0.0.1", "--port", str(PORT), "--nccl-port", "30580"]
    if args.extra_args:
        argv.extend(args.extra_args)
    idx = json.loads((Path(profile["model_path"]) / "model.safetensors.index.json").read_text())
    shards = set(idx["weight_map"].values())
    assert all((Path(profile["model_path"]) / name).is_file() for name in shards)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--short"], cwd=source, text=True)
    except subprocess.CalledProcessError:
        commit, dirty = None, "not a git checkout"
    save(run / "launch.json", {"utc": utc(), "model": args.model, "strategy": args.strategy,
         "profile": profile, "argv": argv, "source": str(source), "source_commit": commit, "source_status": dirty,
         "runtime": str(runtime),
         "env": {k: v for k, v in env.items() if k not in ("HOME", "USER", "LOGNAME")},
         "gpu_before": gpu, "model_config_sha256": hashlib.sha256((Path(profile["model_path"]) / "config.json").read_bytes()).hexdigest(),
         "shards": len(shards), "scope": "local only; no platform/online mutations"})
    with (run / "engine.log").open("w") as log:
        proc = subprocess.Popen(argv, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    record = {"pid": proc.pid, "start_ticks": process_start(proc.pid), "run": str(run), "model": args.model,
              "strategy": args.strategy, "name": args.name, "port": PORT, "utc": utc()}
    save(run / "process.json", record)
    save(ROOT / "active-engine.json", record)
    print(json.dumps(record), flush=True)


def stop(args):
    record = json.loads((ROOT / "active-engine.json").read_text())
    assert record["name"] == args.name
    pid = record["pid"]
    ticks = process_start(pid)
    if ticks is None:
        print("Recorded engine already exited")
    else:
        assert ticks == record["start_ticks"] and os.getpgid(pid) == pid
        assert ("FIVE_MODEL_COST_RUN=" + record["run"]).encode() in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        os.killpg(pid, signal.SIGTERM)
        save(Path(record["run"]) / "stop.json", {"utc": utc(), "signal": "SIGTERM", "pid": pid})
        print(f"Sent SIGTERM only to tracked local process group {pid}", flush=True)
    released = wait_for_release(record, PROFILES[record['model']]['gpus'])
    save(Path(record['run']) / 'released.json', {'utc': utc(), **released})
    print(json.dumps({'released': record['name'], **released}), flush=True)


def status(args):
    record = json.loads((ROOT / "active-engine.json").read_text())
    print(json.dumps(record))
    try:
        info = query("/get_server_info")
        save(Path(record["run"]) / "server-info.json", info)
        print(json.dumps({"health": "reachable", "server_info_saved": True}))
    except Exception as exc:
        print(json.dumps({"not_ready": repr(exc)}))
    log = Path(record["run"]) / "engine.log"
    print("\n".join(log.read_text(errors="replace").splitlines()[-15:]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["start", "stop", "status"])
    p.add_argument("--model", choices=PROFILES)
    p.add_argument("--strategy", choices=["throughput", "sla"])
    p.add_argument("--name")
    p.add_argument("--source")
    p.add_argument("--python")
    p.add_argument("--runtime")
    p.add_argument("--extra-args", nargs=argparse.REMAINDER)
    args = p.parse_args()
    globals()[args.action](args)
