"""Read-only shutdown checks; never signal or adopt untracked processes."""
import errno
import json
from pathlib import Path
import socket
import subprocess
import time


def live_group_pids(pgid):
    live = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == pgid and fields[0] not in ('Z', 'X'):
                live.append(int(entry.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return sorted(live)


def port_released(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                return False
            raise
    return True


def release_state(record, gpus):
    usage = subprocess.check_output(
        ['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], text=True)
    memory = [int(v.strip()) for v in usage.splitlines()[:gpus]]
    return {'live_group_pids': live_group_pids(record['pid']),
            'port_released': port_released(record['port']),
            'gpu_memory_mib': memory,
            'gpus_released': len(memory) == gpus and all(v < 512 for v in memory)}


def wait_for_release(record, gpus, timeout=180, poll_interval=1):
    start = time.monotonic()
    next_log = start
    while True:
        state = release_state(record, gpus)
        now = time.monotonic()
        if not state['live_group_pids'] and state['port_released'] and state['gpus_released']:
            return {**state, 'wait_seconds': now-start}
        if now-start >= timeout:
            raise TimeoutError(f'Tracked engine resources not released: {state}; no next launch')
        if now >= next_log:
            print(json.dumps({'waiting_for_release': record['name'], **state}), flush=True)
            next_log = now+10
        time.sleep(poll_interval)
