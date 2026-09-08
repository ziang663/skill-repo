#!/usr/bin/env python3
"""Summarize SGLang request performance dump JSON files.

The script keeps request/stage wall time distinct from per-step samples and
flags a suspiciously short first sample that may indicate asynchronous CUDA
timing attribution. It does not silently rewrite total request timing.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _step_values(data: dict[str, Any]) -> list[float]:
    result: list[float] = []
    for entry in data.get("denoise_steps_ms", []) or []:
        value = entry.get("duration_ms") if isinstance(entry, dict) else entry
        parsed = _number(value)
        if parsed is not None:
            result.append(parsed)
    return result


def _stages(data: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for entry in data.get("steps", []) or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        value = _number(entry.get("duration_ms"))
        if isinstance(name, str) and value is not None:
            result[name] = value
    return result


def _memory_peak(data: dict[str, Any]) -> dict[str, float | None]:
    checkpoints = data.get("memory_checkpoints", {}) or {}
    allocated: list[float] = []
    reserved: list[float] = []
    host: list[float] = []
    if isinstance(checkpoints, dict):
        for snapshot in checkpoints.values():
            if not isinstance(snapshot, dict):
                continue
            for key, target in (
                ("peak_allocated_mb", allocated),
                ("peak_reserved_mb", reserved),
                ("peak_host_anon_mb", host),
            ):
                value = _number(snapshot.get(key))
                if value is not None:
                    target.append(value)
    return {
        "peak_allocated_mb": max(allocated) if allocated else None,
        "peak_reserved_mb": max(reserved) if reserved else None,
        "peak_host_anon_mb": max(host) if host else None,
    }


def summarize(path: Path, policy: str) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    values = _step_values(data)
    suspicious_first = False
    if len(values) >= 3:
        rest_median = statistics.median(values[1:])
        suspicious_first = rest_median > 0 and values[0] < 0.25 * rest_median

    exclude_first = policy == "always" or (policy == "auto" and suspicious_first)
    stable = values[1:] if exclude_first and len(values) > 1 else values
    step_summary: dict[str, Any] = {
        "samples": len(values),
        "stable_samples": len(stable),
        "excluded_first": exclude_first,
        "suspicious_first": suspicious_first,
        "first_ms": values[0] if values else None,
    }
    if stable:
        step_summary.update(
            {
                "sum_ms": sum(stable),
                "mean_ms": statistics.mean(stable),
                "median_ms": statistics.median(stable),
                "min_ms": min(stable),
                "max_ms": max(stable),
            }
        )

    total = _number(data.get("total_duration_ms"))
    stages = _stages(data)
    return {
        "label": path.stem,
        "path": str(path.resolve()),
        "request_id": data.get("request_id"),
        "commit_hash": data.get("commit_hash"),
        "total_duration_ms": total,
        "stage_sum_ms": sum(stages.values()),
        "unattributed_wall_ms": total - sum(stages.values()) if total is not None else None,
        "stages_ms": stages,
        "step_timing": step_summary,
        "memory": _memory_peak(data),
        "meta": data.get("meta", {}),
    }


def _fmt(value: Any) -> str:
    return "-" if value is None else f"{float(value):.3f}"


def markdown(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# SGLang request performance summary",
        "",
        "| Case | Request total ms | Stable step median ms | Stable samples | Peak reserved MB | Warning |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in summaries:
        step = item["step_timing"]
        warning = "first sample suspicious/excluded" if step["suspicious_first"] else ""
        lines.append(
            "| {label} | {total} | {median} | {count} | {reserved} | {warning} |".format(
                label=item["label"],
                total=_fmt(item["total_duration_ms"]),
                median=_fmt(step.get("median_ms")),
                count=step["stable_samples"],
                reserved=_fmt(item["memory"]["peak_reserved_mb"]),
                warning=warning,
            )
        )

    stage_names = sorted({name for item in summaries for name in item["stages_ms"]})
    if stage_names:
        lines.extend(["", "## Stage wall time", ""])
        lines.append("| Stage | " + " | ".join(item["label"] for item in summaries) + " |")
        lines.append("|---|" + "---:|" * len(summaries))
        for name in stage_names:
            lines.append(
                "| " + name + " | " + " | ".join(_fmt(item["stages_ms"].get(name)) for item in summaries) + " |"
            )

    warnings = [item for item in summaries if item["step_timing"]["suspicious_first"]]
    if warnings:
        lines.extend(
            [
                "",
                "> Warning: at least one first step was less than 25% of the median of later steps. This can occur when CUDA work is asynchronously attributed to the following scope. Confirm with synchronized instrumentation or a GPU timeline before using per-step samples as exact forward latency.",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument(
        "--first-step-policy",
        choices=("auto", "always", "never"),
        default="auto",
        help="Whether to exclude the first per-step sample from stable statistics.",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    summaries = [summarize(path, args.first_step_policy) for path in args.inputs]
    output = (
        json.dumps({"cases": summaries}, indent=2, sort_keys=True) + "\n"
        if args.format == "json"
        else markdown(summaries)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()

