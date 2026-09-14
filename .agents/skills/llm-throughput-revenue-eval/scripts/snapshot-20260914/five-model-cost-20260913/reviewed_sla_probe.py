"""One explicit, reviewed lower-rate SLA probe on the same owned local engine.

No automatic retries, configuration changes or mutation of original evidence.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path

from conduct import point
from local_campaign import process_start, query
from report_results import main as update_report

ROOT = Path(__file__).resolve().parent


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def run(args):
    review = json.loads((ROOT / 'v4pro-sla-resource-review.json').read_text())
    active = json.loads((ROOT / 'active-engine.json').read_text())
    assert review['evidence_unchanged'] and review['diagnosis']
    assert active['name'] == review['engine_run'] and active['strategy'] == 'sla'
    assert active['pid'] == review['engine_identity_verified']['pid']
    assert active['start_ticks'] == review['engine_identity_verified']['start_ticks']
    assert process_start(active['pid']) == active['start_ticks']
    assert os.getpgid(active['pid']) == active['pid']
    assert ('FIVE_MODEL_COST_RUN=' + active['run']).encode() in Path(
        f'/proc/{active["pid"]}/environ').read_bytes().split(b'\0')
    query('/get_server_info')
    search_path = ROOT / 'v4pro-resume-13-sla-search.json'
    model_path = ROOT / 'v4pro-resume-13-model-state.json'
    if search_path.exists():
        state = json.loads(search_path.read_text())
        model = json.loads(model_path.read_text())
        assert state['status'] == 'awaiting_reviewed_probe'
    else:
        prior = json.loads((ROOT / review['prior_search']).read_text())
        assert prior['engine_run'] == active['name']
        state = {**prior, 'status': 'awaiting_reviewed_probe',
                 'mode': 'manual_bounded_refinement_after_cache_review',
                 'prior_search_evidence': review['prior_search']}
        state.pop('stop_reasons', None)
        model = {'model': 'v4pro', 'tag': 'latest', 'status': 'benchmarking',
                 'started_utc': datetime.now(timezone.utc).isoformat(),
                 'active_stage': 'v4pro-resume-13-sla', 'engine_run': active['name'],
                 'stages': ['v4pro-resume-03-throughput', active['name']],
                 'limitations': ['throughput_cache_target_not_met; raw FAIL retained'],
                 'mode': 'manual_reviewed_probes; no background model queue'}
    summaries = [json.loads((ROOT/'benchmarks'/p['name']/'summary.json').read_text()) for p in state['points']]
    for summary in summaries:
        assert summary['engine_run'] == active['name']
        assert summary['requests'] == summary['success'] == 200
        assert summary['health_after']['/health']['http'] == 200
        assert set(summary['failure_reasons']) <= {'cache_rate_mismatch', 'TTFT', 'TPOT'}
        if 'cache_rate_mismatch' in summary['failure_reasons']:
            name = next(p['name'] for p in state['points'] if p['rate'] == summary['request_rate'])
            assert name in review['reviewed_cache_failure_points'], 'Review every cache failure before continuing'
    passing = [p for p in state['points'] if p['status'] == 'PASS']
    failing = [p for p in state['points'] if p['status'] == 'FAIL']
    low = max(p['rate'] for p in passing)
    upper = min(failing, key=lambda p: p['rate'])
    state['passing_target_lower'] = low
    state['unusable_target_upper'] = upper['rate']
    state['unusable_upper_reasons'] = upper['failure_reasons']
    state['failing_target_upper'] = (upper['rate'] if set(upper['failure_reasons']) <= {'TTFT','TPOT'} else None)
    state['best_measured_pass'] = max(passing, key=lambda p: p['total_tpm'])
    state['resource_review'] = review
    if args.finish:
        assert upper['rate'] - low <= max(.005, .1 * low) or len(state['points']) >= 12
        state['status'] = ('bracketed' if state['failing_target_upper'] is not None else 'resource_limited_bracket')
        state['note'] = 'Finite 200-request points. Original cache-invalid points retained; no repeat confirmation or steady-state proof.'
        model['status'] = 'both_stages_completed_with_limitations'
    else:
        assert args.rate is not None and low < args.rate < upper['rate'] and len(state['points']) < 12
        name = f'v4pro-resume-13-sla-p{len(state["points"])+1:02d}-r{args.rate:.6f}'
        state.update(status='running', current_point={'name': name, 'rate': args.rate})
        save(search_path, state)
        save(model_path, model)
        try:
            summary = point('v4pro', 'sla', args.rate, name)
            state['points'].append({'name': name, 'rate': args.rate, 'status': summary['status'],
                'failure_reasons': summary['failure_reasons'], 'completed_rps': summary['completed_rps'],
                'total_tpm': summary['total_tpm'], 'mean_ttft_s': summary['ttft_s']['mean'],
                'mean_tpot_ms': summary['tpot_ms']['mean']})
            state['status'] = 'awaiting_reviewed_probe'
        except Exception as exc:
            state.update(status='interrupted_or_error', error=repr(exc))
            model.update(status='needs_inspection', error=repr(exc))
            raise
        finally:
            save(search_path, state)
            save(model_path, model)
            update_report()
    save(search_path, state)
    save(model_path, model)
    update_report()
    print(json.dumps(state, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--rate', type=float)
    group.add_argument('--finish', action='store_true')
    args = parser.parse_args()
    with ExitStack() as stack:
        for filename in ('model-controller.lock', 'controller.lock'):
            handle = stack.enter_context((ROOT / filename).open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(args)
