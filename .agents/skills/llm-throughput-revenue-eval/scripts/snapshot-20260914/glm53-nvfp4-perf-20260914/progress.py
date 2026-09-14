"""Read-only concise monitoring of the approved local SLA job."""
import json
import subprocess

from experiment import ROOT, lifecycle
from warning_policy import classify_log


def main():
    policy = json.loads((ROOT / 'warning-policy-20260914.json').read_text())
    name = policy['run_name']
    run = ROOT / 'runs' / name
    proc = json.loads((run / 'process.json').read_text())
    controller = json.loads((ROOT / (name + '-controller.json')).read_text())
    result = {'utc': lifecycle.utc(), 'run': name,
              'same_engine': lifecycle.process_start(proc['pid']) == proc['start_ticks'],
              'controller_status': controller['status']}
    search_path = ROOT / (name + '-search.json')
    if search_path.exists():
        search = json.loads(search_path.read_text())
        result['search_status'] = search['status']
        result['completed_points'] = search['points']
        if search.get('current_point'):
            point = ROOT / 'benchmarks' / search['current_point']['name']
            result['current_point'] = search['current_point']
            if (point / 'progress.json').exists():
                result['point_progress'] = json.loads((point / 'progress.json').read_text())
            rows = [json.loads(p.read_text()) for p in sorted((point / 'requests').glob('*.json'))]
            if rows:
                good = [r for r in rows if r.get('success')]
                result['partial_observation_not_sla_result'] = {
                    'persisted': len(rows), 'success': len(good),
                    'mean_ttft_s': sum(r['ttft_s'] for r in good) / len(good) if good else None,
                    'mean_tpot_ms': sum(r['tpot_ms'] for r in good) / len(good) if good else None}
    log = (run / 'engine.log').read_text(errors='replace')
    scan = classify_log(log)
    result['engine_total_allocator_warnings'] = len(scan['allocator_warnings'])
    result['engine_runtime_errors'] = scan['runtime_errors'][-5:]
    result['log_tail'] = [line[:350] for line in log.replace('\r', '\n').splitlines()[-3:]]
    result['gpu'] = subprocess.check_output(['nvidia-smi', '--query-gpu=index,memory.used,utilization.gpu',
                                            '--format=csv,noheader,nounits'], text=True).strip().splitlines()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
