# Pod Terminal Access

## When to use it

Use the platform Pod terminal for live, read-only checks that logs and the SiFlow SDK
cannot answer, such as `/proc` inspection, environment verification, mounted-storage
checks, and CUDA user-coredump FIFO validation.

The SiFlow SDK does not currently expose Pod exec, but the console's `Terminal` button
uses this WebSocket endpoint:

```text
wss://<console-host>/sfapi/manage-service/v1/pod-exec?cluster=<cluster>&podName=<pod>
```

Optional query parameters:

- `owner=<owner>` when accessing a Pod owned by another user.
- `vOrgName=<tenant>` when operating through a switched tenant context.

Authenticate with the dynamic headers in `SiFlow.default_headers`. Do not hardcode or
print `AppID`, `Signature`, `Randstr`, or other credentials. The browser normally uses
its login session; SDK access keys work by supplying the signed SiFlow headers during
the WebSocket handshake.

## Protocol

The terminal accepts JSON messages:

```json
{"type":"resize","rows":50,"cols":200}
{"type":"input","input":"hostname\r"}
```

Output is terminal text and can contain ANSI escape sequences. Send `\r` to execute a
command. The endpoint opens the workload's main container.

Prefer the helper:

```bash
python scripts/pod_terminal.py \
  --region us-west --cluster pisces \
  --pod-name <pod> \
  --check-cuda-corepipes --expected-schedulers 8
```

Arbitrary commands require both `--command` and `--allow-command`:

```bash
python scripts/pod_terminal.py \
  --region us-west --cluster pisces \
  --pod-name <pod> \
  --command 'hostname; ps -eo pid,args' \
  --allow-command
```

Set `SIFLOW_ACCESS_KEY_ID` and `SIFLOW_ACCESS_KEY_SECRET` in the environment. Never put
tokens in command arguments, URLs, reports, or Skill files.

## Safety

- Default to read-only commands. Pod terminal access is equivalent to a production
  shell; the endpoint itself is not read-only.
- Do not restart processes, change files, send signals, or alter service state without
  explicit authorization.
- Never write `1` to `/tmp/corepipe.cuda.*` just to test it. That triggers a real GPU
  coredump and can pause or destabilize the Engine.
- To validate CUDA user-triggered coredumps safely, require both:
  - every expected scheduler PID has a named pipe; and
  - the scheduler process holds at least one FD referencing that pipe.

## Evidence persistence across Pod restarts

Pod-local state disappears when a Pod is recreated:

- `/tmp/corepipe.cuda.*`;
- `/proc/<pid>` and process memory;
- files written only to the container root filesystem.

Evidence survives only if it reached an external sink or persistent mount before the
container was killed:

- logs already shipped to SiFlow/OmniObs;
- traces and metrics already exported;
- SGLang request snapshots under a shared `--crash-dump-folder`;
- CUDA core files whose `CUDA_COREDUMP_FILE` points into the shared mount.

Verify the mount in the Pod spec and confirm that each new Pod can create its per-host
directory. A directory alone proves writability, not that a core completed.

CUDA dump completion is time-sensitive. SGLang's crash path sleeps about five seconds,
triggers each scheduler FIFO, then waits
`SGLANG_CUDA_COREDUMP_BEFORE_CRASH_WAIT_SECS` (default 60 seconds). Compare that total
with Kubernetes `terminationGracePeriodSeconds`. If the grace period is shorter, a
partially generated core may be truncated or absent. Prefer increasing termination
grace, or explicitly shortening the post-trigger wait only after considering core
generation time. Even with correct configuration, a severe driver/GPU hang can prevent
a usable dump, so retain external logs, py-spy output, request snapshots, and lifecycle
events as independent evidence.
