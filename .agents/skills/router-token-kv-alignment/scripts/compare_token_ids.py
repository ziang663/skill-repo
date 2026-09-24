#!/usr/bin/env python3
"""Compare ordered prompt token arrays; no engine/GPU dependencies."""

import argparse
import hashlib
import json
from pathlib import Path


def select(value, pointer):
    if not pointer:
        return value
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer must be empty or begin with /")
    for part in pointer[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not key.isdecimal():
                raise ValueError("array pointer component must be a non-negative index")
            value = value[int(key)]
        elif isinstance(value, dict):
            value = value[key]
        else:
            raise ValueError("JSON Pointer traverses a non-container")
    return value


def read_ids(path, pointer):
    ids = select(json.loads(Path(path).read_text(encoding="utf-8")), pointer)
    if not isinstance(ids, list) or any(type(x) is not int or x < 0 for x in ids):
        raise ValueError("expected an array of non-negative integer token IDs")
    return ids


def compare(router, backend, page_size, encoding="token"):
    if page_size <= 0:
        raise ValueError("page size must be positive")
    if encoding not in ("token", "bigram"):
        raise ValueError("encoding must be token or bigram")
    common = next(
        (i for i, (a, b) in enumerate(zip(router, backend)) if a != b),
        min(len(router), len(backend)),
    )
    equal = router == backend
    overlap = int(encoding == "bigram")
    digest = lambda ids: hashlib.sha256(
        json.dumps(ids, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "equal": equal,
        "router_tokens": len(router),
        "backend_tokens": len(backend),
        "common_prefix_tokens": common,
        "first_difference_index": None if equal else common,
        "router_is_backend_prefix": common == len(router),
        "page_size": page_size,
        "encoding": encoding,
        "common_complete_pages": max(0, common - overlap) // page_size,
        "router_complete_pages": max(0, len(router) - overlap) // page_size,
        "backend_complete_pages": max(0, len(backend) - overlap) // page_size,
        "router_sha256": digest(router),
        "backend_sha256": digest(backend),
        "interpretation": "ordered-array comparison; not a measured cache hit",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--router", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--router-pointer", default="")
    parser.add_argument("--backend-pointer", default="")
    parser.add_argument("--page-size", type=int, required=True)
    parser.add_argument("--encoding", choices=("token", "bigram"), default="token")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        result = compare(
            read_ids(args.router, args.router_pointer),
            read_ids(args.backend, args.backend_pointer),
            args.page_size,
            args.encoding,
        )
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.out:
            args.out.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
    except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
        parser.error(str(error))
    return 0 if result["equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
