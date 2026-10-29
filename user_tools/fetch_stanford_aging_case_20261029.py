"""Fetch a bounded W8/Diag_1/Cycling_1 candidate from the author's OSF Dropbox.

File membership is not proof of chronological or state matching.
"""
from pathlib import Path
import hashlib
import json
import os
import requests

BASE='https://api.osf.io/v2/nodes/qsabn/files/dropbox/'
TOKEN=os.environ.get('STANFORD_OSF_VIEW_ONLY', '')
OUT=Path('data/public/stanford_aging_w8_candidate_20261029')

def listing(folder):
    url=BASE+folder+'/'
    params={'page[size]':100}
    if TOKEN:
        params['view_only']=TOKEN
    rows=[]
    while url:
        response=requests.get(url,params=params,timeout=70);response.raise_for_status()
        page=response.json();rows.extend(page['data']);url=page['links']['next'];params=None
    return rows

def main():
    specifications=[('diagnostic_tests/Diag_1/Capacity_test',lambda n:'_W8_' in n),
       ('diagnostic_tests/Diag_1/HPPC_test',lambda n:'_W8_' in n),
       ('diagnostic_tests/Diag_1/EIS_test',lambda n:'_W8_' in n),
       ('cycling_tests/Cycling_1/W8',lambda n:n.endswith('.1.xlsx'))]
    OUT.mkdir(parents=True,exist_ok=True); manifest=[];failures=[]
    for folder,accept in specifications:
        selected=[e for e in listing(folder) if accept(e['attributes']['name'])]
        expected=3 if 'EIS_test' in folder else 1
        if len(selected)!=expected: raise ValueError(f'{folder}: expected {expected}, found {len(selected)}')
        for entry in selected:
            name=entry['attributes']['name']; dest=OUT/folder/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            try:
                r=requests.get(entry['links']['download'],timeout=180);r.raise_for_status()
                raw=r.content; expected_size=entry['attributes'].get('size')
                if expected_size is not None and len(raw)!=expected_size: raise ValueError('publisher size mismatch')
                if not raw.startswith(b'PK'): raise ValueError('response is not an XLSX ZIP')
                dest.write_bytes(raw)
                manifest.append({'path':str(dest),'source':entry['links']['download'],
                    'published_size':expected_size,'bytes':len(raw),'sha256_local':hashlib.sha256(raw).hexdigest(),
                    'publisher_sha256':entry['attributes']['extra']['hashes'].get('sha256')})
                print('downloaded',name,len(raw),flush=True)
            except Exception as exc:
                failures.append({'file':name,'error':str(exc)});print('failed',name,exc,flush=True)
    (OUT/'manifest.json').write_text(json.dumps({'source':'https://osf.io/qsabn/',
       'candidate_cell':'W8','diagnostic':'Diag_1','cycling':'Cycling_1',
       'chronology':'unverified: inspect protocol and timestamps before using for prospective prediction',
       'integrity':'local SHA256; upstream did not provide hashes for Dropbox entries',
       'files':manifest,'failures':failures},indent=2),encoding='utf8')
    if failures: raise SystemExit(1)
if __name__=='__main__': main()
