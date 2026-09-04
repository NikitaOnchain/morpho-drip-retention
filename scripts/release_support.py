"""Portable release helpers; no network or workspace fallback."""
from pathlib import Path
import hashlib
import json
import os


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def require(value, message):
    if not value:
        raise RuntimeError(message)


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.part')
    with tmp.open('w', encoding='utf8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def verify_accepted(root, item):
    """Do not substitute a release hash into the frozen Phase 7 manifest."""
    actual = sha(root / item['path'])
    if actual == item['sha256']:
        return
    mapping = json.loads((root/'release/derivative_manifest.json').read_text(encoding='utf8'))
    matches = [r for r in mapping['derivatives'] if r['path'] == item['path']
               and r['original_sha256'] == item['sha256'] and r['release_sha256'] == actual]
    require(len(matches) == 1, 'Unmapped accepted artifact: '+item['path'])


def verify_package(root):
    manifest = json.loads((root/'release/manifest.json').read_text(encoding='utf8'))
    for item in manifest['files']:
        require(sha(root/item['path']) == item['sha256'], 'Package hash mismatch: '+item['path'])
    return manifest
