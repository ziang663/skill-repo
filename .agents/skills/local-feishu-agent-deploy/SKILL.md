---
name: local-feishu-agent-deploy
description: Securely deploy, validate, restart, and troubleshoot a Feishu/Lark agent backend on a local Linux host. Use for Node.js or TypeScript bots that receive im.message.receive_v1 over Feishu long connection, call an OpenAI-compatible model API, optionally read GitHub, expose health endpoints, and run persistently with tmux or an existing process manager.
---

# Local Feishu Agent Deployment

## Operating contract

- Treat deployment as complete only when the process is persistent, `/readyz` succeeds, the Feishu long connection is connected, and a real bot request completes.
- Prefer Feishu long connection for a local machine. It needs outbound network access but no public webhook or inbound firewall rule.
- Never put an App Secret, model API key, GitHub token, or populated `.env` in Git, Skill files, reports, command output, or logs.
- Preserve unrelated local changes. Inspect before editing, and never delete or replace an existing deployment merely because startup failed.
- Do not hard-code a project directory, port, model, endpoint, or process name. Discover them or obtain them from the user.

## Workflow

1. Inspect the repository's instructions, package scripts, runtime version, configuration loader, health implementation, ignore files, and current Git status.
2. Determine the project directory, start command, model endpoint and model name, Feishu domain, health port, and process manager. Reuse explicit user choices.
3. Run `scripts/preflight_local_agent.py --project-dir <path> --env-file .env`. Fix only confirmed failures.
4. Ensure the secret file is ignored by Git and container build context, owned by the deployment user, and mode `0600` or stricter. Populate secrets only from user-approved environment variables or secret storage.
5. Install locked dependencies and execute the repository's full check/build command before touching the running process. For npm projects, prefer `npm ci`, then the existing `check`, `test`, `typecheck`, and `build` scripts rather than inventing equivalents.
6. Check whether the configured port is already listening and identify the owner. Select another port only when changing it is safe; update configuration and health checks together.
7. Validate the model and GitHub paths without Feishu when the project provides a CLI or test command. This separates external API errors from event-delivery errors.
8. Start or restart the service with the repository's existing process manager. When using tmux, stop the old process with `Ctrl-C`, confirm it exited, and then start exactly one replacement session.
9. Verify `/healthz`, `/readyz`, the connection log, and a real group `@bot` request in that order.
10. Report the project path, runtime command, process/session name, bound port, endpoint results, and remaining risks. Never report secret values.

Read `references/deployment-runbook.md` before changing credentials, Feishu settings, ports, or a live process. It contains the detailed commands, acceptance gates, and failure matrix.

## Acceptance gates

- Build gate: dependency installation and repository checks pass.
- Process gate: one intended process owns the configured port and remains alive after the launching shell exits.
- Health gate: `/healthz` returns HTTP 200.
- Readiness gate: `/readyz` returns HTTP 200 only after the Feishu client is connected.
- Model gate: a minimal direct query reaches the configured model and returns a usable response.
- GitHub gate: an authenticated request has the expected rate limit when the bot depends on GitHub.
- Feishu gate: logs show a successful connection and an actual mention receives both acknowledgement and final response.

Do not declare success from `/healthz` alone. It proves only that the local process is serving its health endpoint.

## Restart discipline

For tmux deployments:

1. Inspect the current session and recent logs.
2. Send `Ctrl-C` to the process pane.
3. Poll until the process and listener exit; avoid a blind fixed delay.
4. Preserve failure logs.
5. Start one new detached session in the project directory.
6. Re-run all acceptance gates.

Do not create a second session on the same port while the old process is still alive. Do not use recursive deletion as a recovery step.

## Evidence standards

- Show HTTP status and sanitized response bodies for health checks.
- Show connection state and error categories, not credential-bearing environment dumps.
- Distinguish process health, Feishu readiness, model availability, GitHub availability, and end-to-end message handling.
- If an external service is slow, measure the direct model/GitHub request separately before blaming the Feishu client.
- If blocked, retain the exact sanitized error, the last successful gate, and the next action requiring user or platform authority.
