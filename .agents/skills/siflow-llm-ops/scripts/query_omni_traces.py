#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

HOST = "https://omniobs.scitix.ai"


def parse_tags(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator:
            raise SystemExit(f"invalid tag: {value}")
        result[key] = item
    return result


def post(path: str, body: dict) -> dict:
    request = urllib.request.Request(
        HOST + path,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['OMNI_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description="Search or fetch OmniObs OTel traces.")
    parser.add_argument("--trace-id")
    parser.add_argument("--start-ms", type=int)
    parser.add_argument("--end-ms", type=int)
    parser.add_argument("--service-name", default="")
    parser.add_argument("--span-name", default="")
    parser.add_argument("--span-tag", action="append", default=[])
    parser.add_argument("--resource-tag", action="append", default=[])
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if args.trace_id:
        result = post("/api/query/traces/detail", {"trace_id": args.trace_id})
    else:
        if args.start_ms is None or args.end_ms is None:
            raise SystemExit("search requires --start-ms and --end-ms")
        result = post(
            "/api/query/traces/search",
            {
                "start_time": args.start_ms,
                "end_time": args.end_ms,
                "service_name": args.service_name,
                "span_name": args.span_name,
                "tags": parse_tags(args.span_tag),
                "resource_tags": parse_tags(args.resource_tag),
                "limit": args.limit,
                "offset": args.offset,
                "sort_field": "timestamp",
                "sort_order": "asc",
            },
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
