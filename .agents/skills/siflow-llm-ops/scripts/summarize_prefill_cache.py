#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import glob
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

PREFILL = re.compile(
    r"Prefill batch, #new-seq: (\d+), #new-token: (\d+), "
    r"#cached-token: (\d+), token usage: ([0-9.]+), #running-req: (\d+), "
    r"#queue-req: (\d+), #pending-token: (\d+)"
)


def timestamp(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_starts(path: Path | None) -> dict[str, dt.datetime]:
    if path is None:
        return {}
    data = json.loads(path.read_text())
    starts = {}
    for pods in data.values():
        if not isinstance(pods, list):
            continue
        for pod in pods:
            if not isinstance(pod, dict):
                continue
            name = pod.get("name") or pod.get("podName")
            value = pod.get("createTime") or pod.get("startTime")
            if name and value:
                starts[name] = timestamp(value).astimezone(dt.timezone.utc)
    return starts


def open_text(path: str):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize SGLang Prefill cache-hit logs.")
    parser.add_argument("--input", action="append", required=True, help="Glob; repeatable")
    parser.add_argument("--instances", type=Path)
    parser.add_argument("--minutes", type=int, default=5)
    parser.add_argument("--rank-marker", default="PP0 ATTN_CP0 TP0")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    paths = sorted({path for pattern in args.input for path in glob.glob(pattern)})
    starts = load_starts(args.instances)
    bins = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    groups = defaultdict(lambda: [0, 0, 0])

    for path in paths:
        pod = Path(path).name.removesuffix(".gz").removesuffix(".ndjson")
        with open_text(path) as handle:
            for line in handle:
                row = json.loads(line)
                row_time = timestamp(row["_timestamp"])
                if pod in starts and row_time < starts[pod]:
                    continue
                log = row.get("log") or ""
                if args.rank_marker not in log:
                    continue
                match = PREFILL.search(log)
                if not match:
                    continue
                _, new, cached, _, running, queue, pending = match.groups()
                new_tokens, cached_tokens = int(new), int(cached)
                if new_tokens == 64 and cached_tokens == 0:
                    continue
                minute = (row_time.minute // args.minutes) * args.minutes
                bucket = row_time.replace(minute=minute, second=0, microsecond=0)
                values = bins[bucket]
                values[0] += new_tokens
                values[1] += cached_tokens
                values[2] += 1
                values[3] = max(values[3], int(running))
                values[4] = max(values[4], int(queue))
                values[5] = max(values[5], int(pending))
                group = groups[(bucket, pod)]
                group[0] += new_tokens
                group[1] += cached_tokens
                group[2] += 1

    lines = [
        "# Prefill Cache Hit",
        "",
        "| UTC window | Token hit | New tokens | Cached tokens | Batches | Max running | Max queue | Max pending tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for bucket, values in sorted(bins.items()):
        total = values[0] + values[1]
        hit = values[1] / total if total else 0
        lines.append(
            f"| {bucket:%Y-%m-%d %H:%M} | {hit:.2%} | {values[0]} | {values[1]} | "
            f"{values[2]} | {values[3]} | {values[4]} | {values[5]} |"
        )
    lines.extend(["", "## By Pod", ""])
    for (bucket, pod), values in sorted(groups.items()):
        total = values[0] + values[1]
        hit = values[1] / total if total else 0
        lines.append(f"- `{bucket:%Y-%m-%d %H:%M}` `{pod}`: {hit:.2%}, {total} tokens")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
