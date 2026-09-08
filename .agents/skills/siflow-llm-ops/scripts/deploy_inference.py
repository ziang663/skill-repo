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
ANONYMOUS_HF_TOKEN_PATH = "$.modelConfig.modelSource.storage.hf.token"


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
            is_public_hf_marker = child == ANONYMOUS_HF_TOKEN_PATH and item == "anonymous"
            if (
                any(part in key.lower() for part in SENSITIVE_KEY_PARTS)
                and item not in (None, "", [], {})
                and not is_public_hf_marker
            ):
                raise ValueError(f"payload contains a non-empty secret-like field at {child}")
            reject_embedded_secrets(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_embedded_secrets(item, f"{path}[{index}]")


def validate_model_source(value: dict[str, Any]) -> None:
    model_source = value.get("modelConfig", {}).get("modelSource", {})
    if model_source.get("storageType") != "hf":
        return

    hf = model_source.get("storage", {}).get("hf", {})
    if not hf.get("model"):
        raise ValueError("HF model source requires modelConfig.modelSource.storage.hf.model")
    if not hf.get("token"):
        raise ValueError(
            "SiFlow requires modelConfig.modelSource.storage.hf.token even for a public model; "
            "use the literal 'anonymous' for public Hugging Face repositories"
        )


def exact_name_matches(client: SiFlow, service_name: str) -> list[Any]:
    matches: list[Any] = []
    page = 1
    page_size = 100
    while True:
        candidates = client.inference.list_services(
            search=service_name,
            page=page,
            page_size=page_size,
        )
        rows = list(candidates)
        matches.extend(item for item in rows if item.name == service_name)
        if len(rows) < page_size:
            return matches
        page += 1


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
    validate_model_source(raw)
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

    exact = exact_name_matches(client, service_name)
    if exact:
        ids = [item.id for item in exact]
        raise RuntimeError(f"refusing duplicate service name {service_name!r}; existing IDs: {ids}")

    try:
        service_id = client.inference.create_service(service_params=params)
    except Exception as error:
        failure: dict[str, Any] = {
            "serviceName": service_name,
            "errorType": type(error).__name__,
            "error": str(error),
            "retryAttempted": False,
        }
        try:
            after_failure = exact_name_matches(client, service_name)
            failure["exactNameMatchesAfterFailure"] = [
                {
                    "id": getattr(item, "id", None),
                    "name": getattr(item, "name", None),
                    "status": dump(getattr(item, "status", None)),
                }
                for item in after_failure
            ]
        except Exception as lookup_error:
            failure["postFailureLookupError"] = repr(lookup_error)
        write_private_json(args.out_dir / "create_failure.json", failure)
        raise RuntimeError(
            f"service creation failed for {service_name!r}; no retry was attempted; "
            f"see {args.out_dir / 'create_failure.json'}"
        ) from error

    service = client.inference.get_service(service_id=service_id)
    instances = client.inference.list_service_instances(service_id=service_id)
    write_private_json(args.out_dir / "service_after_create.json", dump(service))
    write_private_json(args.out_dir / "instances_after_create.json", dump(instances))
    (args.out_dir / "service_id.txt").write_text(f"{service_id}\n")
    (args.out_dir / "service_id.txt").chmod(0o600)
    print(f"created service id={service_id} name={service_name}")


if __name__ == "__main__":
    main()
