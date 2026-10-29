"""Prepare a small, vehicle-held-out official generated-data smoke fixture.

Data stays in ignored data/. This is not a reproduction of the full benchmark.
Requires py7zr only for this local acquisition helper, not the workbench.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath


def prepare(root):
    import py7zr
    archive = root / 'V1.0.7z'
    destination = root / 'ch_selected'
    destination.mkdir(exist_ok=True)
    selected = []
    with py7zr.SevenZipFile(archive) as handle:
        names = handle.getnames()
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name:
                raise ValueError('Archive contains an unsafe path.')
        for label in ['normal', 'high_resistance', 'low_capacity', 'self_discharge']:
            choices = [n for n in names if n.startswith('LFP/'+label+'/') and n.endswith('_charge_1.csv')]
            choices.sort(key=lambda n: hashlib.sha256(('42:'+n).encode()).hexdigest())
            if len(choices) < 6:
                raise ValueError('Insufficient vehicles for '+label)
            selected.extend((name, label, 'train' if i < 4 else 'test') for i, name in enumerate(choices[:6]))
        missing = [n for n, _, _ in selected if not (destination/n).exists()]
        if missing:
            handle.extract(path=destination, targets=missing)
    rows, sources = [], []
    for name, label, role in selected:
        raw = (destination/name).read_bytes()
        stream = io.StringIO(raw.decode('utf-8-sig'))
        original = list(csv.DictReader(stream))
        fields = ['TIME', 'SUM_CURRENT', 'SUM_VOLTAGE', 'MAX_CELL_VOLT', 'MIN_CELL_VOLT', 'MAX_TEMP', 'MIN_TEMP']
        if not original or not set(fields) <= set(original[0]):
            raise ValueError('Official data schema differs: '+name+' '+str(list(original[0]) if original else []))
        # Uniform deterministic subsample of each single charging recording;
        # do not select by label/prediction/outcome values.
        count = min(300, len(original))
        indices = sorted({round(i*(len(original)-1)/max(1, count-1)) for i in range(count)})
        for index in indices:
            row = original[index]
            rows.append({'vehicle_id': 'LFP/'+PurePosixPath(name).parts[2], 'role': role, 'label': label,
                         **{k: row[k] for k in fields}})
        sources.append({'path': name, 'role': role, 'label': label, 'sha256': hashlib.sha256(raw).hexdigest(),
                        'original_points': len(original), 'selected_indices': indices})
    output = root/'ch_fault_smoke.csv'
    with output.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader();writer.writerows(rows)
    manifest = {'source': 'https://github.com/CH-BatteryGen/dataset-warehouse/releases/tag/v1.0.0',
         'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'dataset_kind': 'official_AI_generated',
         'split': 'LFP, four train/two test vehicles per class; one charge recording per vehicle',
         'rows': len(rows), 'csv_sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'files': sources,
         'use': 'local academic smoke only; not full benchmark or real fleet validation; do not redistribute data'}
    (root/'ch_fault_smoke_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k!='files'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--root', type=Path, default=Path('data/vendor_assets'))
    prepare(parser.parse_args().root)
