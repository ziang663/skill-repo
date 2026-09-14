"""Launch the approved SLA controller with durable local job identity."""
import json
import os
import subprocess
import sys

from experiment import ROOT, lifecycle, owned_record, save
from report import main as update_report


def main():
    approval = json.loads((ROOT / 'warning-policy-20260914.json').read_text())
    assert approval['resume_authorized']
    name = approval['run_name']
    active = owned_record()
    assert active['name'] == name and active['strategy'] == 'sla'
    job = ROOT / 'jobs' / name
    assert not job.exists(), 'Do not launch a duplicate controller'
    job.mkdir()
    argv = [sys.executable, '-u', str(ROOT / 'conduct.py'), 'search',
            '--name', name, '--initial-rate', str(approval['initial_rps'])]
    env = dict(os.environ, GLM53_NVFP4_BENCH_JOB=str(job))
    with (job / 'controller.log').open('w') as log:
        proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
    record = {'utc': lifecycle.utc(), 'pid': proc.pid, 'pgid': proc.pid,
              'start_ticks': lifecycle.process_start(proc.pid), 'argv': argv,
              'job': str(job), 'engine': active}
    save(job / 'process.json', record)
    update_report()
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
