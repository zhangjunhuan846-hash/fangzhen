"""Check dates of next W8 diagnostic files against the selected cycles."""
from pathlib import Path
import hashlib,json,requests
import openpyxl
from user_tools.fetch_stanford_aging_case_20261029 import listing

OUT=Path('data/public/stanford_aging_w8_diag2_audit_20261029')
def main():
    OUT.mkdir(parents=True,exist_ok=True);records=[]
    for kind in ('Capacity_test','HPPC_test'):
        entries=[e for e in listing('diagnostic_tests/Diag_2/'+kind) if '_W8_' in e['attributes']['name']]
        if len(entries)!=1:raise ValueError('missing or ambiguous W8 Diag_2 '+kind)
        e=entries[0];path=OUT/e['attributes']['name'];r=requests.get(e['links']['download'],timeout=180);r.raise_for_status();raw=r.content
        if not raw.startswith(b'PK'):raise ValueError('not XLSX')
        if e['attributes']['size'] is not None and len(raw)!=e['attributes']['size']:raise ValueError('size mismatch')
        path.write_bytes(raw);wb=openpyxl.load_workbook(path,read_only=True,data_only=True);sheet=next(s for s in wb if s.title.startswith('Channel_'))
        it=sheet.iter_rows(values_only=True);header=list(next(it));idx=header.index('Date_Time');first=last=None
        for row in it:
            if row[idx] is not None:
                if first is None:first=row[idx]
                last=row[idx]
        wb.close();records.append({'kind':kind,'file':str(path),'sha256_local':hashlib.sha256(raw).hexdigest(),
           'start':str(first),'end':str(last),'source':e['links']['download'],'publisher_sha256':e['attributes']['extra']['hashes'].get('sha256')})
        print(json.dumps(records[-1]),flush=True)
    (OUT/'audit.json').write_text(json.dumps(records,indent=2),encoding='utf8')
if __name__=='__main__':main()
