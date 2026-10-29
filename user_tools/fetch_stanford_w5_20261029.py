"""Retrieve W5 Diag_2 and first two Cycling_2 parts; pairing not presumed."""
from pathlib import Path
import hashlib
import json
import requests
from user_tools.fetch_stanford_aging_case_20261029 import listing

OUT=Path('data/public/stanford_aging_w5_diag2_20261029')
def main():
    OUT.mkdir(parents=True,exist_ok=True);files=[];failures=[]
    specs=[('diagnostic_tests/Diag_2/Capacity_test',lambda n:'_W5_' in n),
           ('diagnostic_tests/Diag_2/HPPC_test',lambda n:'_W5_' in n),
           ('cycling_tests/Cycling_2/W5',lambda n:n.endswith(('.1.xlsx','.2.xlsx')))]
    for folder,accept in specs:
        selected=[e for e in listing(folder) if accept(e['attributes']['name'])]
        if len(selected)!=(2 if folder.endswith('/W5') else 1):raise ValueError('unexpected source list: '+folder)
        for e in selected:
            dest=OUT/folder/e['attributes']['name'];dest.parent.mkdir(parents=True,exist_ok=True)
            try:
                r=requests.get(e['links']['download'],timeout=180);r.raise_for_status();raw=r.content
                if not raw.startswith(b'PK'):raise ValueError('not XLSX')
                if e['attributes']['size'] is not None and len(raw)!=e['attributes']['size']:raise ValueError('size mismatch')
                dest.write_bytes(raw);files.append({'path':str(dest),'url':e['links']['download'],'bytes':len(raw),
                    'sha256_local':hashlib.sha256(raw).hexdigest(),'publisher_sha256':e['attributes']['extra']['hashes'].get('sha256')})
                print('downloaded',dest.name,len(raw),flush=True)
            except Exception as exc:failures.append({'file':str(dest),'error':str(exc)});print('failed',dest.name,exc,flush=True)
    (OUT/'manifest.json').write_text(json.dumps({'source':'https://osf.io/qsabn/','cell':'W5','diagnostic':'Diag_2',
       'cycling':'Cycling_2','chronology':'unverified; inspect original timestamps','files':files,'failures':failures},indent=2),encoding='utf8')
    if failures:raise SystemExit(1)
if __name__=='__main__':main()
