"""Fetch part 5 solely to finish the next preselected W8 dynamic cycle."""
from pathlib import Path
import hashlib,json,requests
from user_tools.fetch_stanford_aging_case_20261029 import listing

OUT=Path('data/public/stanford_aging_w8_continuation_20261029')
def main():
    entries=[e for e in listing('cycling_tests/Cycling_1/W8') if e['attributes']['name'].endswith('.5.xlsx')]
    if len(entries)!=1:raise ValueError('Part 5 unavailable or ambiguous')
    e=entries[0];r=requests.get(e['links']['download'],timeout=180);r.raise_for_status();raw=r.content
    if not raw.startswith(b'PK'):raise ValueError('not XLSX')
    if e['attributes']['size'] is not None and len(raw)!=e['attributes']['size']:raise ValueError('size mismatch')
    dest=OUT/e['attributes']['name'];dest.write_bytes(raw)
    (OUT/'part5_manifest.json').write_text(json.dumps({'path':str(dest),'url':e['links']['download'],'bytes':len(raw),
        'sha256_local':hashlib.sha256(raw).hexdigest(),'publisher_sha256':e['attributes']['extra']['hashes'].get('sha256')},indent=2),encoding='utf8')
    print(dest.name,len(raw),flush=True)
if __name__=='__main__':main()
