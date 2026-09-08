#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HOST = "https://omniobs.scitix.ai"
PAGE = 5000


def force_host_resolution(host: str, ip: str) -> None:
    """Resolve one hostname to a caller-supplied IP without changing /etc/hosts."""
    original_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(name, *args, **kwargs):
        if name == host:
            name = ip
        return original_getaddrinfo(name, *args, **kwargs)

    socket.getaddrinfo = getaddrinfo


def post(token: str, project: str, body: dict) -> dict:
    url = f"{HOST}/api/query/logs/query?" + urllib.parse.urlencode({"project": project})
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    last_error = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = (error.read() or b"")[:300].decode("utf-8", "replace")
            if error.code == 401:
                raise SystemExit(f"401 UNAUTHORIZED: {detail}")
            if error.code not in (429, 502, 503, 504):
                raise SystemExit(f"HTTP {error.code}: {detail}")
            last_error = detail
        except Exception as error:
            last_error = repr(error)
        time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f"OmniObs request failed: {last_error}")


def count(token: str, project: str, kind: str, query: str, start: int, end: int) -> int:
    body = {"kind": kind, "start_time": start, "end_time": end, "query": query, "limit": 1}
    return int(((post(token, project, body).get("data") or {}).get("total") or 0))


def fetch(token: str, project: str, kind: str, query: str, start: int, end: int) -> list[dict]:
    total = count(token, project, kind, query, start, end)
    if total == 0:
        return []
    if total > PAGE and end - start > 1:
        middle = (start + end) // 2
        return fetch(token, project, kind, query, start, middle) + fetch(
            token, project, kind, query, middle, end
        )
    rows: list[dict] = []
    offset = 0
    while True:
        body = {
            "kind": kind,
            "start_time": start,
            "end_time": end,
            "query": query,
            "limit": PAGE,
            "offset": offset,
            "sort_field": "_timestamp",
            "sort_order": "asc",
        }
        page = (post(token, project, body).get("data") or {}).get("log_data") or []
        rows.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
    return rows


def dedupe(rows: list[dict]) -> list[dict]:
    unique = {}
    for row in rows:
        key = (row.get("_timestamp"), row.get("pod_name"), row.get("log"))
        unique[key] = row
    return sorted(unique.values(), key=lambda row: (row.get("_timestamp") or "", row.get("log") or ""))


def fetch_pod(args, token: str, pod: str) -> tuple[str, int]:
    query = f'{args.filter} AND pod_name="{pod}"' if args.filter else f'pod_name="{pod}"'
    rows = dedupe(fetch(token, args.project, args.kind, query, args.from_ms, args.to_ms))
    output = args.outdir / f"{pod}.ndjson.gz"
    with gzip.open(output, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return pod, len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch per-Pod logs from OmniObs.")
    parser.add_argument("--from-ms", type=int, required=True)
    parser.add_argument("--to-ms", type=int, required=True)
    parser.add_argument("--pods", required=True, help="JSON list file or comma-separated Pod names")
    parser.add_argument("--filter", default="")
    parser.add_argument("--project", default="default")
    parser.add_argument("--kind", default="container_stdout")
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--resolve-ip",
        help="Force omniobs.scitix.ai to this IP while preserving HTTPS hostname/SNI",
    )
    args = parser.parse_args()

    if args.resolve_ip:
        force_host_resolution(urllib.parse.urlparse(HOST).hostname, args.resolve_ip)

    token = os.environ["OMNI_TOKEN"]
    if Path(args.pods).is_file():
        pods = json.loads(Path(args.pods).read_text())
    else:
        pods = [pod.strip() for pod in args.pods.split(",") if pod.strip()]
    args.outdir.mkdir(parents=True, exist_ok=True)

    manifest = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(fetch_pod, args, token, pod): pod for pod in pods}
        for future in as_completed(futures):
            pod, rows = future.result()
            manifest[pod] = {"rows": rows}
            print(f"{pod}: {rows}")
    (args.outdir / "_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
