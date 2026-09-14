"""Verify completed adaptive SLA results against every persisted request."""
import hashlib
import json
import math
from pathlib import Path

from experiment import ROOT, lifecycle, PROFILES, MODEL, save
from adaptive_sampling import early_decision
from report import revenue


def close(actual, expected):
    assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-6), (actual, expected)


def main():
    policy=json.loads((ROOT/'warning-policy-20260914.json').read_text())
    run=policy['run_name']
    state=json.loads((ROOT/(run+'-search.json')).read_text())
    controller=json.loads((ROOT/(run+'-controller.json')).read_text())
    assert state['status']=='bracketed' and controller['status']=='completed'
    profile=PROFILES[MODEL]
    points=[]
    hashes=set()
    for row in state['points']:
        point=ROOT/'benchmarks'/row['name']
        s=json.loads((point/'summary.json').read_text())
        requests=[json.loads(p.read_text()) for p in sorted((point/'requests').glob('*.json'))]
        n=s['requests']
        assert len(requests)==n==s['success']
        assert [r['id'] for r in requests]==list(range(n))
        assert all(r['success'] and r['http']==200 and r['input_tokens']==72125 and r['output_tokens']==1095 for r in requests)
        ti=sum(r['input_tokens'] for r in requests)
        tc=sum(r['cached_tokens'] for r in requests)
        to=sum(r['output_tokens'] for r in requests)
        for key,tokens in [('input_tpm',ti),('cached_input_tpm',tc),('uncached_input_tpm',ti-tc),('output_tpm',to),('total_tpm',ti+to)]:
            close(s[key],tokens*60/s['duration_s'])
        close(s['completed_rps'],n/s['duration_s'])
        close(s['observed_cache_rate'],tc/ti)
        close(s['ttft_s']['mean'],sum(r['ttft_s'] for r in requests)/n)
        close(s['tpot_ms']['mean'],sum(r['tpot_ms'] for r in requests)/n)
        assert abs(s['observed_cache_rate']-.94532)<=.005
        assert s['actual_offered_rps']>=float(s['request_rate'])*.95
        assert s['health_after']['/health']['http']==200
        identity=json.loads((point/'engine-identity.json').read_text())
        assert identity['same_engine_after'] and identity['before']['name']==run
        scan=json.loads((point/'engine-error-scan.json').read_text())
        assert not scan['runtime_errors']
        expected_reasons=[]
        if s['ttft_s']['mean']>profile['ttft_s']:
            expected_reasons.append('TTFT')
        if s['tpot_ms']['mean']>profile['tpot_ms']:
            expected_reasons.append('TPOT')
        assert s['failure_reasons']==expected_reasons
        assert s['status']==('FAIL' if expected_reasons else 'PASS')
        manifest=json.loads((point/'manifest.json').read_text())
        hashes.add(manifest['dataset_sha256'])
        sampling=s.get('adaptive_sampling')
        if sampling:
            assert sampling['submitted_requests']==n and sampling['all_inflight_drained']
            assert sampling['unsent_requests']==200-n
            decision=early_decision(requests,profile,.94532,float(s['request_rate']))
            assert decision and decision['eligible']==sampling['decision']['eligible']
            assert sampling['early_stopped']==decision['eligible']
            assert 100<=n<=200
        else:
            assert n==200 and s['request_rate']==.25
        points.append({'point':point.name,'target_rps':s['request_rate'],'requests':n,
                       'status':s['status'],'total_tpm':s['total_tpm'],
                       'input_tpm':s['input_tpm'],'cached_input_tpm':s['cached_input_tpm'],
                       'uncached_input_tpm':s['uncached_input_tpm'],'output_tpm':s['output_tpm'],
                       'ttft_s':s['ttft_s']['mean'],'tpot_ms':s['tpot_ms']['mean'],
                       'cache_rate':s['observed_cache_rate'],'completed_rps':s['completed_rps'],
                       'allocator_warnings':s['allocator_warning_count_this_point'],
                       'monthly_revenue_per_gpu_usd':revenue(s) if s['status']=='PASS' else None,
                       'summary_sha256':hashlib.sha256((point/'summary.json').read_bytes()).hexdigest()})
    assert len(hashes)==1
    passing=[p for p in points if p['status']=='PASS']
    best=max(passing,key=lambda p:p['total_tpm'])
    assert best['point']==state['best_measured_pass']['name']
    lower=state['passing_target_lower']
    upper=state['failing_target_upper']
    assert upper-lower<=max(.005,.1*lower)
    info=json.loads((ROOT/'runs'/run/'server-info.json').read_text())
    args={**info.get('server_args',info),**(info.get('internal_states') or [{}])[0]}
    result={'utc':lifecycle.utc(),'status':'verified','engine_run':run,'points':points,
            'completed_formal_requests':sum(p['requests'] for p in points),
            'point_count':len(points),'passing_points':len(passing),'failed_latency_points':len(points)-len(passing),
            'best':best,'target_rps_bracket':[lower,upper],
            'allocator_warning_count':sum(p['allocator_warnings'] for p in points),
            'request_failures':0,'crashes_or_restarts':0,
            'single_scheduler_kv_pool':args['max_total_num_tokens'],
            'max_req_input_len':args['max_req_input_len'],
            'same_dataset_sha256':next(iter(hashes)),
            'prices_usd_per_million':{'uncached_input':1.4,'cached_input':.26,'output':4.4},
            'gpus':8,'days_at_full_load':30,
            'notes':['Finite adaptive 100-200 request points, not steady-state/global maximum proof',
                     'All in-flight requests included; no repeated boundary confirmation',
                     'Allocator warnings accepted per user policy; no quality/1M request validation',
                     'Original throughput and old interrupted SLA evidence unchanged']}
    target=ROOT/'final-audit.json'
    assert not target.exists(), 'Do not overwrite a final audit'
    save(target,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
