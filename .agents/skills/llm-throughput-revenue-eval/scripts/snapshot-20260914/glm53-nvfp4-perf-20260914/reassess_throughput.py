"""Apply user-authorized warning tolerance without rewriting original evidence."""
import hashlib
import json

from experiment import ROOT, lifecycle, save
from warning_policy import classify_log


def main():
    policy_path = ROOT / 'warning-policy-20260914.json'
    policy = json.loads(policy_path.read_text())
    assert policy['allocator_warning_action'] == 'record_only'
    point = ROOT / 'benchmarks' / 'throughput-tp8-dpa8-mem085-01-inf'
    paths = [point / name for name in ('summary.json', 'engine-error-scan.json', 'engine-identity.json')]
    summary, scan, identity = [json.loads(path.read_text()) for path in paths]
    classified = classify_log('\n'.join(scan['matches']))
    assert summary['failure_reasons'] == ['engine_runtime_errors']
    assert summary['requests'] == summary['success'] == 200
    assert abs(summary['observed_cache_rate'] - summary['target_cache_rate']) <= .005
    assert summary['health_after']['/health']['http'] == 200
    assert identity['same_engine_after']
    assert not classified['runtime_errors'] and len(classified['allocator_warnings']) == 1
    result = {'utc': lifecycle.utc(), 'point': point.name, 'status': 'PASS_WITH_WARNING',
              'original_status': summary['status'], 'original_failure_reasons': summary['failure_reasons'],
              'policy': policy_path.name, 'policy_sha256': hashlib.sha256(policy_path.read_bytes()).hexdigest(),
              'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
              'reason': '200/200 success, cache within tolerance, health 200, same engine; only recoverable allocator warning',
              'allocator_warning_count': 1, 'original_evidence_unchanged': True,
              'note': 'New user acceptance criterion; not a retest or proof of long-term stability'}
    target = ROOT / 'throughput-reassessment-20260914.json'
    assert not target.exists()
    save(target, result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
