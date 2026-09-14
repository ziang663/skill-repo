"""Experiment-local identity and guarded lifecycle; never touches online services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CAMPAIGN = ROOT.parent / 'five-model-cost-20260913'
TRIAL = ROOT.parent / 'glm53-nvfp4-kv-20260914'
RUNTIME = CAMPAIGN / 'runtimes/latest/runtime'
SOURCE = RUNTIME / 'sgl-workspace/sglang'
PYTHON = RUNTIME / 'opt/sglang/bin/python'
MODEL = 'glm53_nvfp4'
PORT = 30480
sys.path.insert(0, str(CAMPAIGN))
import local_campaign as lifecycle
sys.path.pop(0)

PROFILES = json.loads((ROOT / 'profiles.json').read_text())
lifecycle.ROOT = ROOT
lifecycle.PORT = PORT
lifecycle.PROFILES = PROFILES


def save(path, obj):
    lifecycle.save(path, obj)


def owned_record():
    record = json.loads((ROOT / 'active-engine.json').read_text())
    assert record['model'] == MODEL and record['port'] == PORT
    assert Path(record['run']).parent == ROOT / 'runs'
    pid = record['pid']
    assert lifecycle.process_start(pid) == record['start_ticks'], 'Engine generation changed'
    assert os.getpgid(pid) == pid
    assert ('FIVE_MODEL_COST_RUN=' + record['run']).encode() in Path(
        f'/proc/{pid}/environ').read_bytes().split(b'\0')
    return record


def preflight():
    """Parse both configurations in the pinned runtime without loading weights."""
    manifest = json.loads((TRIAL / 'download-manifest.json').read_text())
    verified = json.loads((TRIAL / 'download-verified.json').read_text())
    assert manifest['revision'] == verified['revision'] == '11af4cba759e6559eda70358a5778bd1bddddd78'
    model_path = Path(PROFILES[MODEL]['model_path'])
    for entry in manifest['files']:
        assert (model_path / entry['rfilename']).stat().st_size == entry['size']
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip()
    assert commit == '0bcd822377da7b5718e674eaf9c870d349424dd1'
    assert not subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=no'], cwd=SOURCE, text=True)
    env = lifecycle.environment()
    tf = RUNTIME / 'sgl-workspace/transformers/src'
    env.update(PATH=f'{RUNTIME}/opt/sglang/bin:/usr/local/cuda/bin:/usr/bin:/bin',
               PYTHONPATH=str(SOURCE / 'python') + (':' + str(tf) if tf.exists() else ''),
               SGLANG_CACHE_DIR=str(ROOT / 'kernel-cache/latest'))
    assert not any('SIMULATE' in key for key in env)
    result = {'utc': lifecycle.utc(), 'source_commit': commit,
              'weights_revision': verified['revision'], 'strategies': {},
              'profiles_sha256': hashlib.sha256((ROOT / 'profiles.json').read_bytes()).hexdigest()}
    code = '''import json,sys
from sglang.srt.server_args import prepare_server_args
a=prepare_server_args(json.loads(sys.argv[1]))
a.resolve_once()
a.check_server_args()
keys=['tp_size','dp_size','ep_size','enable_dp_attention','quantization','kv_cache_dtype','mem_fraction_static','moe_a2a_backend','moe_runner_backend','fp4_gemm_runner_backend','speculative_algorithm','speculative_num_steps','speculative_eagle_topk','speculative_num_draft_tokens','disable_shared_experts_fusion','chunked_prefill_size','max_running_requests']
r=a.resolved_dict()
print(json.dumps({k:r.get(k) for k in keys}))
'''
    for strategy in ('throughput', 'sla'):
        argv = ['--model-path', str(model_path), '--served-model-name', PROFILES[MODEL]['served_model'],
                *PROFILES[MODEL]['common'], *PROFILES[MODEL][strategy]]
        proc = subprocess.run([str(PYTHON), '-c', code, json.dumps(argv)], cwd=SOURCE,
                              env=env, capture_output=True, text=True, timeout=180)
        result['strategies'][strategy] = {'argv': argv, 'exit_code': proc.returncode,
                                         'stdout': proc.stdout, 'stderr': proc.stderr}
        save(ROOT / 'preflight.json', result)
        print(strategy, proc.stdout, proc.stderr, flush=True)
        assert proc.returncode == 0, f'{strategy} CLI preflight failed; do not launch'
    return result


def start(strategy, name):
    checked = json.loads((ROOT / 'preflight.json').read_text())
    assert checked['profiles_sha256'] == hashlib.sha256((ROOT / 'profiles.json').read_bytes()).hexdigest()
    assert all(row['exit_code'] == 0 for row in checked['strategies'].values())
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 30580))
    lifecycle.start(argparse.Namespace(model=MODEL, strategy=strategy, name=name,
        runtime=str(RUNTIME), source=None, python=None, extra_args=[]))


def status():
    record = owned_record()
    info = lifecycle.query('/server_info')
    save(Path(record['run']) / 'server-info.json', info)
    resolved = {**info.get('server_args', info), **(info.get('internal_states') or [{}])[0]}
    keys = ['tp_size','dp_size','ep_size','enable_dp_attention','max_total_num_tokens',
            'max_req_input_len','kv_cache_dtype','mem_fraction_static','max_running_requests',
            'speculative_algorithm','speculative_num_steps','speculative_num_draft_tokens',
            'moe_runner_backend','moe_a2a_backend','disable_shared_experts_fusion']
    print(json.dumps({k: resolved.get(k,info.get(k)) for k in keys}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['preflight','start','status','stop'])
    parser.add_argument('--strategy', choices=['throughput','sla'])
    parser.add_argument('--name')
    args = parser.parse_args()
    if args.action == 'preflight':
        preflight()
    elif args.action == 'start':
        assert args.strategy and args.name
        start(args.strategy, args.name)
    elif args.action == 'stop':
        assert args.name
        lifecycle.stop(argparse.Namespace(name=args.name))
    else:
        status()
