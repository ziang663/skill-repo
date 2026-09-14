"""Passive local GPU/metrics sampling for an already-authorized model queue."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parent


def read(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', default='telemetry')
    parser.add_argument('--queue-name', default='resume-01-remaining')
    args = parser.parse_args()
    assert all(value.replace('-', '').isalnum() for value in (args.name, args.queue_name))
    OUT = ROOT / 'resume-01' / (args.name + '.jsonl')
    assert not OUT.exists()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with OUT.open('x') as out:
        print(json.dumps({'sampling': str(OUT), 'period_s': 10}), flush=True)
        while True:
            tick = time.monotonic()
            active = read(ROOT / 'active-engine.json')
            queue = read(ROOT / (args.queue_name + '-state.json'))
            row = {'utc': datetime.now(timezone.utc).isoformat(), 'engine': active, 'queue_status': queue.get('status')}
            try:
                row['gpu_csv'] = subprocess.check_output(['nvidia-smi', '--query-gpu=index,memory.used,utilization.gpu,power.draw', '--format=csv,noheader,nounits'], text=True, timeout=5).splitlines()
            except Exception as exc:
                row['gpu_error'] = repr(exc)
            try:
                with opener.open('http://127.0.0.1:30480/metrics', timeout=2) as response:
                    lines = response.read().decode().splitlines()
                row['metrics'] = [line for line in lines if not line.startswith('#') and any(key in line for key in ('num_running', 'num_queue', 'token_usage', 'num_used_tokens', 'gen_throughput', 'cache_hit_rate', 'spec_accept'))]
            except Exception as exc:
                row['metrics_error'] = repr(exc)
            out.write(json.dumps(row) + '\n')
            out.flush()
            if queue.get('status') in ('completed', 'needs_inspection', 'paused_by_user',
                                      'both_stages_completed', 'both_stages_completed_with_limitations'):
                break
            time.sleep(max(0, 10 - (time.monotonic() - tick)))
