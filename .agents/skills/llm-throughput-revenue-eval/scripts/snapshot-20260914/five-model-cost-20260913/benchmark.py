"""Deterministic token-exact shared-prefix load; unrestricted client concurrency.

Only loopback native SGLang /generate is supported. All requests and stream timing
are persisted. Cache pre-seeding is separately accounted and excluded from formal
timing. Finite rates use deterministic open-loop arrivals, not response pacing.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

import aiohttp
import numpy as np
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parent
PROFILES = json.loads((ROOT / "profiles.json").read_text())
BASE = "http://127.0.0.1:30480"
FORMAL_REQUESTS = 200


def connector():
    # Dataset construction may block the event loop past the server's keepalive
    # timeout. Never reuse that stale socket for a non-idempotent POST. Opening
    # each local request's connection is included in its measured latency.
    return aiohttp.TCPConnector(limit=0, limit_per_host=0, force_close=True)


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def utc():
    return datetime.now(timezone.utc).isoformat()


def distribution(values):
    a = np.asarray(values, dtype=float)
    return {"mean": float(a.mean()), "p50": float(np.quantile(a, .5)),
            "p95": float(np.quantile(a, .95)), "p99": float(np.quantile(a, .99)),
            "min": float(a.min()), "max": float(a.max())} if len(a) else None


def effective_args(info):
    # SGLang releases expose flattened args or a nested server_args object.
    candidate = info.get("server_args", info)
    if not isinstance(candidate, dict) or "model_path" not in candidate or "tp_size" not in candidate:
        raise RuntimeError("Missing effective server args in supported layouts")
    states = info.get("internal_states", [])
    if states and isinstance(states[0], dict) and states[0].get("model_path") == candidate["model_path"]:
        candidate = {**candidate, **states[0]}
    return candidate


class Stream:
    def __init__(self):
        self.first = None
        self.last = None
        self.meta = {}
        self.text = ""
        self.error = None
        self.events = []
        self.tokens = 0
        self.done = False

    def feed(self, data, elapsed):
        if data == "[DONE]":
            self.done = True
            return
        item = json.loads(data)
        if "error" in item:
            self.error = item["error"]
            return
        meta = item.get("meta_info", {})
        count = int(meta.get("completion_tokens", 0))
        if count > self.tokens:
            if self.first is None:
                self.first = elapsed
            self.last = elapsed
            self.events.append([elapsed, count])
            self.tokens = count
        self.meta = meta or self.meta
        self.text = item.get("text", self.text)

    def result(self, expected_input, expected_output):
        finish = self.meta.get("finish_reason")
        completed = isinstance(finish, dict) and finish.get("type") in ("length", "stop")
        cached = self.meta.get("cached_tokens")
        success = (not self.error and completed and self.tokens == expected_output
                   and self.meta.get("prompt_tokens") == expected_input and self.first is not None)
        return {"success": bool(success), "input_tokens": self.meta.get("prompt_tokens"),
                "output_tokens": self.tokens, "cached_tokens": cached,
                "ttft_s": self.first, "tpot_ms": (self.last-self.first)*1000/(self.tokens-1) if self.tokens > 1 else None,
                "token_finish_s": self.last, "finish_reason": finish, "stream_done": self.done,
                "body_error": self.error, "meta_info": self.meta, "token_events": self.events,
                "text_sha256": hashlib.sha256(self.text.encode()).hexdigest(), "text_sample": self.text[:160]}


async def request(session, body, expected_input, expected_output, rid, planned=None):
    started = time.perf_counter()
    stream = Stream()
    row = {"id": rid, "start_clock": started, "utc": utc(),
           "dispatch_lag_s": max(0, started-planned) if planned is not None else 0}
    try:
        async with session.post(BASE + "/generate", data=body, headers={"Content-Type": "application/json"}) as response:
            row["http"] = response.status
            if response.status != 200:
                row.update(success=False, response_body=(await response.text())[:4000])
            else:
                async for line in response.content:
                    if line.startswith(b"data:"):
                        stream.feed(line[5:].decode().strip(), time.perf_counter()-started)
                row.update(stream.result(expected_input, expected_output))
    except Exception as exc:
        row.update(success=False, exception=repr(exc), partial_meta=stream.meta)
    row["e2e_s"] = time.perf_counter()-started
    return row


def payload(ids, output, rid, dp_rank=None):
    p = {"input_ids": ids, "sampling_params": {"max_new_tokens": output,
         "temperature": 0, "ignore_eos": True}, "stream": True, "rid": rid}
    if dp_rank is not None:
        p["routed_dp_rank"] = dp_rank
    return json.dumps(p, separators=(",", ":")).encode()


def dataset(profile, n, length, hit, page_size, seed):
    tokpath = Path(profile["model_path"]) / "tokenizer.json"
    tok = Tokenizer.from_file(str(tokpath))
    special = {i for i, v in tok.get_added_tokens_decoder().items() if v.special}
    valid = np.asarray(sorted(set(tok.get_vocab().values()) - special), dtype=np.int32)
    rng = np.random.default_rng(seed)
    target = length * hit
    lo = int(target // page_size) * page_size
    hi = min(lo + page_size, length - 1)
    n_hi = int(round((target-lo)*n/(hi-lo))) if hi > lo else 0
    lengths = np.asarray([hi]*n_hi + [lo]*(n-n_hi))
    rng.shuffle(lengths)
    shared = rng.choice(valid, size=int(lengths.max()) + 1)
    prompts = []
    for i, size in enumerate(lengths):
        tail = rng.choice(valid, size=length-int(size))
        # Prevent a shared extra page: first unique token differs from the common
        # prefix and other requests' unique-start tokens for this boundary.
        first = int(valid[(i+1000) % len(valid)])
        if first == int(shared[size]):
            first = int(valid[(i+1000+n) % len(valid)])
        tail[0] = first
        prompts.append(np.concatenate((shared[:size], tail)).astype(np.int32))
    array = np.stack(prompts)
    return array, shared[:int(lengths.max())], {"seed": seed, "n": n, "input_tokens": length,
        "target_cache_rate": hit, "page_size": page_size, "prefix_length_min": lo,
        "prefix_length_max": int(lengths.max()), "constructed_cache_rate": float(lengths.mean()/length),
        "per_request_prefix_lengths": lengths.tolist(), "dataset_sha256": hashlib.sha256(array.tobytes()).hexdigest(),
        "tokenizer_sha256": hashlib.sha256(tokpath.read_bytes()).hexdigest(),
        "distribution": "uniform valid non-special tokenizer IDs; shared prefix plus independent unique tails",
        "format": "native input_ids, no chat-template/re-tokenization drift"}


async def snapshot(session, out, suffix):
    result = {}
    for endpoint in ("/health", "/get_server_info", "/metrics"):
        try:
            async with session.get(BASE+endpoint, timeout=aiohttp.ClientTimeout(total=15)) as response:
                txt = await response.text()
                result[endpoint] = {"http": response.status}
                name = endpoint.strip("/").replace("/", "_")
                (out/f"{name}-{suffix}.txt").write_text(txt)
        except Exception as exc:
            result[endpoint] = {"error": repr(exc)}
    return result


async def run(args):
    profile = PROFILES[args.model]
    active = json.loads((ROOT / "active-engine.json").read_text())
    assert active["model"] == args.model and active["port"] == 30480, active
    out = ROOT / "benchmarks" / args.name
    assert not out.exists(), "Never overwrite evidence"
    out.mkdir(parents=True)
    n = FORMAL_REQUESTS if args.n is None else args.n
    assert n > 0
    length = 76800 if args.scenario == "throughput" else profile["sla_input"]
    output = 1024 if args.scenario == "throughput" else profile["sla_output"]
    hit = .9 if args.scenario == "throughput" else profile["cache_rate"]
    timeout = aiohttp.ClientTimeout(total=1800, sock_connect=15, sock_read=1200)
    async with aiohttp.ClientSession(connector=connector(), timeout=timeout, trust_env=False) as session:
        async with session.get(BASE + "/get_server_info") as response:
            assert response.status == 200
            info = await response.json()
        save(out/"initial-server-info.json", info)
        save(Path(active["run"])/"server-info.json", info)
        server_args = effective_args(info)
        assert server_args["model_path"] == profile["model_path"], "Wrong model weights"
        page = int(server_args.get("page_size") or 1)
        dp = int(server_args.get("dp_size") or 1) if server_args.get("enable_dp_attention") else 1
        array, shared, manifest = dataset(profile, n, length, hit, page, args.seed)
        np.savez_compressed(out/"input_ids.npz", input_ids=array, shared_prefix=shared)
        manifest.update(output_tokens=output, active_engine=active, scenario=args.scenario,
                        request_rate="inf" if math.isinf(args.rate) else args.rate,
                        concurrency_limit=None, arrivals="all at once" if math.isinf(args.rate) else "deterministic open loop",
                        utc=utc(), dp_attention_units=dp,
                        transport="new TCP connection per request; no connection-pool cap; no client retry",
                        cache_rate_absolute_tolerance=.005,
                        client={"python": sys.version, "numpy": np.__version__, "aiohttp": aiohttp.__version__,
                                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
        save(out/"manifest.json", manifest)
        # Bounded unrelated warmup, then clear it before pre-seeding formal prefix.
        warm = await request(session, payload(array[0, -128:].tolist(), 16, args.name+"-warm"), 128, 16, "warmup")
        save(out/"warmup.json", warm)
        if not warm["success"]:
            raise RuntimeError("Warmup failed; no formal benchmark sent")
        # SSE completion can precede scheduler removal of the final batch.
        # All pinned runtimes provide a bounded server-side wait for true idle.
        async with session.post(BASE+"/flush_cache", params={"timeout": 30},
                                timeout=aiohttp.ClientTimeout(total=35)) as response:
            flush = {"http": response.status, "body": await response.text(), "idle_wait_timeout_s": 30}
        save(out/"flush.json", flush)
        if flush["http"] != 200:
            raise RuntimeError("Cache flush failed")
        seeds = []
        for rank in range(dp):
            row = await request(session, payload(shared.tolist(), 1, args.name+f"-seed-{rank}", rank if dp>1 else None), len(shared), 1, f"seed-{rank}")
            seeds.append(row)
            if not row["success"]:
                save(out/"cache-preseed.json", seeds)
                raise RuntimeError("Cache preseed failed; no formal benchmark sent")
        save(out/"cache-preseed.json", seeds)
        bodies = [payload(ids.tolist(), output, args.name+f"-{i}") for i, ids in enumerate(array)]
        before = await snapshot(session, out, "before")
        rows = []
        begun = time.perf_counter()
        save(out/"progress.json", {"phase": "formal", "completed": 0, "total": n, "utc": utc()})

        async def one(i):
            planned = begun if math.isinf(args.rate) else begun+i/args.rate
            await asyncio.sleep(max(0, planned-time.perf_counter()))
            row = await request(session, bodies[i], length, output, i, planned)
            rows.append(row)
            save(out/"requests"/f"{i:04}.json", row)
            save(out/"progress.json", {"phase": "formal", "completed": len(rows), "total": n,
                 "success": sum(r["success"] for r in rows), "elapsed_s": time.perf_counter()-begun, "utc": utc()})
            if len(rows)%10 == 0 or not row["success"]:
                print(json.dumps({"point": args.name, "completed": len(rows), "n": n,
                      "success": sum(r["success"] for r in rows), "elapsed_s": round(time.perf_counter()-begun, 1)}), flush=True)

        await asyncio.gather(*(one(i) for i in range(n)))
        duration = time.perf_counter()-begun
        after = await snapshot(session, out, "after")
    good = [r for r in rows if r["success"]]
    total_input = sum(r["input_tokens"] for r in good)
    total_output = sum(r["output_tokens"] for r in good)
    cache_known = all(isinstance(r.get("cached_tokens"), int) for r in good) and bool(good)
    cached = sum(r["cached_tokens"] for r in good) if cache_known else None
    ttft = distribution([r["ttft_s"] for r in good])
    tpot = distribution([r["tpot_ms"] for r in good])
    starts = sorted(r["start_clock"] for r in rows)
    actual_offered = (n-1)/(starts[-1]-starts[0]) if n>1 and starts[-1]>starts[0] else None
    reasons = []
    if len(good) != n:
        reasons.append("request_failure")
    if after["/health"].get("http") != 200:
        reasons.append("unhealthy_after")
    observed_hit = cached/total_input if cached is not None and total_input else None
    if observed_hit is None or abs(observed_hit-hit) > .005:
        reasons.append("cache_rate_mismatch")
    if args.scenario == "sla":
        if not ttft or (ttft["mean"] >= profile["ttft_s"] if profile.get("ttft_strict") else ttft["mean"] > profile["ttft_s"]):
            reasons.append("TTFT")
        if not tpot or tpot["mean"] > profile["tpot_ms"]:
            reasons.append("TPOT")
        if not math.isinf(args.rate) and (actual_offered is None or actual_offered < args.rate*.95):
            reasons.append("client_offered_rate_shortfall")
    summary = {"utc": utc(), "status": "PASS" if not reasons else "FAIL", "failure_reasons": reasons,
         "model": args.model, "scenario": args.scenario, "gpus": profile["gpus"], "engine_run": active["name"],
         "requests": n, "success": len(good), "duration_s": duration, "request_rate": manifest["request_rate"],
         "actual_offered_rps": actual_offered, "completed_rps": len(good)/duration,
         "input_tpm": total_input*60/duration, "output_tpm": total_output*60/duration,
         "total_tpm": (total_input+total_output)*60/duration,
         "cached_input_tpm": cached*60/duration if cached is not None else None,
         "uncached_input_tpm": (total_input-cached)*60/duration if cached is not None else None,
         "observed_cache_rate": observed_hit, "target_cache_rate": hit,
         "ttft_s": ttft, "tpot_ms": tpot, "e2e_s": distribution([r["e2e_s"] for r in good]),
         "dispatch_lag_s": distribution([r["dispatch_lag_s"] for r in rows]),
         "preseed_duration_s": sum(r["e2e_s"] for r in seeds), "health_before": before, "health_after": after,
         "note": "Logical input includes cached tokens; no accuracy claim; aggregate includes fill and drain"}
    save(out/"summary.json", summary)
    save(out/"progress.json", {"phase": "done", "completed": n, "success": len(good), "utc": utc()})
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", choices=PROFILES, required=True)
    p.add_argument("--scenario", choices=["throughput", "sla"], required=True)
    p.add_argument("--rate", type=float, default=float("inf"))
    p.add_argument("--n", type=int)
    p.add_argument("--seed", type=int, default=20260913)
    p.add_argument("--name", required=True)
    args = p.parse_args()
    assert args.rate > 0 and args.name.replace("-", "").replace("_", "").replace(".", "").isalnum()
    asyncio.run(run(args))
