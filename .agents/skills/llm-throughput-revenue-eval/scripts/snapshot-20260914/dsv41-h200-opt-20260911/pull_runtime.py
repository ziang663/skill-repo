"""Extract an image-pinned Python runtime locally; never run container hooks."""
from __future__ import annotations

import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import time

import requests

ROOT = Path(__file__).resolve().parent
REGISTRY = "https://registry-us-east.scitix.ai"
REPO = "simaas/sglang"
DIGEST = "sha256:b1b96cec3331b75ef92044307f6f350adaa6def8ddada4f420878a5aca368528"
RUNTIME = ROOT / "runtime"
BLOBS = ROOT / "blobs"
PREFIXES = ("opt/sglang/", "sgl-workspace/", "opt/image-factory/")


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def api_session():
    session = requests.Session()
    response = session.get(
        REGISTRY + "/service/token",
        params={"service": "harbor-registry", "scope": f"repository:{REPO}:pull"},
        timeout=30,
    )
    response.raise_for_status()
    token = response.json().get("token") or response.json()["access_token"]
    session.headers["Authorization"] = "Bearer " + token
    return session


def fetch_json(session, kind, digest):
    response = session.get(
        f"{REGISTRY}/v2/{REPO}/{kind}/{digest}",
        headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
        timeout=60,
    )
    response.raise_for_status()
    assert "sha256:" + hashlib.sha256(response.content).hexdigest() == digest
    return response.json()


def download(item):
    index, layer = item
    digest = layer["digest"]
    path = BLOBS / (digest.split(":")[1] + ".tar.gz")
    marker = path.with_suffix(".verified.json")
    if marker.exists() and path.stat().st_size == layer["size"]:
        return index, layer, path
    session = api_session()
    response = session.get(f"{REGISTRY}/v2/{REPO}/blobs/{digest}", stream=True, timeout=(30, 180))
    response.raise_for_status()
    partial = path.with_suffix(".partial")
    hasher, received, start, last_log = hashlib.sha256(), 0, time.monotonic(), 0
    with partial.open("wb") as output:
        for data in response.iter_content(4 * 1024 * 1024):
            output.write(data)
            hasher.update(data)
            received += len(data)
            now = time.monotonic()
            if now - last_log > 20:
                print(f"download layer={index} {received / 2**30:.2f}/{layer['size'] / 2**30:.2f} GiB", flush=True)
                last_log = now
    assert received == layer["size"]
    assert "sha256:" + hasher.hexdigest() == digest
    partial.replace(path)
    save(marker, {"digest": digest, "bytes": received, "seconds": time.monotonic() - start})
    print(f"verified layer={index} bytes={received}", flush=True)
    return index, layer, path


def archive_name(name):
    name = name.removeprefix("./")
    assert not name.startswith("/") and ".." not in PurePosixPath(name).parts, name
    return name


def retain_existing(target, index):
    if target.exists() or target.is_symlink():
        relative = target.relative_to(RUNTIME)
        backup = ROOT / "layer-replaced-backups" / str(index) / relative
        assert not backup.exists() and not backup.is_symlink(), str(backup)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(backup))


def extract(index, layer, path):
    marker = ROOT / f"extracted-{index:02d}.json"
    if marker.exists():
        assert json.loads(marker.read_text())["digest"] == layer["digest"]
        return
    count, total = 0, 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = archive_name(member.name)
            if not any(name.startswith(prefix) for prefix in PREFIXES):
                continue
            # Keep the fresh local venv interpreter/config, not absolute image symlinks.
            if name in ("opt/sglang/pyvenv.cfg", "opt/sglang/lib64") or name.startswith("opt/sglang/bin/python"):
                continue
            target = RUNTIME / name
            assert target.parent.resolve().is_relative_to(RUNTIME.resolve()), name
            if target.name == ".wh..wh..opq":
                if target.parent.exists():
                    for child in target.parent.iterdir():
                        retain_existing(child, index)
                continue
            if target.name.startswith(".wh."):
                retain_existing(target.with_name(target.name[4:]), index)
                continue
            member.name = name
            if member.issym() and member.linkname.startswith("/"):
                link = member.linkname.lstrip("/")
                if any(link.startswith(prefix) for prefix in PREFIXES):
                    member.linkname = os.path.relpath(RUNTIME / link, target.parent)
                else:
                    raise RuntimeError(f"Unmapped external image symlink: {name}")
            if member.islnk():
                member.linkname = archive_name(member.linkname)
            if not member.isdir() and (target.exists() or target.is_symlink()):
                retain_existing(target, index)
            archive.extract(member, path=RUNTIME, filter="data")
            count += 1
            total += member.size
    save(marker, {"index": index, "digest": layer["digest"], "files": count, "bytes": total})
    print(f"extracted layer={index} files={count} GiB={total / 2**30:.2f}", flush=True)


def main():
    BLOBS.mkdir(exist_ok=True)
    RUNTIME.mkdir(exist_ok=True)
    with (ROOT / "runtime.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        session = api_session()
        manifest = fetch_json(session, "manifests", DIGEST)
        config = fetch_json(session, "blobs", manifest["config"]["digest"])
        assert config["os"] == "linux" and config["architecture"] == "amd64"
        save(ROOT / "image-manifest.json", manifest)
        # Only safe runtime metadata, not image command history or credentials.
        env = dict(value.split("=", 1) for value in config["config"]["Env"])
        save(ROOT / "image-runtime-metadata.json", {
            "digest": DIGEST,
            "env": {k: v for k, v in env.items() if k in ("CUDA_HOME", "CUDA_VERSION", "SGLANG_RUST_BUILD_MODE", "SGLANG_BUILD_COMMIT")},
            "architecture": config["architecture"],
            "note": "Only Python/source extracted; host CUDA and OS libraries retained.",
        })
        history = [entry for entry in config["history"] if not entry.get("empty_layer")]
        assert len(history) == len(manifest["layers"])
        assert "COPY /opt/sglang/lib/python3.12/site-packages" in history[19]["created_by"]
        if not (RUNTIME / "opt/sglang/pyvenv.cfg").exists():
            subprocess.run(["/usr/bin/python3", "-m", "venv", "--without-pip", str(RUNTIME / "opt/sglang")], check=True)
        selected = list(enumerate(manifest["layers"]))[19:]
        print(f"Pull {len(selected)} layers, {sum(x['size'] for _, x in selected) / 2**30:.2f} GiB compressed", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(download, item) for item in selected]
            # Apply in image layer order, including image whiteouts.
            for future in futures:
                extract(*future.result())
        save(ROOT / "runtime-extracted.json", {"digest": DIGEST, "source_commit": env["SGLANG_BUILD_COMMIT"], "status": "extracted; imports not yet tested"})
        print("Runtime extraction complete", flush=True)


if __name__ == "__main__":
    main()
