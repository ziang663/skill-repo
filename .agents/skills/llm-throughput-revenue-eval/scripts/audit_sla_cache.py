#!/usr/bin/env python3
"""Offline cache audit. Read evidence only; never import a launcher or contact a server.

Output must be a new directory outside every input evidence root. Missing records
are INCOMPLETE, not evidence of a successful flush. A PASS here is an accounting
and cache-isolation verdict, not an SLA/quality/production-capacity certification.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


SELECTED = {
    "v41-resume-02-sla-p06-r0.070312",
    "v4flash-resume-02-sla-p07-r2.500000",
    "v4pro-resume-13-sla-p04-r0.750000",
    "glm53-resume-07-sla-p05-r0.875000",
    "glm53flash-resume-08-sla-p07-r1.625000",
    "sla-tp8-mtp5-mem085-02-p04-r0.750000",
}
NAMES = {"v41": "V4.1 Flash", "v4flash": "V4 Flash 0731",
         "v4pro": "V4 Pro 0813", "glm53": "GLM 5.3 FP8",
         "glm53flash": "GLM 5.3 Flash FP8", "glm53_nvfp4": "GLM 5.3 NVFP4"}


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.is_file() else default


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc(value):
    result = datetime.fromisoformat(value)
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


@lru_cache(maxsize=32)
def flush_events(log_path):
    events = []
    if not log_path.is_file():
        return events
    with log_path.open(errors="replace") as stream:
        for number, line in enumerate(stream, 1):
            if "Cache flushed successfully!" not in line:
                continue
            match = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if match:
                events.append({"utc": utc(match[1]).isoformat(), "line": number,
                               "text": line.strip()})
    return events


def metric(path, name, labels=None):
    if not path.is_file():
        return None
    values = []
    for line in path.read_text().splitlines():
        if not line.startswith(name + "{"):
            continue
        tags, value = line.rsplit("}", 1)
        if labels and not all(f'{key}="{val}"' in tags for key, val in labels.items()):
            continue
        values.append(float(value.split()[0]))
    return sum(values) if values else None


def cache_counter(path):
    parts = [metric(path, "sglang:prefill_effective_tokens_total", {"mode": mode})
             for mode in ("device_hit", "host_hit", "storage_hit")]
    return sum(parts) if all(x is not None for x in parts) else None


def dataset_check(path, manifest):
    import numpy as np
    errors = []
    with np.load(path, allow_pickle=False) as packed:
        inputs = packed["input_ids"]
        shared = packed["shared_prefix"]
    lengths = manifest["per_request_prefix_lengths"]
    digest = hashlib.sha256(inputs.tobytes()).hexdigest()
    if digest != manifest["dataset_sha256"]:
        errors.append("dataset_hash_mismatch")
    if inputs.shape != (manifest["n"], manifest["input_tokens"]):
        errors.append("dataset_shape_mismatch")
        return {"errors": errors, "sha256": digest}
    if len(shared) != max(lengths) or len(shared) >= inputs.shape[1]:
        errors.append("preseed_not_partial_prefix")
    boundaries = defaultdict(set)
    for ids, length in zip(inputs, lengths):
        if not np.array_equal(ids[:length], shared[:length]):
            errors.append("shared_prefix_mismatch")
        first = int(ids[length])
        if length < len(shared) and first == int(shared[length]):
            errors.append("tail_matches_extra_shared_token")
        if first in boundaries[length]:
            errors.append("non_unique_tail_start")
        boundaries[length].add(first)
    return {"errors": sorted(set(errors)), "sha256": digest,
            "input_shape": list(inputs.shape), "shared_prefix_tokens": len(shared),
            "independent_tail_starts": sum(map(len, boundaries.values()))}


def accounting_checks(point, rows, summary):
    errors, missing, counters = [], [], {}
    good = [row for row in rows if row.get("success")]
    totals = {field: sum(row[key] for row in good)
              for field, key in (("input", "input_tokens"), ("output", "output_tokens"),
                                 ("cached", "cached_tokens"))}
    for field, name, labels in (
        ("input", "sglang:prompt_tokens_total", {"is_streaming": "true"}),
        ("output", "sglang:generation_tokens_total", {"is_streaming": "true"}),
        ("cached", "sglang:cached_tokens_total", None),
    ):
        before = metric(point / "metrics-before.txt", name, labels)
        after = metric(point / "metrics-after.txt", name, labels)
        if field == "cached" and (before is None or after is None):
            before, after = (cache_counter(point / f"metrics-{stage}.txt")
                             for stage in ("before", "after"))
            name = "sglang:prefill_effective_tokens_total cache modes"
        delta = after - before if before is not None and after is not None else None
        counters[field] = {"request_sum": totals[field], "server_delta": delta, "source": name}
        if delta is None:
            missing.append(field + "_server_counter_missing")
        elif delta != totals[field]:
            errors.append(field + "_server_counter_mismatch")
    duration = summary["duration_s"]
    derived = {
        "input_tpm": totals["input"] * 60 / duration,
        "output_tpm": totals["output"] * 60 / duration,
        "cached_input_tpm": totals["cached"] * 60 / duration,
        "uncached_input_tpm": (totals["input"] - totals["cached"]) * 60 / duration,
        "total_tpm": (totals["input"] + totals["output"]) * 60 / duration,
        "completed_rps": len(good) / duration,
        "observed_cache_rate": totals["cached"] / totals["input"] if totals["input"] else None,
    }
    for field, value in derived.items():
        if value is not None and not math.isclose(value, summary[field], rel_tol=1e-10, abs_tol=1e-8):
            errors.append(field + "_arithmetic_mismatch")
    if len(rows) != summary["requests"] or len(good) != summary["success"]:
        errors.append("request_count_mismatch")
    for field in ("ttft_s", "tpot_ms"):
        if good:
            value = statistics.mean(row[field] for row in good)
            derived[field + "_mean"] = value
            if not math.isclose(value, summary[field]["mean"], rel_tol=1e-10, abs_tol=1e-8):
                errors.append(field + "_mean_mismatch")
    if rows:
        # This covers saved requests, but cannot prove no HTTP request was ever
        # submitted without leaving a record; counter agreement is independent evidence.
        span = max(r["start_clock"] + r["e2e_s"] for r in rows) - min(r["start_clock"] for r in rows)
        derived["saved_request_wall_span_s"] = span
        if duration + .01 < span:
            errors.append("formal_window_shorter_than_saved_requests")
    return {"errors": errors, "missing": missing, "totals": totals,
            "counters": counters, "derived": derived}


def audit_point(root, path, source_hashes, verify_dataset):
    point = path.parent
    manifest = read_json(path)
    summary = read_json(point / "summary.json")
    flush = read_json(point / "flush.json")
    seeds = read_json(point / "cache-preseed.json", [])
    warm = read_json(point / "warmup.json")
    rows = [read_json(p) for p in sorted((point / "requests").glob("*.json"))]
    errors, missing = [], []
    if not summary:
        missing.append("no_final_summary")
    if not flush:
        missing.append("no_flush_record")
    elif flush.get("http") != 200:
        errors.append("flush_http_failure")
    dp = manifest.get("dp_attention_units", 1)
    if len(seeds) != dp:
        missing.append("preseed_count_incomplete")
    for seed in seeds:
        if not seed.get("success"):
            errors.append("preseed_request_failed")
        if seed.get("cached_tokens") is None:
            missing.append("preseed_cache_count_missing")
        elif seed["cached_tokens"] != 0:
            errors.append("preseed_nonzero_cache_requires_investigation")
        if seed.get("input_tokens") != manifest["prefix_length_max"] or seed.get("output_tokens") != 1:
            errors.append("preseed_length_mismatch")
    engine = manifest["active_engine"]["name"]
    log_path = root / "runs" / engine / "engine.log"
    matched = []
    if warm and seeds:
        # Logs have one-second timestamp resolution. The engine TZ is UTC in
        # the saved launch environment. Allow rounding, not an arbitrary old flush.
        start = utc(warm["utc"]) + timedelta(seconds=warm["e2e_s"] - 1)
        end = utc(seeds[0]["utc"]) + timedelta(seconds=1)
        matched = [event for event in flush_events(log_path) if start <= utc(event["utc"]) <= end]
    if len(matched) < dp:
        missing.append("successful_flush_log_not_verified_for_all_units")
    lengths = manifest["per_request_prefix_lengths"]
    excess, known, missing_cache = [], 0, 0
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        errors.append("duplicate_request_ids")
    for row in rows:
        rid = row["id"]
        if not isinstance(rid, int) or not 0 <= rid < len(lengths):
            errors.append("invalid_request_id")
            continue
        cached = row.get("cached_tokens")
        if isinstance(cached, int):
            known += 1
            if cached > lengths[rid]:
                excess.append({"id": rid, "cached": cached, "expected_prefix": lengths[rid]})
            if cached < 0 or cached > manifest["input_tokens"]:
                errors.append("invalid_cached_token_count")
        else:
            missing_cache += 1
        if row.get("success") and (row["input_tokens"] != manifest["input_tokens"] or
                                   row["output_tokens"] != manifest["output_tokens"]):
            errors.append("formal_token_length_mismatch")
    if excess:
        errors.append("cache_exceeds_constructed_prefix_requires_investigation")
    if missing_cache:
        missing.append("some_requests_have_no_cache_count")
    source = manifest["client"]["script_sha256"]
    if source not in source_hashes:
        missing.append("executed_client_source_hash_not_found")
    dataset_result = None
    if verify_dataset:
        if (point / "input_ids.npz").is_file():
            dataset_result = dataset_check(point / "input_ids.npz", manifest)
            errors.extend(dataset_result["errors"])
        else:
            missing.append("dataset_file_missing")
    accounting = None
    if summary and not any(r.get("success") and not isinstance(r.get("cached_tokens"), int) for r in rows):
        accounting = accounting_checks(point, rows, summary)
        errors.extend(accounting["errors"])
        missing.extend(accounting["missing"])
    return {
        "point": point.name, "evidence_root": str(root),
        "model": manifest["active_engine"]["model"], "selected": point.name in SELECTED,
        "original_sla_status": summary.get("status") if summary else None,
        "original_failure_reasons": summary.get("failure_reasons") if summary else None,
        "audit_status": "FAIL" if errors else ("INCOMPLETE" if missing else "PASS"),
        "errors": sorted(set(errors)), "missing": sorted(set(missing)),
        "saved_requests": len(rows), "saved_success": sum(bool(r.get("success")) for r in rows),
        "cache_counts_known": known, "excess_cache_requests": excess,
        "flush_http": flush.get("http") if flush else None,
        "preseed_cached_tokens": [s.get("cached_tokens") for s in seeds],
        "preseed_input_tokens": [s.get("input_tokens") for s in seeds],
        "flush_log": {"path": str(log_path), "events": matched},
        "client_sha256": source, "client_matching_files": source_hashes.get(source, []),
        "dataset_sha256": manifest["dataset_sha256"], "dataset_check": dataset_result,
        "target_cache_rate": manifest["target_cache_rate"], "accounting": accounting,
        "evidence_sha256": {name: sha256(point / name) for name in
                            ("manifest.json", "summary.json", "flush.json", "cache-preseed.json",
                             "metrics-before.txt", "metrics-after.txt") if (point / name).is_file()},
    }


def render(result):
    rows = result["points"]
    lines = ["# 六模型 SLA 缓存隔离与计量审计", "",
             "这是历史证据的离线核对，不是新的性能测试。审计 PASS 与原点 SLA PASS 是不同判据。", "",
             f"共 {len(rows)} 个 SLA 尝试点；审计状态：`{result['statuses']}`。", "",
             "## 用户表中的六个点", "",
             "| 模型 | 审计 | flush 日志条数 | 首次预置 cached tokens | 超出公共前缀的请求 | 实际命中率 | 重算总 TPM |",
             "|---|---|---:|---|---:|---:|---:|"]
    for row in rows:
        if not row["selected"]:
            continue
        d = (row["accounting"] or {}).get("derived", {})
        hit = d.get("observed_cache_rate")
        tpm = d.get("total_tpm")
        lines.append(f"| {NAMES.get(row['model'], row['model'])} | {row['audit_status']} | "
                     f"{len(row['flush_log']['events'])} | {row['preseed_cached_tokens']} | "
                     f"{len(row['excess_cache_requests'])} | "
                     f"{f'{hit * 100:.6f}%' if hit is not None else '未知'} | "
                     f"{f'{tpm:,.0f}' if tpm is not None else '未知'} |")
    lines += ["", "## 每轮证据", "",
              "| 点 | 原 SLA 状态 | 保存请求 / 成功 | 审计 | 问题或缺失证据 |", "|---|---|---:|---|---|"]
    for row in rows:
        lines.append(f"| {row['point']} | {row['original_sla_status'] or '未完成'} | "
                     f"{row['saved_requests']} / {row['saved_success']} | {row['audit_status']} | "
                     f"{', '.join(row['errors'] + row['missing']) or '无'} |")
    lines += ["", "## 边界", "",
              "- HTTP 200 不是独立的清理成功证据；同时核对当前轮时间窗内的 scheduler 日志、预置命中计数和正式请求缓存上界。",
              "- 首次预置无缓存且正式命中不超出公共前缀，支持没有利用上一轮完整 prompt 缓存；不证明真实业务具有相同工作集或性能。",
              "- 共享前缀在计时前预置；预置成本不计入正式窗口。总 TPM 包含命中输入，不等于新增 prefill 或输出 TPM。",
              "- 源码哈希、数据哈希、逐点指标差值及日志行号见 `audit.json`。未完成点不用于填补或拼接正式结果。",
              "- 离线证据无法验证未被采集的事件；缺失记录标 INCOMPLETE，不能当作成功或直接认定漏 flush。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, action="append", required=True,
                        help="Evidence campaign root; repeat for the other campaign")
    parser.add_argument("--output", type=Path, required=True, help="A new directory outside input roots")
    parser.add_argument("--datasets", choices=("all", "selected", "none"), default="all")
    args = parser.parse_args()
    roots = [path.resolve(strict=True) for path in args.root]
    out = args.output.resolve()
    if out.exists() or any(out == root or root in out.parents for root in roots):
        parser.error("Output must not exist and must be outside all input evidence roots")
    source_hashes = defaultdict(list)
    for root in roots:
        for path in root.glob("*.py"):
            source_hashes[sha256(path)].append(str(path))
    points = []
    for root in roots:
        for path in sorted((root / "benchmarks").glob("*/manifest.json")):
            manifest = read_json(path)
            if manifest.get("scenario") != "sla":
                continue
            verify = args.datasets == "all" or (args.datasets == "selected" and path.parent.name in SELECTED)
            points.append(audit_point(root, path, source_hashes, verify))
    if not points:
        parser.error("No SLA manifests found; check input roots")
    groups = defaultdict(list)
    for row in points:
        groups[row["model"]].append(row)
    result = {"created_utc": datetime.now(timezone.utc).isoformat(), "audit_script_sha256": sha256(Path(__file__)),
              "roots": list(map(str, roots)), "dataset_verification": args.datasets,
              "statuses": dict(Counter(row["audit_status"] for row in points)),
              "selected_points_missing": sorted(SELECTED - {row["point"] for row in points}),
              "by_model": {key: {"attempts": len(values),
                                  "saved_requests": sum(row["saved_requests"] for row in values),
                                  "dataset_hashes": sorted({row["dataset_sha256"] for row in values})}
                           for key, values in groups.items()}, "points": points}
    out.mkdir(parents=True, exist_ok=False)
    (out / "audit.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    (out / "AUDIT.md").write_text(render(result))
    print(json.dumps({"points": len(points), "statuses": result["statuses"],
                      "selected_missing": result["selected_points_missing"], "output": str(out)}))


if __name__ == "__main__":
    main()
