"""Audited local SLA measurement using SGLang's native client and metrics.

Defaults are the V4 Flash 0731 reproduction on this workstation. No requests are
sent without --execute. Never starts, stops, or reconfigures an engine. Legacy
evidence/snapshots are read-only. Runtime source is never edited: AST insertion
adds passive observations to the native request function in this process only.
"""
import argparse
import ast
import asyncio
from datetime import datetime, timezone
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import pickle
import statistics
import sys
import textwrap
import time
from urllib.parse import urlparse
import uuid


DEFAULT_RUNTIME = '/volume/dev/alan/deployments/five-model-cost-20260913/runtimes/latest/runtime'
DEFAULT_REFERENCE = '/volume/dev/alan/deployments/five-model-cost-20260913/benchmarks/v4flash-resume-02-sla-p07-r2.500000'
GSP_HASH = 'a11ce2533a39817c1a2c3e3b205470e747c6bc232951d1306c45688eb6f7d509'
VERSION = 'native-sla-v2-visible-text-20260914'


def engine_identity(base_url):
    import psutil
    port = urlparse(base_url).port or 80
    pids = {c.pid for c in psutil.net_connections(kind='tcp')
            if c.status == psutil.CONN_LISTEN and c.laddr.port == port and c.pid}
    if len(pids) != 1:
        raise RuntimeError('Cannot uniquely identify the local listening engine')
    process = psutil.Process(pids.pop())
    return {'pid': process.pid, 'create_time': process.create_time()}


def save(path, value):
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


class TimingObserver:
    def __init__(self, index, started):
        self.index = index
        self.started = started
        self.first_token = None
        self.last_token = None
        self.first_visible = None
        self.first_visible_count = None
        self.count = 0
        self.frames = []
        self.first_frames = []
        self.meta = {}

    def feed(self, data, elapsed):
        meta = data.get('meta_info') or {}
        count = int(meta.get('completion_tokens', 0))
        text = data.get('text') or ''
        if count > self.count:
            if self.first_token is None:
                self.first_token = elapsed
            self.last_token = elapsed
            self.count = count
        if text and self.first_visible is None:
            self.first_visible = elapsed
            self.first_visible_count = count
        self.frames.append([elapsed, count, len(text)])
        if len(self.first_frames) < 4:
            self.first_frames.append({'elapsed_s': elapsed, 'completion_tokens': count, 'text': text})
        self.meta = meta

    def finish(self, output):
        old_tpot = ((self.last_token - self.first_token) * 1000 / (self.count - 1)
                    if self.count > 1 and self.first_token is not None else None)
        self.result = {
            'index': self.index, 'start_clock': self.started,
            'success': output.success, 'error': output.error,
            'input_tokens': output.prompt_len, 'output_tokens': output.output_len,
            'cached_tokens': output.cached_tokens,
            'ttft_s': output.ttft,
            'tpot_ms': (output.latency - output.ttft) * 1000 / (output.output_len - 1)
                       if output.output_len > 1 else None,
            'e2e_s': output.latency,
            'legacy_first_token_ttft_s': self.first_token,
            'legacy_token_to_token_tpot_ms': old_tpot,
            'first_visible_completion_count': self.first_visible_count,
            'visible_after_first_token_s': output.ttft - self.first_token
                                          if self.first_token is not None else None,
            'frames_elapsed_count_text_chars': self.frames,
            'first_frames': self.first_frames,
            'server_timing': {k: self.meta[k] for k in (
                'request_received_ts', 'response_sent_to_client_ts', 'forward_entry_time',
                'prefill_finished_time', 'queue_time', 'spec_accept_length',
            ) if k in self.meta},
        }


