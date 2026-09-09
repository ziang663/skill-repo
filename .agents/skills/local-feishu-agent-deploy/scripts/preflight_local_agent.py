#!/usr/bin/env python3
"""Read-only safety checks for a local Feishu agent deployment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
from typing import Iterable


DEFAULT_REQUIRED = ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "OPENAI_MODEL")
MODEL_KEY_ALTERNATIVES = ("OPENAI_API_KEY", "SIONIC_API_KEY", "SONIC_API_KEY")


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def parse_env_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        if name.startswith("export "):
            name = name.removeprefix("export ").strip()
        if name:
            names.add(name)
    return names


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def add_result(results: list[dict[str, str]], level: str, check: str, detail: str) -> None:
    results.append({"level": level, "check": check, "detail": detail})


def ignored_by_local_file(project: Path, relative_env: Path) -> tuple[bool, str]:
    ignore_file = project / ".gitignore"
    if not ignore_file.exists():
        return False, ".gitignore is absent"
    target = relative_env.as_posix()
    patterns = {
        line.strip()
        for line in ignore_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and not line.startswith("!")
    }
    matched = target in patterns or relative_env.name in patterns or ".env*" in patterns
    return matched, f"{ignore_file.name}:{relative_env.name}" if matched else "not covered by .gitignore"


def check_ignore(project: Path, relative_env: Path) -> tuple[bool, str]:
    inside = run(["git", "rev-parse", "--is-inside-work-tree"], project)
    if inside.returncode != 0:
        return ignored_by_local_file(project, relative_env)
    result = run(["git", "check-ignore", "-v", "--", str(relative_env)], project)
    if result.returncode == 0:
        rule = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "ignored"
        return True, rule
    return False, "not ignored by Git"


def docker_ignores_env(project: Path, relative_env: Path) -> bool | None:
    path = project / ".dockerignore"
    if not path.exists():
        return None
    target = relative_env.as_posix()
    patterns = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    return target in patterns or relative_env.name in patterns or ".env*" in patterns


def check_package_scripts(project: Path, results: list[dict[str, str]]) -> None:
    package = project / "package.json"
    if not package.exists():
        add_result(results, "WARN", "package", "package.json not found; inspect the project's runtime manually")
        return
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        add_result(results, "FAIL", "package", f"cannot parse package.json: {exc}")
        return
    scripts = data.get("scripts") or {}
    available = [name for name in ("check", "test", "typecheck", "build", "start", "dev") if name in scripts]
    engine = (data.get("engines") or {}).get("node", "unspecified")
    add_result(results, "OK", "package", f"node engine={engine}; scripts={','.join(available) or 'none'}")
    if "start" not in scripts and "dev" not in scripts:
        add_result(results, "WARN", "start-script", "neither npm start nor npm run dev is defined")


def required_names(extra: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*DEFAULT_REQUIRED, *extra)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--env-file", default=".env", type=Path)
    parser.add_argument("--port", type=int, help="Check whether this local port is currently free")
    parser.add_argument("--require", action="append", default=[], help="Additional required environment variable name")
    parser.add_argument(
        "--require-model-key-in-env-file",
        action="store_true",
        help="Fail unless a recognized model API key variable is named in the env file",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a text report")
    args = parser.parse_args()

    project = args.project_dir.expanduser().resolve()
    results: list[dict[str, str]] = []
    if not project.is_dir():
        add_result(results, "FAIL", "project", f"directory does not exist: {project}")
    else:
        add_result(results, "OK", "project", str(project))
        check_package_scripts(project, results)

        env_path = args.env_file if args.env_file.is_absolute() else project / args.env_file
        if not env_path.exists():
            add_result(results, "FAIL", "env-file", f"missing: {env_path}")
        else:
            relative_env = Path(os.path.relpath(env_path, project))
            mode = stat.S_IMODE(env_path.stat().st_mode)
            if mode & 0o077:
                add_result(results, "FAIL", "env-permissions", f"{relative_env} mode is {mode:04o}; require 0600 or stricter")
            else:
                add_result(results, "OK", "env-permissions", f"{relative_env} mode is {mode:04o}")

            ignored, detail = check_ignore(project, relative_env)
            add_result(results, "OK" if ignored else "FAIL", "git-ignore", detail)

            docker_ignored = docker_ignores_env(project, relative_env)
            if docker_ignored is None:
                add_result(results, "WARN", "docker-ignore", ".dockerignore not present")
            else:
                add_result(
                    results,
                    "OK" if docker_ignored else "FAIL",
                    "docker-ignore",
                    f"{relative_env} is {'covered' if docker_ignored else 'not covered'} by .dockerignore",
                )

            try:
                names = parse_env_names(env_path)
            except (OSError, UnicodeError) as exc:
                add_result(results, "FAIL", "env-parse", f"cannot read variable names: {exc}")
            else:
                missing = [name for name in required_names(args.require) if name not in names]
                if missing:
                    add_result(results, "FAIL", "env-names", "missing variable names: " + ", ".join(missing))
                else:
                    add_result(results, "OK", "env-names", "required variable names are present; values were not displayed")
                if not any(name in names for name in MODEL_KEY_ALTERNATIVES):
                    level = "FAIL" if args.require_model_key_in_env_file else "WARN"
                    add_result(
                        results,
                        level,
                        "model-key-name",
                        "no recognized model API key variable is named in the env file; this is valid if injected externally",
                    )

        if args.port is not None:
            if not 1 <= args.port <= 65535:
                add_result(results, "FAIL", "port", "port must be between 1 and 65535")
            elif port_is_free(args.port):
                add_result(results, "OK", "port", f"127.0.0.1:{args.port} is free")
            else:
                add_result(results, "WARN", "port", f"127.0.0.1:{args.port} is already in use; identify its owner")

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print(f"[{item['level']}] {item['check']}: {item['detail']}")

    return 1 if any(item["level"] == "FAIL" for item in results) else 0


if __name__ == "__main__":
    sys.exit(main())
