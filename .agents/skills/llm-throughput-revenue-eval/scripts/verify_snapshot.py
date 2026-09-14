#!/usr/bin/env python3
"""Verify frozen source bytes and syntax without importing/executing experiment code."""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def verify(root, source_root=None):
    manifest = json.loads((root / "SOURCES.json").read_text())
    errors = []
    for row in manifest["files"]:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe manifest path")
        path = root / relative
        if not path.is_file():
            errors.append({"path": str(relative), "error": "missing"})
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            errors.append({"path": str(relative), "error": "snapshot_hash_mismatch"})
        try:
            if path.suffix == ".py":
                ast.parse(data, filename=str(relative))
            elif path.suffix == ".json":
                json.loads(data)
        except (SyntaxError, ValueError) as exc:
            errors.append({"path": str(relative), "error": str(exc)})
        if source_root:
            source = source_root / relative
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != row["sha256"]:
                errors.append({"path": str(relative), "error": "source_missing_or_changed"})
    return {"files": len(manifest["files"]), "errors": errors,
            "verified_against_local_sources": source_root is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=Path(__file__).parent / "snapshot-20260914")
    parser.add_argument("--source-root", type=Path, help="Optional original deployments directory")
    args = parser.parse_args()
    result = verify(args.snapshot, args.source_root)
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result["errors"]))


if __name__ == "__main__":
    main()
