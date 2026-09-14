"""Local sequential benchmark controller with durable state and bounded searches."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from report_results import main as update_report


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False)+"\n")


def wait_ready(timeout=3600):
    active = json.loads((ROOT / "active-engine.json").read_text())
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:30480/health", timeout=5) as r:
                if r.status == 200:
                    return active
        except Exception:
            pass
        proc = Path(f'/proc/{active["pid"]}/stat')
        if not proc.exists() or proc.read_text().rsplit(")", 1)[1].split()[0] == "Z":
            raise RuntimeError("Tracked engine exited during startup")
        print(json.dumps({"waiting_for_engine": active["name"], "utc": datetime.now(timezone.utc).isoformat()}), flush=True)
        time.sleep(15)
    raise TimeoutError("Local startup timeout; no benchmark sent")


def point(model, scenario, rate, name, n=None):
    out = ROOT / "benchmarks" / name
    if out.exists():
        raise RuntimeError(f"Evidence exists: {out}")
    argv = [sys.executable, str(ROOT / "benchmark.py"), "--model", model,
            "--scenario", scenario, "--rate", str(rate), "--name", name]
    if n:
        argv.extend(["--n", str(n)])
    proc = subprocess.run(argv)
    update_report()
    if proc.returncode or not (out / "summary.json").exists():
        raise RuntimeError(f"Point failed before summary: {name}")
    return json.loads((out / "summary.json").read_text())


def search(args):
    active = wait_ready(args.startup_timeout)
    assert active["model"] == args.model and active["strategy"] == "sla"
    state_path = ROOT / (args.name+"-search.json")
    assert not state_path.exists(), "Do not overwrite a previous search"
    state = {"model": args.model, "engine_run": active["name"], "status": "running", "points": [],
             "requests_per_point": 200, "initial_rate": args.initial_rate,
             "relative_bracket_tolerance": .10, "absolute_bracket_tolerance": .005,
             "max_points": 12, "arrival_process": "deterministic open loop; no concurrency limit"}
    rate = args.initial_rate
    low = high = None
    try:
        for i in range(12):
            name = f"{args.name}-p{i+1:02d}-r{rate:.6f}"
            state["current_point"] = {"name": name, "rate": rate}
            save(state_path, state)
            s = point(args.model, "sla", rate, name)
            state["points"].append({"name": name, "rate": rate, "status": s["status"],
                    "failure_reasons": s["failure_reasons"], "completed_rps": s["completed_rps"],
                    "total_tpm": s["total_tpm"], "mean_ttft_s": s["ttft_s"]["mean"] if s["ttft_s"] else None,
                    "mean_tpot_ms": s["tpot_ms"]["mean"] if s["tpot_ms"] else None})
            infra = set(s["failure_reasons"]) - {"TTFT", "TPOT"}
            if infra:
                state.update(status="infrastructure_failure", stop_reasons=sorted(infra))
                break
            if s["status"] == "PASS":
                low = rate
            else:
                high = rate
            state.update(passing_target_lower=low, failing_target_upper=high)
            save(state_path, state)
            if low is not None and high is not None and high-low <= max(.005, .10*low):
                state["status"] = "bracketed"
                break
            if low is None:
                rate /= 2
                if rate < .015625:
                    state["status"] = "no_pass_within_search_range"
                    break
            elif high is None:
                rate *= 2
            else:
                rate = (low+high)/2
        else:
            state["status"] = "point_budget_reached"
        passes = [p for p in state["points"] if p["status"] == "PASS"]
        state["best_measured_pass"] = max(passes, key=lambda p:p["total_tpm"]) if passes else None
        state["note"] = "Finite 200-request evidence, not an exact/global capacity proof. No repeated confirmation pass."
    except Exception as exc:
        state.update(status="interrupted_or_error", error=repr(exc))
        raise
    finally:
        save(state_path, state)
        update_report()
    print(json.dumps(state, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["throughput", "search"])
    p.add_argument("--model", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--initial-rate", type=float, default=.25)
    p.add_argument('--startup-timeout', type=float, default=3600,
                   help='Startup-only wait budget; does not change request timeouts or SLA')
    args = p.parse_args()
    assert args.startup_timeout > 0
    assert args.name.replace("-", "").replace("_", "").isalnum()
    # Prevent a second controller from competing for the same local worker.
    import fcntl
    with (ROOT / "controller.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "search":
            search(args)
        else:
            active = wait_ready(args.startup_timeout)
            assert active["model"] == args.model and active["strategy"] == "throughput"
            point(args.model, "throughput", float("inf"), args.name)
