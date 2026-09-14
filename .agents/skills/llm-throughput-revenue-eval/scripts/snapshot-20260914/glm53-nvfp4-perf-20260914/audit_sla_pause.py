"""Preserve the manually interrupted SLA point without inventing a summary."""
import json
import re
import subprocess
import urllib.request

from experiment import ROOT, lifecycle, owned_record, save
from engine_lifecycle import live_group_pids


def main():
    active = owned_record()
    assert active['name'] == 'sla-tp8-mtp5-mem085-01'
    job = json.loads((ROOT / 'jobs' / active['name'] / 'process.json').read_text())
    assert not live_group_pids(job['pgid']), 'Controller must be stopped first'
    point = ROOT / 'benchmarks' / (active['name'] + '-p01-r0.250000')
    assert not (point / 'summary.json').exists()
    assert not (ROOT / 'sla-review.json').exists()
    info = lifecycle.query('/server_info')
    save(ROOT / 'runs' / active['name'] / 'server-info.json', info)
    args = {**info.get('server_args', info), **(info.get('internal_states') or [{}])[0]}
    log = (ROOT / 'runs' / active['name'] / 'engine.log').read_text(errors='replace')
    warnings = [line for line in log.splitlines() if 'memory allocation failed with OOM' in line]
    fatal = [line for line in log.splitlines() if re.search(
        r'OutOfMemoryError|CUDA out of memory|Scheduler hit an exception|Traceback \(most recent call last\)', line)]
    rows = [json.loads(p.read_text()) for p in sorted((point / 'requests').glob('*.json'))]
    with urllib.request.urlopen('http://127.0.0.1:30480/health', timeout=5) as response:
        health = response.status
    record = {
        'utc': lifecycle.utc(), 'status': 'paused_for_review',
        'reason': 'Allocator OOM warnings during preseed; manually stopped controller before completing point',
        'active_engine': active, 'controller': job,
        'controller_live_pids': live_group_pids(job['pgid']),
        'point': point.name, 'target_rps': 0.25, 'planned_requests': 200,
        'persisted_request_results': len(rows),
        'persisted_successes': sum(bool(row['success']) for row in rows),
        'persisted_request_ids': [row['id'] for row in rows],
        'in_flight_request_evidence': 'Engine log records rid suffix -4 after client interruption; no complete client result saved for this request',
        'preseed': json.loads((point / 'cache-preseed.json').read_text()),
        'oom_warnings': warnings, 'oom_warning_count': len(warnings),
        'fatal_matches_before_operator_shutdown': fatal,
        'same_engine_before_operator_shutdown': True, 'health_before_operator_shutdown': health,
        'single_scheduler_kv_pool': args['max_total_num_tokens'],
        'model_context': args.get('context_length'),
        'max_req_input_len': args['max_req_input_len'],
        'pool_at_least_1m': args['max_total_num_tokens'] >= 1048576,
        'gpu_before_operator_shutdown': subprocess.check_output([
            'nvidia-smi', '--query-gpu=index,memory.used,memory.total,utilization.gpu',
            '--format=csv,noheader,nounits'], text=True),
        'tpm_and_revenue': None,
        'measurement_note': 'Incomplete point; no valid SLA capacity or revenue. No aggregation of partial successes into a 200-request result.',
        'state_note': 'Original search JSON says running because SIGINT interrupted core; controller needs_review and this pause record supersede that stale status.',
        'changes': 'No engine source, deployment parameters, SLA thresholds, or online services changed.'
    }
    save(ROOT / 'sla-review.json', record)
    save(point / 'interruption.json', record)
    print(json.dumps({k: record[k] for k in ('status', 'persisted_successes', 'oom_warning_count',
                     'health_before_operator_shutdown', 'single_scheduler_kv_pool', 'max_req_input_len')}, indent=2))


if __name__ == '__main__':
    main()
