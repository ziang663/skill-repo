"""Reuse the audited token/stream benchmark, with separate NVFP4 evidence."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time

from experiment import ROOT, CAMPAIGN, MODEL, PROFILES, owned_record, lifecycle, save
from warning_policy import classify_log

spec = importlib.util.spec_from_file_location('nvfp4_benchmark_core', ROOT / 'benchmark_core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
core.ROOT = ROOT
core.PROFILES = PROFILES
# Original core intentionally only supports loopback :30480.
assert core.BASE == 'http://127.0.0.1:30480'
assert core.FORMAL_REQUESTS == 200


async def run(args):
    assert args.model == MODEL and args.n is None, 'Maximum 200; SLA may stop after first 100 pass'
    active = owned_record()
    assert active['strategy'] == args.scenario
    launch = json.loads((Path(active['run']) / 'launch.json').read_text())
    assert launch['profile'] == PROFILES[MODEL]
    assert not any('SIMULATE' in key for key in launch['env'])
    out = ROOT / 'benchmarks' / args.name
    assert not out.exists()
    policy_path = ROOT / 'warning-policy-20260914.json'
    policy = json.loads(policy_path.read_text())
    assert policy['allocator_warning_action'] == 'record_only'
    assert policy['resume_authorized']
    log_path = Path(active['run']) / 'engine.log'
    initial_log_bytes = log_path.stat().st_size
    observations = []
    started = time.monotonic()

    async def observe():
        while True:
            proc = await asyncio.create_subprocess_exec(
                'nvidia-smi', '--query-gpu=index,memory.used,memory.total,utilization.gpu',
                '--format=csv,noheader,nounits', stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await proc.communicate()
            observations.append({'utc': lifecycle.utc(), 'elapsed_s': time.monotonic()-started,
                                 'exit_code': proc.returncode, 'gpu_csv': stdout.decode(),
                                 'stderr': stderr.decode(),
                                 'same_engine': lifecycle.process_start(active['pid']) == active['start_ticks']})
            if out.exists():
                save(out / 'gpu-observations.json', observations)
            await asyncio.sleep(10)

    observer = asyncio.create_task(observe())
    try:
        await core.run(args)
    finally:
        observer.cancel()
        try:
            await observer
        except asyncio.CancelledError:
            pass
        if out.exists():
            same = lifecycle.process_start(active['pid']) == active['start_ticks']
            save(out / 'engine-identity.json', {'utc': lifecycle.utc(), 'before': active,
                                               'same_engine_after': same})
            save(out / 'gpu-observations.json', observations)
            log_bytes = log_path.read_bytes()
            scan = classify_log(log_bytes.decode(errors='replace'))
            current_scan = classify_log(log_bytes[initial_log_bytes:].decode(errors='replace'))
            save(out / 'engine-error-scan.json', {'utc': lifecycle.utc(), **scan,
                 'this_point': current_scan, 'point_initial_log_bytes': initial_log_bytes,
                 'policy': policy, 'policy_sha256': hashlib.sha256(policy_path.read_bytes()).hexdigest()})
            summary_path = out / 'summary.json'
            if summary_path.exists():
                summary = json.loads(summary_path.read_text())
                if not same:
                    summary['failure_reasons'].append('engine_generation_changed')
                if scan['runtime_errors']:
                    summary['failure_reasons'].append('engine_runtime_errors')
                summary['status'] = 'FAIL' if summary['failure_reasons'] else 'PASS'
                summary['allocator_warning_count_this_point'] = len(current_scan['allocator_warnings'])
                summary['allocator_warning_count_engine_total'] = len(scan['allocator_warnings'])
                summary['warning_policy'] = policy_path.name
                summary['warning_policy_sha256'] = hashlib.sha256(policy_path.read_bytes()).hexdigest()
                summary['wrapper_evidence'] = 'engine-identity.json; engine-error-scan.json; gpu-observations.json'
                save(summary_path, summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=PROFILES, required=True)
    parser.add_argument('--scenario', choices=['throughput','sla'], required=True)
    parser.add_argument('--rate', type=float, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--n', type=int)
    parser.add_argument('--seed', type=int, default=20260913)
    args = parser.parse_args()
    assert args.rate > 0 and args.name.replace('-','').replace('_','').replace('.','').isalnum()
    asyncio.run(run(args))
