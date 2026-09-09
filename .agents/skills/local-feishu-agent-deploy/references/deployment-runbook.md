# Local Feishu Agent Deployment Runbook

## 1. Inspect before changing anything

Read repository-local instructions and deployment docs first. Identify:

- project directory and current Git status;
- required Node.js version and lockfile;
- install, check, build, start, and direct-query scripts;
- configuration variable names and defaults;
- health/readiness behavior;
- `.gitignore` and `.dockerignore` coverage;
- current listener and process-manager state.

Useful read-only commands:

```bash
git status --short
node --version
npm --version
npm run
ss -ltnp
tmux list-sessions
```

Do not print a populated `.env`, run `env`, or enable shell tracing around secrets.

## 2. Feishu application prerequisites

For a locally hosted bot, use Feishu/Lark long connection unless the project explicitly requires a webhook.

Confirm in the Feishu developer console:

- the Bot capability is enabled;
- the application subscribes to `im.message.receive_v1` using long connection;
- group mention/message permissions are approved;
- private-message permission is approved if private chat is required;
- the application version containing those permissions is published;
- the bot is present in the target group.

The service should log a recognizable connected state, such as `[lark] connected`. A TCP health listener does not prove that the event stream is connected.

## 3. Secret configuration

Prefer an existing secret manager or injected environment. If the project intentionally uses a local `.env`:

1. Start from the repository's `.env.example`.
2. Confirm `.env` is ignored by both Git and Docker build context.
3. Set mode `0600` before adding credentials.
4. Use the project's actual variable names.
5. Never copy the populated file into evidence, a commit, or a container image.

Typical variable classes are:

```dotenv
FEISHU_DOMAIN=feishu
FEISHU_APP_ID=<from-secret-store>
FEISHU_APP_SECRET=<from-secret-store>

OPENAI_BASE_URL=<responses-compatible-endpoint>
OPENAI_API_KEY=<from-secret-store>
OPENAI_MODEL=<approved-model-name>

GITHUB_TOKEN=<optional-read-only-token>
PORT=<local-health-port>
```

Some projects accept a provider-specific alias for `OPENAI_API_KEY`; inspect the configuration loader rather than assuming it. The selected endpoint must implement the API used by the code, commonly `POST /responses`, not merely a similarly shaped chat endpoint.

To check ignore rules without exposing contents:

```bash
git check-ignore -v -- .env
stat -c '%a %U:%G %n' .env
```

## 4. Build gate

For an npm repository with a lockfile:

```bash
npm ci
npm run check
npm run build
```

Adapt to available package scripts. If `check` already includes tests, type checking, and build, do not needlessly repeat expensive work. Stop before restarting the live process when the build gate fails.

## 5. Port selection

Read the configured port, then inspect that exact listener. A port collision is not evidence that the bot is already running; identify its owner.

```bash
ss -ltnp '( sport = :18080 )'
```

If a different process owns the port, either retain that service and select an approved free port, or coordinate its shutdown. Keep the configured port and all health probes consistent.

## 6. Layered validation before Feishu

If the repository provides a direct CLI, use it to test the same service layer without Feishu, for example:

```bash
npm run ask -- "minimal supported query"
```

This should exercise model access and, when relevant, GitHub access. Diagnose them separately:

- Model authentication or route failure: verify base URL, model name, API key scope, and API shape.
- Model timeout: measure a minimal request directly and compare it with the application's timeout.
- GitHub 403/rate limit: verify token use without displaying it.

For GitHub, query `/rate_limit` using a token already present in the environment. Record only the limit, remaining count, reset time, and HTTP status. Authenticated GitHub REST access normally raises the core limit from 60 requests/hour to 5,000 requests/hour, subject to account and organization policy.

## 7. Persistent process with tmux

Use the repository's existing service manager when one exists. Otherwise tmux is acceptable for a single-host local deployment.

Choose a stable, project-specific session name. On restart:

```bash
tmux has-session -t <session-name>
tmux send-keys -t <session-name> C-c
```

Poll the session and listener until the old process exits. Then start one detached session in the project directory using the repository's production start command. Capture logs to an already ignored runtime/log directory if the application does not manage logs itself.

Avoid placing credentials on the tmux command line. Let the process read its protected environment file or injected environment.

## 8. Health and readiness

Probe using the actual configured port:

```bash
curl --silent --show-error --fail-with-body http://127.0.0.1:<port>/healthz
curl --silent --show-error --fail-with-body http://127.0.0.1:<port>/readyz
```

Interpretation:

| Result | Meaning |
|---|---|
| `/healthz` 200, `/readyz` 503 | Process is alive; Feishu/event dependency is not ready. |
| both 200, no messages | Inspect subscription, permissions, published version, bot membership, and mention parsing. |
| neither responds | Process failed, wrong port, or listener conflict. |
| readiness flaps | Inspect long-connection reconnects, outbound network, credentials, and duplicate processes. |

Readiness should be tied to the long-connection state. If the code marks ready at process start, note that the probe is weaker than the acceptance criterion.

## 9. End-to-end acceptance

In the target group, send a minimal supported mention. Confirm:

1. the bot receives the event once;
2. it recognizes that the current bot was mentioned;
3. it sends an acknowledgement if designed to do so;
4. it returns the final model-backed answer;
5. logs contain no secret, duplicate handler, unhandled rejection, or repeated reconnect loop.

Measure separately when the final answer is slow:

- Feishu event-to-acknowledgement latency;
- GitHub data collection time;
- model generation time;
- Feishu final-message send time.

## 10. Failure matrix

| Symptom | Likely layer | Checks |
|---|---|---|
| Immediate config crash | Local config | Missing variable names, invalid domain, malformed numeric setting. |
| `EADDRINUSE` | Local process | Exact port owner, stale process, duplicate tmux session. |
| Health 200, readiness 503 | Feishu connection | App ID/secret validity, domain, outbound access, subscription and publication. |
| Connected but group mention ignored | Feishu event/parser | Bot membership, mention open ID, event permission, mention normalization. |
| Acknowledgement appears, final answer does not | GitHub/model/task queue | Direct CLI, upstream status, timeouts, concurrency and pending limits. |
| GitHub data incomplete | GitHub API | Authentication, rate limit, pagination, repository/PR permissions. |
| Model route not found | Model gateway | Exact model identifier and Responses API support. |
| Restart creates duplicate replies | Process management | Multiple bot processes or event clients using the same application credentials. |

## 11. Handoff record

Report only non-secret deployment facts:

- project path and checked revision;
- runtime and build result;
- start command category and process/session name;
- bound port;
- health and readiness status;
- direct model/GitHub validation status;
- Feishu connection and end-to-end result;
- log location and safe restart procedure;
- any remaining external permission or reliability risk.
