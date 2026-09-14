"""Cross-check completed formal evidence without changing any raw measurements."""
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent


def metric(path, name, labels=None):
    values = []
    for line in path.read_text().splitlines():
        if not line.startswith(name+'{'):
            continue
        tags, value = line.rsplit('}', 1)
        if labels and not all(f'{k}="{v}"' in tags for k, v in labels.items()):
            continue
        values.append(float(value.split()[0]))
    return sum(values) if values else None


def prefill_cached(path):
    values = [metric(path, 'sglang:prefill_effective_tokens_total', {'mode': mode})
              for mode in ('device_hit', 'host_hit', 'storage_hit')]
    return sum(values) if all(v is not None for v in values) else None


def audit():
    results = []
    for path in sorted((ROOT/'benchmarks').glob('*/summary.json')):
        s = json.loads(path.read_text())
        if s['requests'] != 200:
            continue
        point = path.parent
        rows = [json.loads(p.read_text()) for p in sorted((point/'requests').glob('*.json'))]
        good = [r for r in rows if r.get('success')]
        manifest = json.loads((point/'manifest.json').read_text())
        totals = {'input': sum(r['input_tokens'] for r in good),
                  'output': sum(r['output_tokens'] for r in good),
                  'cached': sum(r['cached_tokens'] for r in good)}
        errors, warnings, counters = [], [], {}
        if len(rows) != 200 or len(good) != s['success']:
            errors.append('request_count_mismatch')
        if any(r['input_tokens'] != manifest['input_tokens'] or
               r['output_tokens'] != manifest['output_tokens'] for r in good):
            errors.append('token_length_mismatch')
        specs = [('input', 'sglang:prompt_tokens_total', {'is_streaming': 'true'}),
                 ('output', 'sglang:generation_tokens_total', {'is_streaming': 'true'}),
                 ('cached', 'sglang:cached_tokens_total', None)]
        for field, name, labels in specs:
            before = metric(point/'metrics-before.txt', name, labels)
            after = metric(point/'metrics-after.txt', name, labels)
            source = name
            if field == 'cached' and (before is None or after is None):
                # A fresh tokenizer counter has no labelled series before its
                # first hit. Do not infer zero: use explicitly initialized
                # scheduler cache counters present in both saved snapshots.
                before = prefill_cached(point/'metrics-before.txt')
                after = prefill_cached(point/'metrics-after.txt')
                source = 'sglang:prefill_effective_tokens_total cache modes'
            delta = after-before if before is not None and after is not None else None
            counters[field] = {'request_sum': totals[field], 'server_counter_delta': delta, 'source': source}
            if delta is None:
                warnings.append(field+'_counter_unavailable')
            elif delta != totals[field]:
                errors.append(field+'_counter_mismatch')
        derived = {'input_tpm': totals['input']*60/s['duration_s'],
                   'output_tpm': totals['output']*60/s['duration_s'],
                   'cached_input_tpm': totals['cached']*60/s['duration_s'],
                   'uncached_input_tpm': (totals['input']-totals['cached'])*60/s['duration_s'],
                   'total_tpm': (totals['input']+totals['output'])*60/s['duration_s']}
        for field, value in derived.items():
            if not math.isclose(value, s[field], rel_tol=1e-12, abs_tol=1e-9):
                errors.append(field+'_arithmetic_mismatch')
        if good:
            for field in ('ttft_s', 'tpot_ms'):
                if not math.isclose(statistics.mean(r[field] for r in good), s[field]['mean'],
                                    rel_tol=1e-12, abs_tol=1e-9):
                    errors.append(field+'_mean_mismatch')
        results.append({'point': point.name, 'model': s['model'],
                        'status': 'FAIL' if errors else ('WARN' if warnings else 'PASS'),
                        'errors': errors, 'warnings': warnings, 'totals': totals,
                        'counters': counters, 'dataset_sha256': manifest['dataset_sha256']})
    (ROOT/'accounting-audit.json').write_text(json.dumps(results, indent=2)+'\n')
    lines = ['# 计量交叉核对', '',
             '只核对已完成的200条正式点，不改原始判定。服务端计数取正式窗口前后差值；输入/输出限定streaming，避免混入健康探测。', '',
             '| 点 | 计量核对 | 问题 |', '|---|---|---|']
    for r in results:
        lines.append(f"| {r['point']} | {r['status']} | {', '.join(r['errors']+r['warnings']) or '请求合计、服务端计数、TPM及延迟均值一致'} |")
    lines += ['', '原始服务端计数、逐请求合计和数据哈希见 [accounting-audit.json](accounting-audit.json)。', '']
    (ROOT/'ACCOUNTING-AUDIT.md').write_text('\n'.join(lines))
    print(json.dumps({'points': len(results),
                      'statuses': {k:sum(r['status']==k for r in results) for k in ('PASS','WARN','FAIL')},
                      'issues': [r for r in results if r['status'] != 'PASS']}))


if __name__ == '__main__':
    audit()
