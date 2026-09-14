"""Read-only compact status for supervising this local campaign."""
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent


def read(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    latest = {}
    for state in sorted((read(p) for p in ROOT.glob('*-model-state.json')),
                        key=lambda s: s.get('started_utc', '')):
        if state:
            latest[state['model']] = state
    result = {'utc': datetime.now(timezone.utc).isoformat(), 'models': {}}
    for model, state in latest.items():
        stage = state.get('active_stage', '')
        search = read(ROOT/(stage+'-search.json'))
        if state['status'] in ('both_stages_completed', 'both_stages_completed_with_limitations'):
            result['models'][model] = {'status': state['status'],
                                      'limitations': state.get('limitations', []),
                                      'best_measured_pass': search.get('best_measured_pass')}
            continue
        name = search.get('current_point', {}).get('name', stage+'-inf')
        point = ROOT/'benchmarks'/name
        info = {'status': state['status'], 'stage': stage, 'point': name,
                'progress': read(point/'progress.json')}
        if not point.exists():
            info['point'] = None
            info['progress'] = {'phase': 'engine_startup_or_preparation', 'formal_requests_sent': 0}
        if state.get('error'):
            info['error'] = state['error']
        if search:
            info['search_status'] = search['status']
            info['completed_point_count'] = len(search['points'])
            info['last_completed_point'] = search['points'][-1] if search['points'] else None
            info['best_measured_pass'] = search.get('best_measured_pass')
        if info['progress'].get('phase') == 'formal':
            rows = [read(p) for p in (point/'requests').glob('*.json')]
            good = [r for r in rows if r.get('success')]
            if good:
                info['partial_only'] = {
                    'completed': len(rows), 'success': len(good),
                    'ttft_s_mean': statistics.mean(r['ttft_s'] for r in good),
                    'tpot_ms_mean': statistics.mean(r['tpot_ms'] for r in good),
                    'cache_rate': sum(r['cached_tokens'] for r in good)/sum(r['input_tokens'] for r in good)}
        result['models'][model] = info
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
