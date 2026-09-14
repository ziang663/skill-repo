"""Continue the approved model order after the running V4.1 campaign finishes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def read_state(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main(args):
    state_path = ROOT/(args.name + '-state.json')
    assert not state_path.exists(), "Do not duplicate a queue"
    state = {"status": "waiting_for_predecessor", "pending": list(args.models), "completed": [],
             "waiting_for": args.after_model_name, "run_suffix": args.run_suffix,
             "controller": {"pid": os.getpid(), "pgid": os.getpgrp(),
                            "start_ticks": Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]},
             "launch_overrides": args.launch_overrides}
    def save():
        state_path.write_text(json.dumps(state, indent=2)+"\n")
    save()
    try:
        while True:
            first = read_state(ROOT/(args.after_model_name + '-model-state.json'))
            if first.get("status") in ('both_stages_completed', 'both_stages_completed_with_limitations'):
                break
            if first.get("status") == "needs_inspection":
                raise RuntimeError(f"{args.after_model_name} requires inspection; queue did not start another model")
            time.sleep(15)
        for model in list(state["pending"]):
            state.update(status="running", active_model=model)
            save()
            command = [sys.executable, str(ROOT/"run_model.py"), "--model", model,
                       "--name", model+'-'+args.run_suffix, "--initial-rate", ".25"]
            if args.launch_overrides:
                command.extend(['--launch-overrides', args.launch_overrides])
            subprocess.run(command, check=True)
            state["completed"].append(model)
            state["pending"].remove(model)
            save()
        state["status"] = "completed"
    except Exception as exc:
        state.update(status="needs_inspection", error=repr(exc))
        raise
    finally:
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', default='remaining-models')
    parser.add_argument('--after-model-name', default='v41-official-01')
    parser.add_argument('--run-suffix', default='official-01')
    parser.add_argument('--models', nargs='+', choices=['v4flash', 'v4pro', 'glm53', 'glm53flash'],
                        default=['v4flash', 'v4pro', 'glm53', 'glm53flash'])
    parser.add_argument('--launch-overrides', help='Recorded memory/graph tuning for a single queued model')
    args = parser.parse_args()
    assert all(value.replace('-', '').isalnum() for value in (args.name, args.after_model_name, args.run_suffix))
    assert not args.launch_overrides or len(args.models) == 1
    import fcntl
    with (ROOT/"remaining-controller.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        main(args)
