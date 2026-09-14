"""Refresh public sources and local shard checks without changing old evidence."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

from collect_sources import SOURCES

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'resume-01'


def fetch(name):
    url = SOURCES[name]
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40) as response:
        data = response.read()
    path = OUT / (name + '.raw')
    with path.open('xb') as target:
        target.write(data)
    previous = json.loads((ROOT / 'sources' / (name + '.json')).read_text())
    digest = hashlib.sha256(data).hexdigest()
    return {'name': name, 'url': url, 'utc': datetime.now(timezone.utc).isoformat(), 'sha256': digest, 'same_as_saved': digest == previous['sha256'], 'bytes': len(data)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', default='resume-01')
    args = parser.parse_args()
    assert args.name.replace('-', '').isalnum()
    OUT = ROOT / args.name
    OUT.mkdir(exist_ok=False)
    names = ['cookbook-v41-md', 'cookbook-v4-md', 'cookbook-glm53-md', 'cookbook-glm53flash-md', 'deepseek-pricing', 'zai-pricing']
    with ThreadPoolExecutor(max_workers=6) as pool:
        sources = list(pool.map(fetch, names))
    weights = []
    for key, profile in json.loads((ROOT / 'profiles.json').read_text()).items():
        model = Path(profile['model_path'])
        index = json.loads((model / 'model.safetensors.index.json').read_text())
        shards = sorted(set(index['weight_map'].values()))
        missing = [name for name in shards if not (model / name).is_file()]
        weights.append({'model': key, 'path': str(model), 'gpus': profile['gpus'], 'shard_count': len(shards), 'missing': missing, 'tokenizer_exists': (model / 'tokenizer.json').is_file()})
        assert not missing and (model / 'tokenizer.json').is_file()
    record = {'utc': datetime.now(timezone.utc).isoformat(), 'authorization': 'User explicitly resumed the five-model evaluation', 'sources': sources, 'weights': weights}
    (OUT / 'checks.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2), flush=True)
