"""Fetch next sequential W8 files to establish true cycle boundaries."""
from pathlib import Path
import hashlib
import json
import requests
from user_tools.fetch_stanford_aging_case_20261029 import listing

OUT=Path('data/public/stanford_aging_w8_continuation_20261029')
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    entries=listing('cycling_tests/Cycling_1/W8')
    chosen=[e for e in entries if e['attributes']['name'].endswith(('.2.xlsx','.3.xlsx','.4.xlsx'))]
    if len(chosen)!=3:raise ValueError('Expected exactly sequential files 2, 3, 4')
    files=[];failures=[]
    for entry in sorted(chosen,key=lambda x:x['attributes']['name']):
        dest=OUT/entry['attributes']['name']
        try:
            r=requests.get(entry['links']['download'],timeout=180);r.raise_for_status();data=r.content
            if not data.startswith(b'PK'):raise ValueError('not XLSX')
            size=entry['attributes']['size']
            if size is not None and len(data)!=size:raise ValueError('size mismatch')
            dest.write_bytes(data)
            files.append({'path':str(dest),'url':entry['links']['download'],'bytes':len(data),
                          'sha256_local':hashlib.sha256(data).hexdigest(),'publisher_sha256':entry['attributes']['extra']['hashes'].get('sha256')})
            print('downloaded',dest.name,len(data),flush=True)
        except Exception as exc:failures.append({'name':dest.name,'error':str(exc)});print('failed',dest.name,exc,flush=True)
    (OUT/'manifest.json').write_text(json.dumps({'source':'https://osf.io/qsabn/','files':files,'failures':failures,
       'note':'Consecutive parts, not assumed independent cycles; publisher hash unavailable'},indent=2),encoding='utf8')
    if failures:raise SystemExit(1)
if __name__=='__main__':main()
