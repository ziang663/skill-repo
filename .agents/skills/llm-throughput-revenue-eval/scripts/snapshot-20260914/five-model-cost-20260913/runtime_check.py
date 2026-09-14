"""Check extracted official imports and CLI flags without loading model weights."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from local_campaign import environment, PROFILES


def check(tag, model):
    base = ROOT/"runtimes"/tag
    assert (base/"complete.json").exists(), "Image extraction is not complete"
    image = json.loads((base/"complete.json").read_text())
    prior = [json.loads(p.read_text()) for p in base.glob("*-preflight.json")]
    cached = any(p.get("image", {}).get("digest") == image["digest"] and
                 p.get("imports_exit") == 0 and p.get("cli_exit") == 0 for p in prior)
    if cached and (base/"serve-help.txt").exists():
        help_text = (base/"serve-help.txt").read_text()
        profile = PROFILES[model]
        missing = [f for k in ("common", "throughput", "sla") for f in profile[k]
                   if f.startswith("--") and f not in help_text]
        assert not missing, missing
        record = {"utc": datetime.now(timezone.utc).isoformat(), "model": model, "tag": tag,
                  "imports_exit": 0, "cli_exit": 0, "missing_flags": [], "image": image,
                  "note": "Reused import/CLI evidence for the same immutable runtime; model flags checked. No GPU deployment proof."}
        (base/(model+"-preflight.json")).write_text(json.dumps(record, indent=2)+"\n")
        print(json.dumps(record), flush=True)
        return
    runtime = base/"runtime"
    source = runtime/"sgl-workspace/sglang"
    py = runtime/"opt/sglang/bin/python"
    tf = runtime/"sgl-workspace/transformers/src"
    env = environment()
    env.update(PATH=f"{runtime}/opt/sglang/bin:/usr/local/cuda/bin:/usr/bin:/bin",
               PYTHONPATH=str(source/"python") + (":"+str(tf) if tf.exists() else ""))
    code = """import json, importlib.metadata as m, sglang, torch, transformers
print(json.dumps({'sglang':getattr(sglang,'__version__',None),'sglang_file':sglang.__file__,
'torch':torch.__version__,'torch_cuda':torch.version.cuda,'transformers':transformers.__version__,
'transformers_file':transformers.__file__,'flashinfer':m.version('flashinfer-python')},indent=2))"""
    proc = subprocess.run([str(py), "-c", code], env=env, cwd=source, text=True, capture_output=True, timeout=120)
    (base/"imports.txt").write_text(proc.stdout+proc.stderr)
    print(proc.stdout+proc.stderr, flush=True)
    assert proc.returncode == 0, "Runtime imports failed"
    help_proc = subprocess.run([str(py), "-c", "from sglang.cli.main import main; main()", "serve", "--help"],
                               env=env, cwd=source, text=True, capture_output=True, timeout=120)
    (base/"serve-help.txt").write_text(help_proc.stdout+help_proc.stderr)
    assert help_proc.returncode == 0, (help_proc.stdout+help_proc.stderr)[-6000:]
    profile = PROFILES[model]
    flags = [x for k in ("common", "throughput", "sla") for x in profile[k] if x.startswith("--")]
    absent = [f for f in flags if f not in help_proc.stdout]
    record = {"utc": datetime.now(timezone.utc).isoformat(), "model": model, "tag": tag,
              "imports_exit": proc.returncode, "cli_exit": help_proc.returncode, "missing_flags": absent,
              "image": json.loads((base/"complete.json").read_text()),
              "note": "CPU-side import/CLI check only; no claim of model startup or CUDA kernel success"}
    (base/(model+"-preflight.json")).write_text(json.dumps(record, indent=2)+"\n")
    assert not absent, absent
    print(json.dumps(record), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("tag")
    p.add_argument("model", choices=PROFILES)
    args = p.parse_args()
    check(args.tag, args.model)
