"""Resolve public Docker Hub image, or extract its Python/source to task storage.

No container entrypoint is executed; host libraries remain a documented deviation.
"""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import requests

ROOT = Path(__file__).resolve().parent
REGISTRY = "https://registry-1.docker.io"
REPO = "lmsysorg/sglang"


def session():
    s = requests.Session()
    r = s.get("https://auth.docker.io/token", params={"service": "registry.docker.io", "scope": f"repository:{REPO}:pull"}, timeout=30)
    r.raise_for_status()
    s.headers["Authorization"] = "Bearer " + r.json()["token"]
    return s


def fetch(s, kind, ref):
    r = s.get(f"{REGISTRY}/v2/{REPO}/{kind}/{ref}", headers={"Accept": ",".join([
        "application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"])}, timeout=60)
    r.raise_for_status()
    digest = "sha256:" + hashlib.sha256(r.content).hexdigest()
    if ref.startswith("sha256:"):
        assert ref == digest
    return r.json(), digest


def inspect(tag):
    out = ROOT / "runtimes" / tag
    out.mkdir(parents=True, exist_ok=True)
    s = session()
    doc, top = fetch(s, "manifests", tag)
    if "manifests" in doc:
        ref = next(m["digest"] for m in doc["manifests"] if m.get("platform", {}).get("architecture") == "amd64" and m["platform"].get("os") == "linux")
        doc, digest = fetch(s, "manifests", ref)
    else:
        digest = top
    cfg, _ = fetch(s, "blobs", doc["config"]["digest"])
    history = [h for h in cfg["history"] if not h.get("empty_layer")]
    assert len(history) == len(doc["layers"])
    env = dict(v.split("=", 1) for v in cfg["config"].get("Env", []))
    metadata = {"tag": f"{REPO}:{tag}", "top_digest": top, "amd64_digest": digest,
                "os": cfg["os"], "architecture": cfg["architecture"],
                "env": {k:v for k,v in env.items() if k in ("PATH", "VIRTUAL_ENV", "PYTHONPATH", "CUDA_VERSION", "LD_LIBRARY_PATH", "SGLANG_BUILD_COMMIT")},
                "layers": [{"index": i, "digest": l["digest"], "size": l["size"], "created_by": h.get("created_by", "")}
                           for i, (l,h) in enumerate(zip(doc["layers"], history))]}
    for name, val in (("manifest.json", doc), ("metadata.json", metadata)):
        path = out/name
        if path.exists():
            assert json.loads(path.read_text()) == val, "Mutable tag changed; do not overwrite prior evidence"
        else:
            path.write_text(json.dumps(val, indent=2)+"\n")
    print(json.dumps({k:v for k,v in metadata.items() if k != "layers"}, indent=2), flush=True)
    return out, doc, metadata


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("tag")
    p.add_argument("--extract-from", type=int)
    args = p.parse_args()
    out, manifest, meta = inspect(args.tag)
    if args.extract_from is not None:
        helper = ROOT.parent / "dsv41-h200-opt-20260911/pull_runtime.py"
        spec = importlib.util.spec_from_file_location("extract_helper", helper)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.ROOT = out
        mod.RUNTIME = out/"runtime"
        mod.BLOBS = out/"blobs"
        mod.REGISTRY = REGISTRY
        mod.REPO = REPO
        mod.api_session = session
        mod.BLOBS.mkdir(exist_ok=True)
        mod.RUNTIME.mkdir(exist_ok=True)
        assert any("opt/sglang" in h["created_by"] for h in meta["layers"]), "Inspect image layout before extracting"
        if not (mod.RUNTIME/"opt/sglang/pyvenv.cfg").exists():
            subprocess.run(["/usr/bin/python3", "-m", "venv", "--without-pip", str(mod.RUNTIME/"opt/sglang")], check=True)
        selected = list(enumerate(manifest["layers"]))[args.extract_from:]
        print(f"Selected {len(selected)} layers, compressed {sum(l['size'] for _,l in selected)/2**30:.2f} GiB", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(mod.download, item) for item in selected]
            for job in jobs:
                mod.extract(*job.result())
        (out/"complete.json").write_text(json.dumps({"status": "extracted_not_yet_import_tested", "digest": meta["amd64_digest"]})+"\n")
