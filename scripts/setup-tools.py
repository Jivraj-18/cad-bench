#!/usr/bin/env python3
"""Download immutable enhancement sources and freeze their file hashes."""
import hashlib
import io
import json
import shutil
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
config = json.loads((ROOT/'configs/experiment.json').read_text())
entries = []
for item in config['enhancements']:
    target = ROOT/item['path']
    if not target.exists():
        repo = item['source'].removeprefix('https://github.com/')
        url = f"https://codeload.github.com/{repo}/tar.gz/{item['commit']}"
        with urllib.request.urlopen(url, timeout=90) as response:
            archive = response.read()
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tf:
            members = tf.getmembers()
            prefix = members[0].name.split('/')[0]
            staging = ROOT/'data/vendor-download'/item['id']
            staging.mkdir(parents=True, exist_ok=True)
            tf.extractall(staging, filter='data')
            extracted = staging/prefix
            target.parent.mkdir(parents=True, exist_ok=True)
            if item['kind'] == 'tool':
                shutil.copytree(extracted, target)
            else:
                shutil.copytree(extracted/'skills/verification-before-completion', target)
                shutil.copyfile(extracted/'LICENSE', target.parent/'LICENSE')
    files = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(target.rglob('*')) if p.is_file()}
    entries.append(dict(item, files=files))
path = ROOT/'configs/enhancements.lock.json'
output = {'enhancements': entries}
if path.exists() and json.loads(path.read_text()) != output:
    raise SystemExit('Enhancement source changed; refusing to replace frozen hashes')
path.write_text(json.dumps(output, indent=2)+'\n')
print('Frozen source hashes for '+', '.join(item['id'] for item in entries))
