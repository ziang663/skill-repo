# SiFlow Python SDK installation

Read this reference when the `siflow` package is absent, broken, or needs an
explicit version upgrade.

## Supported source

SiFlow is an internal package and is not published on public PyPI. Download the
official wheel from:

```text
https://oss-cn-shanghai.siflow.cn/ai-infra-download/siflow-public/siflow-{{VERSION}}-py3-none-any.whl
```

The version verified on 2026-08-24 is `0.3.20` with Python 3.12. For that
version, the URL is:

```text
https://oss-cn-shanghai.siflow.cn/ai-infra-download/siflow-public/siflow-0.3.20-py3-none-any.whl
```

Do not mix versions between download and install commands. Some old examples
download `0.1.8` and install `0.1.7`; that is an example defect, not a supported
upgrade procedure.

## Isolated installation

Choose user-owned locations for the wheel and virtual environment. Example:

```bash
mkdir -p /mnt/workspace/siflow-sdk/downloads /mnt/workspace/siflow-sdk/.venvs

curl -fL --retry 3 --connect-timeout 15 \
  --output /mnt/workspace/siflow-sdk/downloads/siflow-0.3.20-py3-none-any.whl \
  https://oss-cn-shanghai.siflow.cn/ai-infra-download/siflow-public/siflow-0.3.20-py3-none-any.whl

python3 -m venv /mnt/workspace/siflow-sdk/.venvs/siflow
/mnt/workspace/siflow-sdk/.venvs/siflow/bin/python -m pip install --upgrade pip setuptools wheel
/mnt/workspace/siflow-sdk/.venvs/siflow/bin/python -m pip install \
  '/mnt/workspace/siflow-sdk/downloads/siflow-0.3.20-py3-none-any.whl[websocket]'
```

The `websocket` extra is recommended for SiFlow log operations. Do not run
`pip uninstall siflow` against the system interpreter. For upgrades, install
the new wheel with `--upgrade` inside the dedicated environment.

## Validation

Validate the wheel and environment before loading AK/SK:

```bash
file /mnt/workspace/siflow-sdk/downloads/siflow-0.3.20-py3-none-any.whl
sha256sum /mnt/workspace/siflow-sdk/downloads/siflow-0.3.20-py3-none-any.whl

/mnt/workspace/siflow-sdk/.venvs/siflow/bin/python - <<'PY'
from importlib.metadata import version
from siflow import SiFlow

print("siflow version:", version("siflow"))
print("SiFlow import:", SiFlow.__name__, "OK")
PY

/mnt/workspace/siflow-sdk/.venvs/siflow/bin/python -m pip check
```

The wheel fetched and verified on 2026-08-24 had SHA-256:

```text
dcfbdbf27aae7cabca0973b1fa216ffdebc46d8a49a9a65aad8f3fb5093e4573
```

Treat a future checksum difference as a reason to verify the release source,
not automatically as proof of compromise: the publisher may have replaced the
artifact under the same version.

## Credentials and first API call

Keep credentials out of command arguments, shell history, source files, and
reports. Use the environment variables required by this skill:

```bash
export SIFLOW_ACCESS_KEY_ID='<your-ak>'
read -rsp 'SiFlow SK: ' SIFLOW_ACCESS_KEY_SECRET
echo
export SIFLOW_ACCESS_KEY_SECRET
```

Run a read-only query first and use the target object's actual region and
cluster. Example:

```python
import os
from siflow import SiFlow

client = SiFlow(
    region="ap-southeast",
    cluster="aries",
    access_key_id=os.environ["SIFLOW_ACCESS_KEY_ID"],
    access_key_secret=os.environ["SIFLOW_ACCESS_KEY_SECRET"],
)

result = client.pools.list(page=1, page_size=5)
print("rows:", len(result.rows))
```

## Offline reuse

For a machine without package-index access, download the wheel and all
dependencies on a connected machine:

```bash
mkdir -p siflow-offline
python -m pip download --dest siflow-offline \
  './siflow-0.3.20-py3-none-any.whl[websocket]'
```

Copy the complete directory, then install without an index:

```bash
python3 -m venv /path/to/.venv-siflow
/path/to/.venv-siflow/bin/python -m pip install \
  --no-index --find-links /path/to/siflow-offline siflow==0.3.20
```
