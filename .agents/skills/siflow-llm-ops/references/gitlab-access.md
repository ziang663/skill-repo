# GitLab source access

Use this procedure for private SiFlow, LLM Router, or related repositories when SSH access to
`gitlab.scitix-inner.ai:22` times out but HTTPS port 443 is available.

## Safety invariants

- Obtain the token from an environment variable, interactive hidden input, or approved secret
  file. Never paste it into a clone URL.
- Do not persist the token with `git config`, a credential helper, `.netrc`, a report, or a Skill.
- Use a transient HTTP authorization header for one Git command, then unset the shell variables.
- Keep the repository remote token-free so later `git remote -v` output is safe.

## Read the token without shell-history exposure

Prefer an existing environment variable:

```bash
test -n "$GITLAB_TOKEN"
```

For an interactive terminal, hidden input is also safe:

```bash
read -rsp 'GitLab token: ' GITLAB_TOKEN; echo
```

If an approved credentials file is used, extract only the required value into a shell variable and
never print it. Adapt the selector to the file's documented format.

## Query and clone over HTTPS

GitLab accepts the personal access token as the password for the `oauth2` username. Construct a
temporary Basic authorization header without embedding credentials in the URL:

```bash
gitlab_auth=$(printf 'oauth2:%s' "$GITLAB_TOKEN" | base64 | tr -d '\n')

git -c http.extraHeader="Authorization: Basic $gitlab_auth" \
  ls-remote --heads https://gitlab.scitix-inner.ai/GROUP/PROJECT.git

git -c http.extraHeader="Authorization: Basic $gitlab_auth" \
  clone --branch BRANCH --single-branch \
  https://gitlab.scitix-inner.ai/GROUP/PROJECT.git TARGET_DIR

unset gitlab_auth GITLAB_TOKEN
```

The resulting `origin` URL contains no token. Verify it before sharing output:

```bash
git -C TARGET_DIR remote -v
git -C TARGET_DIR rev-parse HEAD
```

For an existing clone, use the same one-command header with `git fetch`, then unset the variables.
Do not rewrite the remote to a credential-bearing URL.

## Failure interpretation

- SSH port 22 timeout: retry through HTTPS 443; it does not imply the repository is missing.
- HTTPS `HTTP Basic: Access denied`: authentication was absent, invalid, expired, or lacks repository
  scope. Confirm the token and project permissions without logging the token.
- Empty `ls-remote --heads ... pattern` with exit code 0: the requested branch pattern did not match;
  list heads without the narrow pattern before concluding the repository is inaccessible.
