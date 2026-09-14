"""Bounded original search, isolated to this NVFP4 experiment."""
import argparse
from contextlib import ExitStack
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sys

from experiment import ROOT, CAMPAIGN, MODEL, owned_record, lifecycle, save
from report import main as update_report

spec = importlib.util.spec_from_file_location('nvfp4_conduct_core', CAMPAIGN/'conduct.py')
core = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(CAMPAIGN))
spec.loader.exec_module(core)
sys.path.pop(0)
core.ROOT = ROOT
core.update_report = update_report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['throughput','search'])
    parser.add_argument('--model', default=MODEL, choices=[MODEL])
    parser.add_argument('--name', required=True)
    parser.add_argument('--initial-rate', type=float, default=.25)
    parser.add_argument('--startup-timeout', type=float, default=3600)
    args = parser.parse_args()
    assert args.name.replace('-','').replace('_','').isalnum()
    with ExitStack() as stack:
        for path in (ROOT/'controller.lock', CAMPAIGN/'controller.lock'):
            lock = stack.enter_context(path.open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active = owned_record()
        state_path = ROOT/(args.name+'-controller.json')
        assert not state_path.exists()
        state = {'utc': lifecycle.utc(), 'status': 'running', 'args': vars(args),
                 'engine': active, 'pid': os.getpid(), 'pgid': os.getpgrp(),
                 'start_ticks': lifecycle.process_start(os.getpid())}
        save(state_path, state)
        try:
            if args.action == 'search':
                core.search(args)
                search_state=json.loads((ROOT/(args.name+'-search.json')).read_text())
                assert search_state['status'] not in ('infrastructure_failure','interrupted_or_error'), 'SLA infrastructure failure requires review'
            else:
                core.wait_ready(args.startup_timeout)
                assert active['strategy']=='throughput'
                result=core.point(MODEL,'throughput',float('inf'),args.name)
                assert result['status']=='PASS', 'Throughput failed; review required before next strategy'
            state['status']='completed'
        except BaseException as exc:
            state.update(status='needs_review', error=repr(exc))
            raise
        finally:
            state['finished_utc']=lifecycle.utc()
            save(state_path,state)
            update_report()
