"""Prepare pinned public observations; never uses a holdout to calibrate a model."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))


def panasonic():
    """Use official individual files; the publisher's bulk ZIP may return HTTP403."""
    root=ROOT/'data/public/panasonic_pf_v1';root.mkdir(parents=True,exist_ok=True)
    manifest_path=root/'download_manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else dict(
        source='https://data.mendeley.com/datasets/wykht8y7tg/1',license='CC BY 4.0',files=[])
    folders={
      '96f196a8-a04d-4e6a-827d-0dc4d61ca97b':'Panasonic 18650PF Data',
      '5c3c2acd-d581-4295-b86c-52c73f1ac76d':'25degC/5 pulse disch',
      'a419c649-06e2-4980-9863-5ade6fc8c9ab':'25degC/C20 OCV and 1C discharge tests_start_of_tests',
      'b71a31f8-ba51-4bf1-8161-3ff549780cc4':'25degC/Drive cycles',
      '980735d1-c04c-406a-a85d-bb94f1b9a8c4':'25degC/EIS'}
    for folder,relative in folders.items():
        url='https://data.mendeley.com/public-api/datasets/wykht8y7tg/files?folder_id='+folder+'&version=1&$start=0&$limit=1000'
        request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/vnd.mendeley-public-dataset.1+json'})
        data=json.load(urllib.request.urlopen(request,timeout=60));files=data if isinstance(data,list) else data['data']
        for item in files:
            name=item['filename']
            if not name.endswith(('.mat','.csv','.txt')):continue
            details=item['content_details'];sha=details['sha256_hash']
            if any(r['sha256']==sha and ((ROOT/Path(r['path'])) if r['path'].startswith('data/') else root/Path(r['path'])).exists() for r in manifest['files']):continue
            download=urllib.request.Request(details['download_url'],headers={'User-Agent':'Mozilla/5.0'})
            raw=urllib.request.urlopen(download,timeout=120).read()
            if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Publisher hash mismatch: '+name)
            target=root/relative/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            manifest['files'].append(dict(name=relative+'/'+name,path=target.relative_to(root).as_posix(),sha256=sha,expected_sha256=sha,size=len(raw)))
            save(manifest_path,manifest);print(name,sha,flush=True)
    save(manifest_path,manifest);july()


def july():
    root = ROOT/'data/public/panasonic_pf_v1'
    url = 'https://data.mendeley.com/public-api/datasets/wykht8y7tg/files?folder_id=fa412154-4c43-4468-af35-2b527892f526&version=1&$start=0&$limit=1000'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/vnd.mendeley-public-dataset.1+json'})
    response = json.load(urllib.request.urlopen(req, timeout=60))
    files = response if isinstance(response, list) else response['data']
    manifest = json.loads((root/'download_manifest.json').read_text(encoding='utf-8'))
    for item in files:
        name = item['filename']
        if not name.endswith('.mat') or '1C' not in name: continue
        details = item['content_details']
        target = root/'25degC/C20 OCV Test_end_of_tests'/name
        if target.exists(): raw = target.read_bytes()
        else:
            download = urllib.request.Request(details['download_url'], headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.mendeley.com/datasets/wykht8y7tg/1'})
            raw = urllib.request.urlopen(download, timeout=120).read()
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        if sha != details['sha256_hash']: raise ValueError('Public file hash mismatch')
        record = dict(path=target.relative_to(root).as_posix(), name=name, sha256=sha, expected_sha256=sha, size=len(raw))
        if not any(a.get('path') == record['path'] for a in manifest['files']): manifest['files'].append(record)
        print(name, len(raw), sha, flush=True)
    save(root/'download_manifest.json', manifest)


def hust():
    # The scientific publisher distributes trusted pickle objects. Deserialize only this
    # fixed local publisher archive in the preparation process; UI never loads pickle.
    import pickle
    import zipfile
    import numpy as np
    archive = ROOT/'data/public/hust_raw/nsc7hnsg4s-2/our_data.zip'
    target = ROOT/'data/public/hust_batterylife'
    z = zipfile.ZipFile(archive)
    records, features, labels, roles, ids = [], [], [], [], []
    for name in sorted(n for n in z.namelist() if n.endswith('.pkl')):
        if Path(name).stem == '7-5': continue  # official upstream flags first2cycles as problematic
        raw = z.read(name); data = pickle.loads(raw)
        cell_id = Path(name).stem; cell = data[cell_id]
        curves = []
        for cycle in range(1, 11):
            frame = cell['data'][cycle]
            segments = []
            for phase in ['charge', 'discharge']:
                mask = frame['Status'].str.contains(phase, case=False) & ~frame['Status'].str.contains('discharge' if phase=='charge' else 'rest', case=False)
                block = frame[mask]
                if len(block) < 5: raise ValueError('Missing early-cycle segment: '+cell_id)
                t = block['Time (s)'].to_numpy(dtype=float); t = t-t[0]
                cols = ['Voltage (V)', 'Current (mA)', 'Capacity (mAh)']
                segments.append(np.asarray([np.interp(np.linspace(0, t[-1], 32), t, block[c].to_numpy(dtype=float)) for c in cols]))
            curves.append(np.concatenate(segments, axis=1))
        feat = np.asarray(curves); feat[:, 1:, :] /= 1000
        group = int(cell_id.split('-')[0]); role = 'train' if group <= 6 else 'validation' if group <= 8 else 'test'
        life = float(cell['rul'][10])
        ids.append(cell_id); roles.append(role); features.append(feat); labels.append(life)
        records.append(dict(cell_id=cell_id, role=role, raw_path=name, raw_sha256=hashlib.sha256(raw).hexdigest(),
                            feature_cycles=[1, 10], prediction_cycle=10, label='publisher RUL at cycle 10', label_cycles=life))
        print(cell_id, role, life, flush=True)
    target.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(target/'early10.npz', features=np.asarray(features, dtype=np.float32), labels=np.asarray(labels),
                        roles=np.asarray(roles), cell_ids=np.asarray(ids))
    save(target/'manifest.json', {'source': 'https://data.mendeley.com/datasets/nsc7hnsg4s/2', 'license': 'CC BY 4.0',
          'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
          'npz_sha256': hashlib.sha256((target/'early10.npz').read_bytes()).hexdigest(),
          'channels': ['voltage_V', 'current_A', 'capacity_Ah'], 'shape': [len(ids), 10, 3, 64],
          'split_policy': 'physical cell disjoint, protocol groups 1-6 train, 7-8 validation, 9-10 test; frozen before training',
          'curve_policy': 'first 10 cycles, time-resample charge/discharge separately to 32+32 points; no future curves',
          'exclusions': {'7-5':'Official BatteryLife preprocessing flags the first2cycles as problematic; excluded before model training'},
          'records': records})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('dataset', choices=['panasonic', 'july', 'hust']); args = parser.parse_args()
    {'panasonic':panasonic,'july':july,'hust':hust}[args.dataset]()
