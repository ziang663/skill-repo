#!/usr/bin/env python3
"""Inspect safetensors headers without loading tensor payloads."""

from __future__ import annotations

import argparse
import json
import math
import struct
from collections import defaultdict
from pathlib import Path
from typing import Any


DTYPE_BYTES = {
    "BOOL": 1,
    "U8": 1,
    "I8": 1,
    "F8_E4M3": 1,
    "F8_E4M3FN": 1,
    "F8_E5M2": 1,
    "F8_E5M2FNUZ": 1,
    "I16": 2,
    "U16": 2,
    "F16": 2,
    "BF16": 2,
    "I32": 4,
    "U32": 4,
    "F32": 4,
    "I64": 8,
    "U64": 8,
    "F64": 8,
}


def read_header(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        raw = handle.read(8)
        if len(raw) != 8:
            raise ValueError(f"Invalid safetensors file: {path}")
        length = struct.unpack("<Q", raw)[0]
        header = handle.read(length)
    return json.loads(header)


def find_files(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    for path in paths:
        if path.is_dir():
            result.extend(sorted(path.rglob("*.safetensors")))
        elif path.suffix == ".safetensors":
            result.append(path)
        else:
            raise ValueError(f"Expected a safetensors file or directory: {path}")
    return sorted(dict.fromkeys(item.resolve() for item in result))


def group_name(name: str, depth: int) -> str:
    parts = name.split(".")
    return ".".join(parts[:depth]) if depth > 0 else "all"


def inspect(files: list[Path], depth: int) -> dict[str, Any]:
    by_dtype: dict[str, dict[str, int]] = defaultdict(lambda: {"tensors": 0, "elements": 0, "bytes": 0})
    by_group: dict[str, dict[str, int]] = defaultdict(lambda: {"tensors": 0, "elements": 0, "bytes": 0})
    unknown_dtypes: set[str] = set()
    tensor_count = 0
    total_elements = 0
    total_bytes = 0

    for path in files:
        header = read_header(path)
        for name, entry in header.items():
            if name == "__metadata__" or not isinstance(entry, dict):
                continue
            dtype = str(entry.get("dtype", "UNKNOWN"))
            shape = entry.get("shape", [])
            elements = math.prod(int(value) for value in shape) if shape else 1
            offsets = entry.get("data_offsets")
            if isinstance(offsets, list) and len(offsets) == 2:
                size_bytes = int(offsets[1]) - int(offsets[0])
            else:
                width = DTYPE_BYTES.get(dtype)
                size_bytes = elements * width if width is not None else 0
            if dtype not in DTYPE_BYTES:
                unknown_dtypes.add(dtype)
            tensor_count += 1
            total_elements += elements
            total_bytes += size_bytes
            for bucket in (by_dtype[dtype], by_group[group_name(name, depth)]):
                bucket["tensors"] += 1
                bucket["elements"] += elements
                bucket["bytes"] += size_bytes

    return {
        "files": [str(path) for path in files],
        "file_count": len(files),
        "tensor_count": tensor_count,
        "total_elements": total_elements,
        "total_bytes": total_bytes,
        "by_dtype": dict(by_dtype),
        "by_group": dict(by_group),
        "unknown_dtypes": sorted(unknown_dtypes),
        "group_depth": depth,
    }


def gib(value: int) -> float:
    return value / (1024**3)


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Safetensors storage inventory",
        "",
        f"- Files: {result['file_count']}",
        f"- Tensors: {result['tensor_count']:,}",
        f"- Tensor elements: {result['total_elements']:,}",
        f"- Payload bytes: {result['total_bytes']:,} ({gib(result['total_bytes']):.3f} GiB)",
        "",
        "> This is checkpoint storage metadata. Tensor elements include scales, packed weights, and auxiliary tensors; they are not automatically equivalent to trainable parameter count.",
        "",
        "## By dtype",
        "",
        "| Dtype | Tensors | Elements | GiB |",
        "|---|---:|---:|---:|",
    ]
    for dtype, values in sorted(result["by_dtype"].items(), key=lambda item: item[1]["bytes"], reverse=True):
        lines.append(f"| {dtype} | {values['tensors']:,} | {values['elements']:,} | {gib(values['bytes']):.3f} |")

    lines.extend(["", f"## By prefix depth {result['group_depth']}", "", "| Prefix | Tensors | Elements | GiB |", "|---|---:|---:|---:|"])
    for name, values in sorted(result["by_group"].items(), key=lambda item: item[1]["bytes"], reverse=True):
        lines.append(f"| `{name}` | {values['tensors']:,} | {values['elements']:,} | {gib(values['bytes']):.3f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--group-depth", type=int, default=2)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = inspect(find_files(args.paths), args.group_depth)
    output = json.dumps(result, indent=2, sort_keys=True) + "\n" if args.format == "json" else markdown(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()

