#!/usr/bin/env python3
"""Validate and optionally create a SiFlow LLM Inference service from JSON."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from siflow import SiFlow
from siflow.types.inference import ServiceCreateParams


SENSITIVE_KEY_PARTS = ("token", "secret", "password", "access_key", "accesskey")


def dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=False)
    if isinstance(value, dict):
        return {key: dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [dump(item) for item in value]
    return value


def reject_embedded_secrets(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if any(part in key.lower() for part in SENSITIVE_KEY_PARTS) and item not in (None, "", [], {}):
                raise ValueError(f"payload contains a non-empty secret-like field at {child}")
            reject_embedded_secrets(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_embedded_secrets(item, f"{path}[{index}]")


def write_private_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    raw = json.loads(args.payload.read_text())
    reject_embedded_secrets(raw)
    params = ServiceCreateParams.model_validate(raw)
    canonical = params.model_dump(mode="json", by_alias=True, exclude_none=True)
    service_name = canonical.get("name")
    if not service_name:
        raise ValueError("payload.name is required")

    write_private_json(args.out_dir / "service_create_payload.validated.json", canonical)
    if not args.apply:
        print(f"dry-run validated: {service_name}")
        return

    access_key = os.environ["SIFLOW_ACCESS_KEY_ID"]
    secret_key = os.environ["SIFLOW_ACCESS_KEY_SECRET"]
    client = SiFlow(
        region=args.region,
        cluster=args.cluster,
        access_key_id=access_key,
        access_key_secret=secret_key,
    )

    candidates = client.inference.list_services(search=service_name, page=1, page_size=100)
    exact = [item for item in candidates if item.name == service_name]
    if exact:
        ids = [item.id for item in exact]
        raise RuntimeError(f"refusing duplicate service name {service_name!r}; existing IDs: {ids}")

    service_id = client.inference.create_service(service_params=params)
    service = client.inference.get_service(service_id=service_id)
    instances = client.inference.list_service_instances(service_id=service_id)
    write_private_json(args.out_dir / "service_after_create.json", dump(service))
    write_private_json(args.out_dir / "instances_after_create.json", dump(instances))
    (args.out_dir / "service_id.txt").write_text(f"{service_id}\n")
    (args.out_dir / "service_id.txt").chmod(0o600)
    print(f"created service id={service_id} name={service_name}")


if __name__ == "__main__":
    main()
