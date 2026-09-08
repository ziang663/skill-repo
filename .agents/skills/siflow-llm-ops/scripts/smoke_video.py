#!/usr/bin/env python3
"""Run and preserve an asynchronous SGLang /v1/videos smoke test."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


def write_text(path: Path, value: str) -> None:
    path.write_text(value)
    path.chmod(0o600)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_json(response: httpx.Response, output: Path) -> Any:
    try:
        value = response.json()
    except ValueError:
        write_text(output, response.text)
        response.raise_for_status()
        raise RuntimeError(f"expected JSON response from {response.request.url}")
    write_json(output, value)
    response.raise_for_status()
    return value


def media_probe(media: Path, out_dir: Path, require_audio: bool) -> None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        print("ffprobe unavailable; media metadata validation skipped", flush=True)
        return

    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        (
            "format=format_name,duration,size,bit_rate:"
            "stream=index,codec_name,codec_type,profile,width,height,pix_fmt,"
            "sample_rate,channels,channel_layout,duration"
        ),
        "-of",
        "json",
        str(media),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    probe = json.loads(result.stdout)
    write_json(out_dir / "ffprobe.json", probe)
    stream_types = {item.get("codec_type") for item in probe.get("streams", [])}
    if "video" not in stream_types:
        raise RuntimeError("downloaded artifact has no video stream")
    if require_audio and "audio" not in stream_types:
        raise RuntimeError("downloaded artifact has no audio stream")

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is not None:
        subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(media), "-f", "null", "-"],
            check=True,
        )
        write_text(out_dir / "ffmpeg-decode.txt", "ok\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Submit, poll, download, and validate an SGLang video Job."
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--prompt",
        default=(
            "A calm sunrise over a mountain lake, gentle water ripples, "
            "soft wind and distant birds, cinematic wide shot."
        ),
    )
    parser.add_argument("--task", default="t2va")
    parser.add_argument("--seconds", type=int, default=4)
    parser.add_argument("--short-edge", type=int, default=768)
    parser.add_argument("--aspect-ratio", default="16:9")
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--flow-shift", type=float, default=12.0)
    parser.add_argument("--audio-flow-shift", type=float, default=3.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--deadline-seconds", type=float, default=900.0)
    parser.add_argument("--output-name", default="video-smoke.mp4")
    parser.add_argument(
        "--bearer-token-env",
        help="Optional environment-variable name containing a bearer token.",
    )
    parser.add_argument("--require-audio", action="store_true")
    args = parser.parse_args()

    if args.seconds <= 0 or args.short_edge <= 0 or args.steps <= 0:
        parser.error("seconds, short-edge, and steps must be positive")
    if args.poll_seconds <= 0 or args.deadline_seconds <= 0:
        parser.error("poll-seconds and deadline-seconds must be positive")
    if Path(args.output_name).name != args.output_name:
        parser.error("output-name must be a filename, not a path")

    out_dir = args.out_dir
    if out_dir.exists() and any(out_dir.iterdir()):
        parser.error("out-dir must be empty; use a fresh evidence directory")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o700)

    headers: dict[str, str] = {}
    if args.bearer_token_env:
        token = os.environ.get(args.bearer_token_env)
        if not token:
            parser.error(f"environment variable {args.bearer_token_env!r} is unset")
        headers["Authorization"] = f"Bearer {token}"

    base_url = args.base_url.rstrip("/")
    payload = {
        "model": args.model,
        "prompt": args.prompt,
        "seconds": args.seconds,
        "task": args.task,
        "conditions": [],
        "target": {
            "short_edge": args.short_edge,
            "aspect_ratio": args.aspect_ratio,
            "duration_seconds": float(args.seconds),
        },
        "num_outputs_per_prompt": 1,
        "num_inference_steps": args.steps,
        "flow_shift": args.flow_shift,
        "audio_flow_shift": args.audio_flow_shift,
        "seed": args.seed,
    }
    write_json(out_dir / "request.json", payload)

    started = time.monotonic()
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        health = client.get(f"{base_url}/health", timeout=30)
        write_text(out_dir / "health.txt", f"status={health.status_code}\n{health.text}\n")
        health.raise_for_status()

        models = client.get(f"{base_url}/v1/models", timeout=30)
        request_json(models, out_dir / "models.json")

        created_response = client.post(
            f"{base_url}/v1/videos", json=payload, timeout=60
        )
        created = request_json(created_response, out_dir / "create-response.json")
        job_id = created.get("id")
        if not job_id:
            raise RuntimeError("video creation response contains no id")
        print(f"submitted id={job_id}", flush=True)

        deadline = time.monotonic() + args.deadline_seconds
        previous_status = None
        while time.monotonic() < deadline:
            status_response = client.get(
                f"{base_url}/v1/videos/{job_id}", timeout=30
            )
            job = request_json(status_response, out_dir / "job.json")
            status = job.get("status")
            if status != previous_status:
                print(
                    f"status={status} elapsed={time.monotonic() - started:.1f}s",
                    flush=True,
                )
                previous_status = status
            if status in {"completed", "succeeded"}:
                break
            if status in {"failed", "cancelled"}:
                raise RuntimeError(json.dumps(job, ensure_ascii=False))
            time.sleep(args.poll_seconds)
        else:
            raise TimeoutError(
                f"job {job_id} did not finish within {args.deadline_seconds:g} seconds"
            )

    media = out_dir / args.output_name
    partial = out_dir / f".{args.output_name}.part"
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        with client.stream(
            "GET", f"{base_url}/v1/videos/{job_id}/content", timeout=180
        ) as content:
            content.raise_for_status()
            with partial.open("wb") as output:
                for chunk in content.iter_bytes():
                    output.write(chunk)
    partial.replace(media)
    media.chmod(0o600)
    media_probe(media, out_dir, args.require_audio)

    elapsed = time.monotonic() - started
    digest = sha256_file(media)
    summary = {
        "job_id": job_id,
        "status": status,
        "elapsed_seconds": elapsed,
        "bytes": media.stat().st_size,
        "sha256": digest,
        "output": str(media),
    }
    write_json(out_dir / "summary.json", summary)
    print(
        f"completed elapsed={elapsed:.1f}s bytes={summary['bytes']} "
        f"sha256={digest} output={media}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
