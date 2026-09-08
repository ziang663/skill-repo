#!/usr/bin/env python3
"""Narrow PyTorch module input/output dtype probe for diagnostic runs.

Import this helper into the target SGLang/model process. Do not use the hooked
run for headline performance numbers.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def _describe(value: Any) -> Any:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - import environment specific
        raise RuntimeError("dtype_probe requires PyTorch") from exc

    if isinstance(value, torch.Tensor):
        return {
            "kind": "tensor",
            "dtype": str(value.dtype),
            "shape": list(value.shape),
            "device": str(value.device),
            "requires_grad": bool(value.requires_grad),
        }
    if isinstance(value, dict):
        return {str(key): _describe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_describe(item) for item in value]
    return {"kind": type(value).__name__}


class DTypeProbe:
    def __init__(
        self,
        model: Any,
        output_path: str | Path,
        module_pattern: str = ".*",
        max_calls_per_module: int = 1,
        leaf_only: bool = True,
    ) -> None:
        self.model = model
        self.output_path = Path(output_path)
        self.pattern = re.compile(module_pattern)
        self.max_calls = max_calls_per_module
        self.leaf_only = leaf_only
        self.handles: list[Any] = []
        self.calls: dict[str, int] = defaultdict(int)
        self.records: list[dict[str, Any]] = []

    def _hook(self, name: str, module: Any):
        def record(_module: Any, inputs: Any, output: Any) -> None:
            self.calls[name] += 1
            if self.calls[name] > self.max_calls:
                return
            parameters = {
                param_name: {
                    "dtype": str(param.dtype),
                    "shape": list(param.shape),
                    "device": str(param.device),
                }
                for param_name, param in module.named_parameters(recurse=False)
            }
            buffers = {
                buffer_name: {
                    "dtype": str(buffer.dtype),
                    "shape": list(buffer.shape),
                    "device": str(buffer.device),
                }
                for buffer_name, buffer in module.named_buffers(recurse=False)
            }
            self.records.append(
                {
                    "module": name,
                    "class": f"{module.__class__.__module__}.{module.__class__.__qualname__}",
                    "call": self.calls[name],
                    "inputs": _describe(inputs),
                    "output": _describe(output),
                    "parameters": parameters,
                    "buffers": buffers,
                }
            )

        return record

    def __enter__(self) -> "DTypeProbe":
        for name, module in self.model.named_modules():
            display_name = name or "<root>"
            if not self.pattern.search(display_name):
                continue
            if self.leaf_only and any(True for _ in module.children()):
                continue
            self.handles.append(module.register_forward_hook(self._hook(display_name, module)))
        return self

    def close(self) -> None:
        for handle in self.handles:
            handle.remove()
        self.handles.clear()
        payload = {
            "rank": os.environ.get("RANK", os.environ.get("LOCAL_RANK", "unknown")),
            "module_pattern": self.pattern.pattern,
            "max_calls_per_module": self.max_calls,
            "leaf_only": self.leaf_only,
            "records": self.records,
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        self.close()
        return False