def instrument_native(serving, observers):
    """Keep ALL native request/TTFT code; insert three observation statements."""
    source = textwrap.dedent(inspect.getsource(serving.async_request_sglang_generate))
    tree = ast.parse(source)

    class AddObservations(ast.NodeTransformer):
        begin = feed = end = 0

        def visit_Assign(self, node):
            self.generic_visit(node)
            if ast.unparse(node) == 'output.start_time = st':
                self.begin += 1
                return [node, ast.parse('_observer = _sla_begin(st)').body[0]]
            if ast.unparse(node) == 'data = orjson.loads(sse_data)':
                self.feed += 1
                return [node, ast.parse('_observer.feed(data, latency)').body[0]]
            return node

        def visit_Return(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == 'output':
                self.end += 1
                return [ast.parse('_observer.finish(output)').body[0], node]
            return node

    transform = AddObservations()
    tree = ast.fix_missing_locations(transform.visit(tree))
    if (transform.begin, transform.feed, transform.end) != (1, 1, 1):
        raise RuntimeError('Native source changed: observation anchors not unique; refusing to run')

    def begin(started):
        observer = TimingObserver(len(observers), started)
        observers.append(observer)
        return observer

    namespace = dict(vars(serving), _sla_begin=begin)
    exec(compile(tree, '<native-sla-passive-observation>', 'exec'), namespace)
    function = namespace['async_request_sglang_generate']
    return function, hashlib.sha256(source.encode()).hexdigest()


def validate_prefixes(token_rows, seed_ids, expected, page=256):
    if len(token_rows) != len(expected) or not token_rows:
        raise ValueError('Request/prefix count mismatch')
    seen = set()
    for row, wanted in zip(token_rows, expected):
        matched = next((i for i, (a, b) in enumerate(zip(row, seed_ids)) if a != b),
                       min(len(row), len(seed_ids)))
        if matched // page * page != wanted or wanted >= len(row):
            raise ValueError('Prefix length differs from declared cache bound')
        private_page = (wanted, tuple(row[wanted:wanted + page]))
        if len(row) < wanted + page or private_page in seen:
            raise ValueError('Duplicate/short random-tail boundary page')
        seen.add(private_page)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime', default=DEFAULT_RUNTIME)
    p.add_argument('--reference-point', type=Path, default=Path(DEFAULT_REFERENCE))
    p.add_argument('--base-url', default='http://127.0.0.1:30480')
    p.add_argument('--dataset', choices=('legacy-ids', 'gsp-text'), default='legacy-ids')
    p.add_argument('--arrival', choices=('poisson', 'deterministic'), default='poisson')
    p.add_argument('--request-rate', type=float, default=2.5)
    p.add_argument('--seed', type=int, default=20260913)
    p.add_argument('--output-root', type=Path, default=Path('/volume/dev/alan/study/v4flash-sla-diff-fixed-20260914'))
    p.add_argument('--ttft-limit', type=float, default=1.0)
    p.add_argument('--tpot-limit-ms', type=float, default=25.4)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    return p


def main():
    args = parser().parse_args()
    if urlparse(args.base_url).hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Only local worker URLs are allowed')
    if not math.isfinite(args.request_rate) or args.request_rate <= 0:
        raise ValueError('SLA request rate must be finite and positive')
    sys.path.insert(0, str(Path(args.runtime) / 'sgl-workspace/sglang/python'))
    os.environ['SGLANG_IS_IN_CI'] = '0'
    import numpy as np
    import requests
    from sglang.benchmark import serving
    from sglang.benchmark.datasets.common import DatasetRow

    reference = json.loads((args.reference_point / 'manifest.json').read_text())
    old_info = json.loads((args.reference_point / 'initial-server-info.json').read_text())
    model = old_info.get('server_args', old_info)['model_path']
    tokenizer = serving.get_tokenizer(model)
    n, output_length = reference['n'], reference['output_tokens']
    page = reference['page_size']
    if args.dataset == 'legacy-ids':
        with np.load(args.reference_point / 'input_ids.npz', allow_pickle=False) as archive:
            array = archive['input_ids']
            seed_ids = archive['shared_prefix'].tolist()
        digest = hashlib.sha256(array.tobytes()).hexdigest()
        if digest != reference['dataset_sha256']:
            raise ValueError('Legacy input array hash mismatch')
        token_rows = array.tolist()
        expected = reference['per_request_prefix_lengths']
        rows = [DatasetRow(prompt=ids, prompt_len=len(ids), output_len=output_length) for ids in token_rows]
    else:
        from sglang.benchmark.datasets.generated_shared_prefix import get_gen_prefix_cache_path
        cache = get_gen_prefix_cache_path(20260913, 1, 200, 17525, 4491, 514, tokenizer)
        blob = cache.read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        if digest != GSP_HASH:
            raise ValueError('GSP cache does not match the user baseline')
        rows = pickle.loads(blob)  # Trusted local pickle, verified before loading.
        token_rows = [tokenizer.encode(row.prompt) for row in rows]
        common = min(map(len, token_rows))
        for row in token_rows[1:]:
            common = next((i for i in range(common) if row[i] != token_rows[0][i]), common)
        seed_ids = token_rows[0][:common]
        expected = [common // page * page] * len(rows)
    validate_prefixes(token_rows, seed_ids, expected, page)
    if len(rows) != n or any(len(ids) != row.prompt_len or row.output_len != output_length
                             for ids, row in zip(token_rows, rows)):
        raise ValueError('Input/output lengths do not match the dataset')

    observers = []
    observed_request, function_sha = instrument_native(serving, observers)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = args.output_root / f'{args.dataset}-{args.arrival}-r{args.request_rate:g}-{stamp}-{uuid.uuid4().hex[:6]}'
    command = ['sglang.benchmark.serving', '--backend', 'sglang', '--base-url', args.base_url,
               '--model', model, '--tokenizer', model, '--num-prompts', str(n),
               '--dataset-name', 'generated-shared-prefix' if args.dataset == 'gsp-text' else 'random-ids',
               '--request-rate', str(args.request_rate), '--temperature', '0', '--seed', str(args.seed),
               '--warmup-requests', '0', '--cache-report', '--output-details',
               '--output-file', str(out / 'native-result.jsonl')]
    manifest = {
        'measurement_version': VERSION, 'dataset_kind': args.dataset, 'dataset_sha256': digest,
        'model': model, 'reference_point': str(args.reference_point),
        'requests': n, 'output_tokens': output_length,
        'mean_input_tokens': sum(map(len, token_rows)) / n,
        'expected_cache_rate': sum(expected) / sum(map(len, token_rows)),
        'original_cache_target': reference['target_cache_rate'],
        'per_request_cache_bounds': expected, 'seed_tokens': len(seed_ids),
        'arrival': args.arrival, 'arrival_seed': args.seed, 'request_rate': args.request_rate,
        'native_request_source_sha256': function_sha,
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'ttft_definition': 'Native first nonempty text; first generated token reported separately',
        'tpot_definition': '(Native E2E - native TTFT) / (output_tokens - 1)',
        'prepared_prefix_only': True, 'preparation_excluded_from_formal_timing': True,
        'command_argv': command, 'output': str(out),
    }
    print(json.dumps({k: v for k, v in manifest.items() if k not in ('per_request_cache_bounds', 'command_argv')}, indent=2), flush=True)
    if not args.execute or args.dry_run:
        print('DRY RUN: no HTTP requests, no cache changes, no files written.', flush=True)
        return
    out.mkdir(parents=True)
    save(out / 'manifest.json', manifest)
    identity = engine_identity(args.base_url)
    save(out / 'engine-identity-before.json', identity)
    with requests.Session() as session:
        session.trust_env = False
        def get(endpoint):
            response = session.get(args.base_url + endpoint, timeout=15)
            response.raise_for_status()
            return response.json()
        before_loads = get('/v1/loads')
        if any(unit.get('num_running_reqs', 0) or unit.get('num_waiting_reqs', 0)
               for unit in before_loads.get('loads', [])) or not before_loads.get('loads'):
            raise RuntimeError('Worker not verifiably idle; cache NOT flushed')
        info = get('/get_server_info')
        effective = info.get('server_args', info)
        if effective.get('model_path') != model or effective.get('page_size') != page or effective.get('dp_size', 1) != 1:
            raise ValueError('Model/page/DP differs; cache NOT flushed')
        save(out / 'server-config.json', {k: effective.get(k) for k in (
            'model_path', 'tp_size', 'dp_size', 'ep_size', 'page_size', 'mem_fraction_static',
            'kv_cache_dtype', 'chunked_prefill_size', 'speculative_algorithm', 'random_seed',
            'max_running_requests', 'enable_mixed_chunk', 'prefill_decode_interval',
        )})
        save(out / 'loads-before.json', before_loads)
        response = session.post(args.base_url + '/flush_cache', params={'timeout': 30}, timeout=35)
        save(out / 'flush.json', {'status': response.status_code, 'body': response.text})
        response.raise_for_status()
        begun = time.perf_counter()
        response = session.post(args.base_url + '/generate', json={
            'input_ids': seed_ids, 'stream': False,
            'sampling_params': {'max_new_tokens': 1, 'temperature': 0, 'ignore_eos': True},
        }, timeout=180)
        response.raise_for_status()
        preseed = response.json()
        save(out / 'preseed.json', {'duration_s': time.perf_counter() - begun, 'response': preseed})
        meta = preseed.get('meta_info', {})
        if meta.get('cached_tokens') != 0 or meta.get('prompt_tokens') != len(seed_ids) or meta.get('completion_tokens') != 1:
            raise RuntimeError('Preseed not cold or length invalid; formal requests NOT sent')

    # Keep native payload construction, token parsing, arrival loop, metric
    # calculation, result output, and request concurrency semantics intact.
    serving.get_dataset = lambda *_args, **_kwargs: rows
    serving.ASYNC_REQUEST_FUNCS['sglang'] = observed_request
    if args.arrival == 'deterministic':
        async def deterministic(inputs, rate, **_kwargs):
            started = time.perf_counter()
            for index, row in enumerate(inputs):
                await asyncio.sleep(max(0, started + index / rate - time.perf_counter()))
                yield row
        serving.get_request = deterministic
    # The cloned function's namespace must see the parsed native arguments.
    original_run = serving.run_benchmark
    def run(native_args):
        observed_request.__globals__['args'] = native_args
        return original_run(native_args)
    serving.run_benchmark = run
    sys.argv = command
    try:
        serving.cli_main()
    finally:
        save(out / 'dual-clock-requests.json', [getattr(o, 'result', {
            'index': o.index, 'incomplete': True, 'frames_elapsed_count_text_chars': o.frames,
        }) for o in observers])
    result_lines = (out / 'native-result.jsonl').read_text().splitlines()
    if len(result_lines) != 1:
        raise RuntimeError('Expected one native result')
    result = json.loads(result_lines[0])
    identity_after = engine_identity(args.base_url)
    save(out / 'engine-identity-after.json', identity_after)
    with requests.Session() as session:
        session.trust_env = False
        health = session.get(args.base_url + '/health', timeout=15)
        after_loads = session.get(args.base_url + '/v1/loads', timeout=15)
        after_loads.raise_for_status()
        save(out / 'loads-after.json', after_loads.json())
    actual = result['cached_tokens']
    exact_inputs = result['input_lens'] == list(map(len, token_rows))
    isolation = len(actual) == n and all(0 <= a <= b for a, b in zip(actual, expected))
    hit = sum(actual) / sum(result['input_lens'])
    cache_valid = abs(hit - reference['target_cache_rate']) <= .005
    dual = [o.result for o in observers if hasattr(o, 'result') and o.result['success']]
    def mean(name):
        values = [row[name] for row in dual if row[name] is not None]
        return statistics.mean(values) if values else None
    starts = [o.started for o in observers]
    summary = {
        'measurement_version': VERSION, 'completed': result['completed'],
        'mean_ttft_s': result['mean_ttft_ms'] / 1000,
        'mean_tpot_ms': result['mean_tpot_ms'],
        'legacy_first_token_ttft_mean_s': mean('legacy_first_token_ttft_s'),
        'legacy_token_to_token_tpot_mean_ms': mean('legacy_token_to_token_tpot_ms'),
        'mean_visible_delay_s': mean('visible_after_first_token_s'),
        'first_visible_at_token_1': sum(row['first_visible_completion_count'] == 1 for row in dual),
        'ttft_over_1s_requests': sum(row['ttft_s'] > 1 for row in dual),
        'same_input_lengths': exact_inputs, 'random_tail_full_page_reuse_absent': isolation,
        'all_requests_reused_expected_prefix': actual == expected,
        'actual_cache_hit_rate': hit, 'within_original_cache_target': cache_valid,
        'latency_sla_pass': result['completed'] == n and result['mean_ttft_ms'] / 1000 <= args.ttft_limit
                            and result['mean_tpot_ms'] <= args.tpot_limit_ms,
        'total_tpm': result['total_throughput'] * 60,
        'completed_rps': result['request_throughput'],
        'actual_offered_rps': (len(starts) - 1) / (max(starts) - min(starts)) if len(starts) > 1 else None,
        'engine_identity_unchanged': identity_after == identity,
        'health_after_http': health.status_code,
        'note': 'One finite diagnostic point, not a stable maximum capacity or a revenue replacement.',
    }
    summary['sla_pass'] = (summary['latency_sla_pass'] and cache_valid and isolation and exact_inputs
                           and identity_after == identity and health.status_code == 200)
    save(out / 'summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)
    print('EVIDENCE=' + str(out), flush=True)


if __name__ == '__main__':
    main()
