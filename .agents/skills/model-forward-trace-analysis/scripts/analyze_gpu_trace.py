#!/usr/bin/env python3
"""Aggregate GPU kernel activity from Chrome traces or Nsight SQLite files."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


Kernel = tuple[str, float]  # name, duration in microseconds


def parse_chrome(path: Path) -> list[Kernel]:
    data = json.loads(path.read_text(encoding="utf-8"))
    events = data.get("traceEvents", data) if isinstance(data, dict) else data
    result: list[Kernel] = []
    for event in events:
        if not isinstance(event, dict) or event.get("ph") != "X":
            continue
        category = str(event.get("cat", "")).lower()
        args = event.get("args", {}) or {}
        if not isinstance(args, dict):
            args = {}
        is_kernel = "kernel" in category or "gpu" in category or "stream" in args
        duration = event.get("dur")
        if is_kernel and isinstance(duration, (int, float)) and duration >= 0:
            result.append((str(event.get("name", "<unnamed>")), float(duration)))
    return result


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def parse_nsys_sqlite(path: Path) -> list[Kernel]:
    connection = sqlite3.connect(str(path))
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        kernel_tables = [
            name
            for name in ("CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL", "CUPTI_ACTIVITY_KIND_KERNEL")
            if name in tables
        ][:1]
        if not kernel_tables:
            raise ValueError(f"No Nsight CUDA kernel activity table found in {path}")

        strings: dict[int, str] = {}
        if "StringIds" in tables:
            cols = _columns(connection, "StringIds")
            id_col = "id" if "id" in cols else cols[0]
            value_col = "value" if "value" in cols else cols[-1]
            strings = {int(key): str(value) for key, value in connection.execute(f'SELECT "{id_col}", "{value_col}" FROM "StringIds"')}

        result: list[Kernel] = []
        for table in kernel_tables:
            cols = _columns(connection, table)
            start_col = "start" if "start" in cols else None
            end_col = "end" if "end" in cols else None
            name_col = next((name for name in ("demangledName", "shortName", "name") if name in cols), None)
            if not start_col or not end_col or not name_col:
                raise ValueError(f"Unsupported columns in {table}: {cols}")
            query = f'SELECT "{start_col}", "{end_col}", "{name_col}" FROM "{table}"'
            for start, end, raw_name in connection.execute(query):
                name = strings.get(int(raw_name), str(raw_name)) if isinstance(raw_name, int) else str(raw_name)
                result.append((name, (float(end) - float(start)) / 1000.0))
        return result
    finally:
        connection.close()


def detect_format(path: Path) -> str:
    if path.suffix.lower() in {".sqlite", ".db"}:
        return "nsys-sqlite"
    return "chrome"


def load_rules(path: Path | None) -> tuple[list[tuple[str, re.Pattern[str]]], str]:
    if path is None:
        return [], "Unclassified"
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = [
        (str(item["component"]), re.compile(str(item["pattern"]), re.IGNORECASE))
        for item in data.get("rules", [])
    ]
    return rules, str(data.get("default", "Unclassified"))


def classify(name: str, rules: list[tuple[str, re.Pattern[str]]], default: str) -> str:
    for component, pattern in rules:
        if pattern.search(name):
            return component
    return default


def summarize_one(path: Path, trace_format: str, rules: list[tuple[str, re.Pattern[str]]], default: str) -> dict[str, Any]:
    selected_format = detect_format(path) if trace_format == "auto" else trace_format
    kernels = parse_nsys_sqlite(path) if selected_format == "nsys-sqlite" else parse_chrome(path)
    components: dict[str, float] = defaultdict(float)
    names: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    calls: dict[str, int] = defaultdict(int)
    for name, duration_us in kernels:
        component = classify(name, rules, default)
        components[component] += duration_us
        names[component][name] += duration_us
        calls[name] += 1
    total_us = sum(components.values())
    return {
        "label": f"{path.parent.name}/{path.stem}",
        "path": str(path.resolve()),
        "format": selected_format,
        "kernel_launches": len(kernels),
        "total_activity_us": total_us,
        "components_us": dict(components),
        "kernels_us": {component: dict(values) for component, values in names.items()},
        "kernel_calls": dict(calls),
    }


def aggregate(ranks: list[dict[str, Any]], default: str) -> dict[str, Any]:
    components = sorted({name for rank in ranks for name in rank["components_us"]})
    totals = [rank["total_activity_us"] for rank in ranks]
    rows = []
    for component in components:
        values = [rank["components_us"].get(component, 0.0) for rank in ranks]
        mean = statistics.mean(values)
        rows.append(
            {
                "component": component,
                "rank_values_us": values,
                "mean_us": mean,
                "min_us": min(values),
                "max_us": max(values),
                "imbalance_max_over_mean": max(values) / mean if mean else None,
                "share_of_mean_activity": mean / statistics.mean(totals) if totals and statistics.mean(totals) else None,
            }
        )
    rows.sort(key=lambda item: item["mean_us"], reverse=True)
    return {
        "rank_count": len(ranks),
        "rank_total_activity_us": totals,
        "mean_rank_activity_us": statistics.mean(totals) if totals else 0.0,
        "max_rank_activity_us": max(totals) if totals else 0.0,
        "components": rows,
        "unclassified_component": default,
    }


def top_kernels(ranks: Iterable[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    durations: dict[str, float] = defaultdict(float)
    calls: dict[str, int] = defaultdict(int)
    for rank in ranks:
        for component_values in rank["kernels_us"].values():
            for name, value in component_values.items():
                durations[name] += value
        for name, value in rank["kernel_calls"].items():
            calls[name] += value
    ordered = sorted(durations, key=durations.get, reverse=True)[:limit]
    return [{"name": name, "activity_us": durations[name], "calls": calls[name]} for name in ordered]


def _fmt_us(value: float) -> str:
    return f"{value / 1000.0:.3f}"


def markdown(result: dict[str, Any], limit: int) -> str:
    aggregate_data = result["aggregate"]
    lines = [
        "# GPU kernel activity summary",
        "",
        "> Durations are summed GPU kernel activity, not wall time. Concurrent streams and ranks may overlap.",
        "",
        "## Rank totals",
        "",
        "| Rank/file | Kernel launches | Activity ms |",
        "|---|---:|---:|",
    ]
    for rank in result["ranks"]:
        lines.append(f"| {rank['label']} | {rank['kernel_launches']} | {_fmt_us(rank['total_activity_us'])} |")

    lines.extend(
        [
            "",
            "## Components",
            "",
            "| Component | Mean/rank ms | Share | Min ms | Max ms | Imbalance max/mean |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in aggregate_data["components"]:
        imbalance = "-" if row["imbalance_max_over_mean"] is None else f"{row['imbalance_max_over_mean']:.3f}"
        share = "-" if row["share_of_mean_activity"] is None else f"{100.0 * row['share_of_mean_activity']:.2f}%"
        lines.append(
            f"| {row['component']} | {_fmt_us(row['mean_us'])} | {share} | {_fmt_us(row['min_us'])} | {_fmt_us(row['max_us'])} | {imbalance} |"
        )

    lines.extend(["", f"## Top {limit} kernels across all ranks", "", "| Kernel | Calls | Activity ms |", "|---|---:|---:|"])
    for item in result["top_kernels"]:
        lines.append(f"| `{item['name']}` | {item['calls']} | {_fmt_us(item['activity_us'])} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path, help="One trace per rank or capture.")
    parser.add_argument("--trace-format", choices=("auto", "chrome", "nsys-sqlite"), default="auto")
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rules, default = load_rules(args.rules)
    ranks = [summarize_one(path, args.trace_format, rules, default) for path in args.inputs]
    result = {
        "ranks": ranks,
        "aggregate": aggregate(ranks, default),
        "top_kernels": top_kernels(ranks, args.top),
        "rules_path": str(args.rules.resolve()) if args.rules else None,
    }
    output = json.dumps(result, indent=2, sort_keys=True) + "\n" if args.format == "json" else markdown(result, args.top)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
