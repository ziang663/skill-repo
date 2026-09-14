"""Execute both approved stages for one model, strictly sequentially on local GPUs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from local_campaign import PROFILES, process_start
from report_results import main as update_report

TAGS = {"v41": "dev-dsv41", "v4flash": "latest", "v4pro": "latest",
        "glm53": "latest", "glm53flash": "glm-5.3-flash"}


def invoke(*argv):
    subprocess.run([sys.executable, str(ROOT/argv[0]), *argv[1:]], check=True)


def validated_launch_overrides(record, model):
    """Only explicitly recorded memory/graph tuning; never change workload/SLA."""
    assert record['model'] == model
    assert record['authorization'] and record['reason']
    strategies = record['strategies']
    assert strategies and set(strategies) <= {'throughput', 'sla'}
    for values in strategies.values():
        assert isinstance(values, list) and values and len(values) % 2 == 0
        seen = set()
        for flag, value in zip(values[::2], values[1::2]):
            assert isinstance(flag, str) and isinstance(value, str)
            assert flag not in seen
            seen.add(flag)
            if flag == '--mem-fraction-static':
                assert 0 < float(value) < 1
            elif flag == '--cuda-graph-max-bs-decode':
                assert value.isdecimal() and int(value) > 0
            else:
                raise ValueError(f'Unapproved launch override: {flag}')
    return strategies


def throughput_disposition(summary, review):
    """A reviewed off-target result may finish the attempt, never become PASS."""
    if summary['status'] == 'PASS':
        assert review is None, 'PASS needs no failure review'
        return 'target_passed'
    assert summary['status'] == 'FAIL'
    assert summary['failure_reasons'] == ['cache_rate_mismatch']
    assert summary['requests'] == summary['success'] == 200
    assert summary['health_after']['/health']['http'] == 200
    assert review is not None, 'An explicit written review is required'
    assert review['disposition'] == 'retain_fail_continue_independent_sla'
    assert review['model'] == summary['model']
    assert review['evidence_unchanged'] is True
    assert review['diagnosis'] and review['repeat_evidence']
    return 'reviewed_cache_target_failure'


def completed_throughput(model, name, runtime, review_path=None):
    assert name.replace('-', '').replace('_', '').isalnum()
    out = ROOT/'benchmarks'/name
    summary = json.loads((out/'summary.json').read_text())
    manifest = json.loads((out/'manifest.json').read_text())
    launch = json.loads((ROOT/'runs'/summary['engine_run']/'launch.json').read_text())
    assert summary['model'] == model and summary['scenario'] == 'throughput'
    assert summary['requests'] == summary['success'] == 200
    assert summary['request_rate'] == 'inf' and summary['gpus'] == PROFILES[model]['gpus']
    assert manifest['input_tokens'] == 76800 and manifest['output_tokens'] == 1024
    assert manifest['concurrency_limit'] is None and manifest['target_cache_rate'] == .9
    assert launch['profile'] == PROFILES[model] and launch['runtime'] == str(runtime)
    review = json.loads(Path(review_path).read_text()) if review_path else None
    if review:
        assert review['point'] == name
        repeated = json.loads((ROOT / review['repeat_evidence']).read_text())
        assert repeated['model'] == model and repeated['scenario'] == 'throughput'
        assert repeated['status'] == 'FAIL' and repeated['failure_reasons'] == ['cache_rate_mismatch']
        assert repeated['requests'] == repeated['success'] == 200
        assert repeated['engine_run'] == summary['engine_run']
    disposition = throughput_disposition(summary, review)
    return {'name': name, 'summary': str(out/'summary.json'), 'engine_run': summary['engine_run'],
            'disposition': disposition, 'review': str(review_path) if review_path else None}


def run(args):
    state_path = ROOT/(args.name+"-model-state.json")
    assert not state_path.exists()
    tag = TAGS[args.model]
    runtime = ROOT/"runtimes"/tag/"runtime"
    state = {"model": args.model, "tag": tag, "status": "waiting_for_runtime", "stages": [],
             "startup_wait_timeout_s": args.startup_timeout,
             "controller": {"pid": os.getpid(), "pgid": os.getpgrp(),
                            "start_ticks": process_start(os.getpid())},
             "started_utc": datetime.now(timezone.utc).isoformat()}
    overrides = {}
    if args.launch_overrides:
        override_path = Path(args.launch_overrides).resolve()
        record = json.loads(override_path.read_text())
        overrides = validated_launch_overrides(record, args.model)
        assert not (overrides.get('throughput') and
                    (args.reuse_throughput_engine or args.completed_throughput_name)), \
            'Cannot apply new throughput settings to reused baseline evidence'
        state['launch_overrides'] = {'path': str(override_path), 'record': record}
    def save():
        state_path.write_text(json.dumps(state, indent=2)+"\n")
    save()
    try:
        deadline = time.monotonic()+1800
        while not (runtime.parent/"complete.json").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("Official runtime extraction timeout")
            time.sleep(15)
        state["status"] = "runtime_preflight"
        save()
        invoke("runtime_check.py", tag, args.model)
        strategies = ('throughput', 'sla')
        if args.completed_throughput_name:
            state['completed_throughput_evidence'] = completed_throughput(
                args.model, args.completed_throughput_name, runtime, args.reviewed_throughput_failure)
            if state['completed_throughput_evidence']['disposition'] != 'target_passed':
                state['limitations'] = ['throughput_cache_target_not_met; raw FAIL retained']
            state['stages'].append(state['completed_throughput_evidence']['engine_run'])
            strategies = ('sla',)
            save()
        for strategy in strategies:
            name = args.name+"-"+strategy
            state.update(status="starting", active_stage=name)
            save()
            engine_name = name
            if strategy == 'throughput' and args.reuse_throughput_engine:
                active = json.loads((ROOT / 'active-engine.json').read_text())
                assert active['name'] == args.reuse_throughput_engine
                assert active['model'] == args.model and active['strategy'] == strategy
                assert process_start(active['pid']) == active['start_ticks']
                assert os.getpgid(active['pid']) == active['pid']
                assert ('FIVE_MODEL_COST_RUN=' + active['run']).encode() in Path(f"/proc/{active['pid']}/environ").read_bytes().split(b'\0')
                launch = json.loads((Path(active['run']) / 'launch.json').read_text())
                assert launch['profile'] == PROFILES[args.model] and launch['runtime'] == str(runtime)
                engine_name = active['name']
                state['reused_throughput_engine'] = engine_name
                save()
            else:
                launch_args = ["local_campaign.py", "start", "--model", args.model,
                               "--strategy", strategy, "--name", name, "--runtime", str(runtime)]
                if overrides.get(strategy):
                    launch_args.extend(['--extra-args', *overrides[strategy]])
                invoke(*launch_args)
            update_report()
            state["status"] = "benchmarking"
            save()
            if strategy == "throughput":
                invoke("conduct.py", "throughput", "--model", args.model, "--name", name+"-inf",
                       '--startup-timeout', str(args.startup_timeout))
            else:
                invoke("conduct.py", "search", "--model", args.model, "--name", name,
                       "--initial-rate", str(args.initial_rate), '--startup-timeout', str(args.startup_timeout))
            invoke("local_campaign.py", "status")
            state["stages"].append(name)
            save()
            # Keep every attempt. Controller success is not equivalent to SLA PASS.
            if strategy == "throughput":
                summary = json.loads((ROOT/"benchmarks"/(name+"-inf")/"summary.json").read_text())
                if summary["status"] != "PASS":
                    raise RuntimeError("Throughput point requires inspection before continuing")
            else:
                summary = json.loads((ROOT/(name+"-search.json")).read_text())
                if summary["status"] in ("infrastructure_failure", "interrupted_or_error"):
                    raise RuntimeError("SLA search requires inspection before continuing")
            invoke("local_campaign.py", "stop", "--name", engine_name)
        state["status"] = ('both_stages_completed_with_limitations' if state.get('limitations')
                           else 'both_stages_completed')
    except Exception as exc:
        state.update(status="needs_inspection", error=repr(exc))
        raise
    finally:
        save()
        update_report()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", choices=PROFILES, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--initial-rate", type=float, default=.25)
    p.add_argument('--reuse-throughput-engine')
    p.add_argument('--completed-throughput-name')
    p.add_argument('--reviewed-throughput-failure',
                   help='Written review of repeated cache-only mismatch; retain FAIL and continue independent SLA')
    p.add_argument('--startup-timeout', type=float, default=3600)
    p.add_argument('--launch-overrides',
                   help='Explicit user-approved per-strategy memory/graph overrides JSON; baseline profiles stay unchanged')
    args = p.parse_args()
    assert args.startup_timeout > 0
    assert not (args.reuse_throughput_engine and args.completed_throughput_name)
    assert not args.reviewed_throughput_failure or args.completed_throughput_name
    assert args.name.replace("-", "").replace("_", "").isalnum()
    import fcntl
    with (ROOT/"model-controller.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(args)
