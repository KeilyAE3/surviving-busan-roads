"""Shared deterministic I/O. Source files are read only; no network access."""
from pathlib import Path
import hashlib
import json
import math
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw'

def clean(value):
    if isinstance(value, dict): return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [clean(v) for v in value]
    if hasattr(value, 'item'): value = value.item()
    if value is None or value is pd.NA: return None
    if isinstance(value, float) and not math.isfinite(value): return None
    return value

def js(value):
    return json.dumps(clean(value), ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()

def read_csv(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding='utf-8-sig')

def write_csv(path, frame):
    frame.to_csv(path, index=False, encoding='utf-8-sig', na_rep='', lineterminator='\n')

def verify_sources():
    entries = {}
    for folder in ['national_node_link', 'hd_map', 'view_t', 'busan_link_traffic']:
        base = RAW / folder
        for name in ['SOURCE_MANIFEST.json', 'REFERENCE_MANIFEST.json', 'ADOPTION_MANIFEST.json']:
            manifest = base / name
            if not manifest.exists(): continue
            entries[manifest.relative_to(ROOT).as_posix()] = sha(manifest)
            data = json.loads(manifest.read_text(encoding='utf-8-sig'))
            for row in data['files']:
                path = (base / row['path']).resolve()
                if not path.is_relative_to(base.resolve()): raise ValueError('Unsafe manifest path')
                assert path.stat().st_size == row['bytes'], f'Source size changed: {path.name}'
                digest = sha(path)
                assert digest == row['sha256'], f'Source hash changed: {path.name}'
                entries[path.relative_to(ROOT).as_posix()] = digest
    return entries

def status(source, version, match, fields, **extra):
    return js(dict(schema_version='1', defaults=dict(source=source, version=version, match=match,
                   status='source_value', unit=None), fields=fields, **extra))
