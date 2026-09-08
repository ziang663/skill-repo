#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from siflow import SiFlow


def plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if hasattr(value, "model_dump"):
        return plain(value.model_dump(mode="json", by_alias=True, exclude_none=False))
    if hasattr(value, "data"):
        return plain(value.data)
    return str(value)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot a SiFlow inference service.")
    parser.add_argument("--region", required=True)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--service-id", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    client = SiFlow(
        region=args.region,
        cluster=args.cluster,
        access_key_id=os.environ["SIFLOW_ACCESS_KEY_ID"],
        access_key_secret=os.environ["SIFLOW_ACCESS_KEY_SECRET"],
    )
    service = plain(client.inference.get_service(service_id=args.service_id))
    instances = plain(client.inference.list_service_instances(service_id=args.service_id))
    try:
        syslogs = plain(client.inference.query_sys_logs(args.service_id))
    except Exception as error:
        syslogs = {"error": repr(error)}

    write_json(args.out / "service.json", service)
    write_json(args.out / "instances.json", instances)
    write_json(args.out / "syslogs.json", syslogs)

    print(f"service={args.service_id} name={service.get('name', '')}")
    for role, pods in instances.items():
        print(f"{role}: {len(pods)}")
        for pod in pods:
            if not isinstance(pod, dict):
                continue
            print(
                "  "
                + str(pod.get("name") or pod.get("podName") or "")
                + " status="
                + str(pod.get("status") or "")
                + " restarts="
                + str(pod.get("restartCount") or 0)
                + " created="
                + str(pod.get("createTime") or pod.get("startTime") or "")
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
