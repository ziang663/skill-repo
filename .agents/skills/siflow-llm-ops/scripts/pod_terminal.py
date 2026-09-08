#!/usr/bin/env python3
"""Run guarded commands through the SiFlow console Pod terminal WebSocket."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from siflow import SiFlow

try:
    import websocket
except ImportError as exc:  # pragma: no cover - environment dependent
    raise SystemExit(
        "websocket-client is required; install the SiFlow websocket extra"
    ) from exc


ANSI_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ANSI_OSC = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--pod-name", required=True)
    parser.add_argument("--owner")
    parser.add_argument("--v-org-name")
    parser.add_argument("--console-base", default="https://console-inner.scitix.ai")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-cuda-corepipes", action="store_true")
    mode.add_argument("--command")
    parser.add_argument("--expected-schedulers", type=int)
    parser.add_argument(
        "--allow-command",
        action="store_true",
        help="Required for --command because arbitrary shell commands may mutate a Pod.",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def strip_ansi(value: str) -> str:
    return ANSI_CSI.sub("", ANSI_OSC.sub("", value)).replace("\r", "")


def websocket_url(args: argparse.Namespace) -> str:
    parsed = urlsplit(args.console_base)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    query = {"cluster": args.cluster, "podName": args.pod_name}
    if args.owner:
        query["owner"] = args.owner
    if args.v_org_name:
        query["vOrgName"] = args.v_org_name
    return (
        f"{scheme}://{parsed.netloc}/sfapi/manage-service/v1/pod-exec?"
        f"{urlencode(query)}"
    )


def corepipe_command() -> str:
    return (
        "h=$(hostname); "
        "for p in $(pgrep -f '^sglang::scheduler'); do "
        'f=/tmp/corepipe.cuda.$h.$p; '
        'if test -p "$f"; then '
        'n=$(find /proc/$p/fd -maxdepth 1 -type l -lname "$f" '
        '2>/dev/null | wc -l); '
        "printf '%s FIFO reader_fds=%s\\n' \"$p\" \"$n\"; "
        "else printf '%s MISSING reader_fds=0\\n' \"$p\"; fi; done"
    )


def main() -> int:
    args = parse_args()
    if args.command and not args.allow_command:
        raise SystemExit("--command requires --allow-command")

    access_key = os.environ.get("SIFLOW_ACCESS_KEY_ID")
    secret_key = os.environ.get("SIFLOW_ACCESS_KEY_SECRET")
    if not access_key or not secret_key:
        raise SystemExit(
            "Set SIFLOW_ACCESS_KEY_ID and SIFLOW_ACCESS_KEY_SECRET in the environment"
        )

    client = SiFlow(
        region=args.region,
        cluster=args.cluster,
        access_key_id=access_key,
        access_key_secret=secret_key,
    )
    headers = [
        f"{key}: {value}"
        for key, value in client.default_headers.items()
        if value is not None
    ]
    command = corepipe_command() if args.check_cuda_corepipes else args.command
    marker = f"__SIFLOW_TERMINAL_{uuid.uuid4().hex}__"
    wrapped = f"printf '{marker}_BEGIN\\n'; {command}; printf '{marker}_END\\n'"

    ws = websocket.create_connection(
        websocket_url(args),
        header=headers,
        timeout=min(args.timeout, 10),
        suppress_origin=True,
    )
    ws.settimeout(2)
    raw = ""
    try:
        try:
            ws.recv()  # Initial prompt.
        except Exception:
            pass
        ws.send(json.dumps({"type": "resize", "rows": 50, "cols": 200}))
        ws.send(json.dumps({"type": "input", "input": wrapped + "\r"}))
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            try:
                message = ws.recv()
            except Exception:
                continue
            if message is None:
                break
            if isinstance(message, bytes):
                message = message.decode(errors="replace")
            raw += message
            if raw.count(f"{marker}_END") >= 2:
                break
    finally:
        ws.close()

    output = strip_ansi(raw)
    print(output, end="" if output.endswith("\n") else "\n")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output)

    if args.check_cuda_corepipes:
        rows = re.findall(
            r"(?m)^\s*(\d+)\s+(FIFO|MISSING)\s+reader_fds=(\d+)\s*$", output
        )
        expected = args.expected_schedulers
        valid_count = bool(rows) if expected is None else len(rows) == expected
        valid_rows = all(state == "FIFO" and int(fds) >= 1 for _, state, fds in rows)
        if not valid_count or not valid_rows:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
