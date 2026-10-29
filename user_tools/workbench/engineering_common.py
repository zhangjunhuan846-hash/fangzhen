"""Artifact and provenance helpers for real optional backends."""
from __future__ import annotations
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]


def clean(value):
    import numpy as np
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not np.isfinite(value):
        raise ValueError('数值结果含NaN/Infinity，任务未通过。')
    return value


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def write_csv(path, rows):
    if not rows:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(clean(rows))


def versions(names):
    result = {'python': sys.version.split()[0]}
    for name in names:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = 'source checkout'
    return result


def finish(config, out, result, rows=None, curves=None, packages=()):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if rows:
        write_csv(out / 'engineering.csv', rows)
    result.update(action=config['action'], evidence_type=('synthetic_engineering_demo' if config['data_origin'] == 'synthetic'
                  else 'public_engineering_replay' if config['data_origin'] == 'public' else 'user_engineering_analysis'),
                  data_origin=config['data_origin'], source=config.get('source', '解析/程序生成的合成软件算例'),
                  runtime_versions=versions(packages), material_validation=False, hardware_connected=False)
    result['code_sha256'] = {}
    snapshot_dir=out/'code_snapshot';snapshot_dir.mkdir(exist_ok=True)
    for p in list(Path(__file__).parent.glob('engineering_*.py'))+[Path(__file__).with_name('hardware_readiness.py')]:
        raw=p.read_bytes();result['code_sha256'][p.name]=hashlib.sha256(raw).hexdigest()
        (snapshot_dir/p.name).write_bytes(raw)
    if config.get('source_sha256'):
        result['source_sha256'] = config['source_sha256']
    if config.get('eis_parameter_source'):
        result['eis_parameter_source'] = config['eis_parameter_source']
    if config.get('eis_grid_source'):
        result['eis_grid_source'] = config['eis_grid_source']
    if config.get('telemetry_parameter_source'):
        result['telemetry_parameter_source'] = config['telemetry_parameter_source']
    if config.get('adaptive_parameter_source'):
        result['adaptive_parameter_source'] = config['adaptive_parameter_source']
    manifest = ROOT / 'data/engineering_runtime.local.json'
    if manifest.exists():
        snapshot = manifest.read_bytes()
        (out/'dependency_manifest.json').write_bytes(snapshot)
        result['dependency_manifest_sha256'] = hashlib.sha256(snapshot).hexdigest()
    result = clean(result)
    save(out / 'result.json', result)
    save(out / 'ui_result.json', {'result': result, 'curves': curves or []})
    return result
