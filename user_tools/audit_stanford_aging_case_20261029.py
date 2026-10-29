"""Read absolute timestamps from selected original W8 workbooks (no state-matching claim)."""
from pathlib import Path
import csv
import hashlib
import json
import openpyxl

ROOT=Path('data/public/stanford_aging_w8_candidate_20261029')
OUT=Path('outputs/eis_bms_validation/stanford_aging_w8_audit_20261029')

def main():
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf8'))
    rows=[]
    for f in manifest['files']:
        path=Path(f['path']); digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=f['sha256_local']: raise ValueError('local file changed: '+str(path))
        wb=openpyxl.load_workbook(path,read_only=True,data_only=True)
        for sheet in wb:
            if not (sheet.title.startswith('Channel_') or sheet.title.startswith('ACIM_')): continue
            stream=sheet.iter_rows(values_only=True);header=list(next(stream));
            date_indices=[i for i,x in enumerate(header) if isinstance(x,str) and ('Date_Time' in x or 'Date Time' in x)]
            first=last=None;count=0
            for values in stream:
                count+=1
                if date_indices:
                    date=values[date_indices[0]]
                    if date is not None:
                        if first is None:first=date
                        last=date
            rows.append({'file':str(path),'sha256':digest,'sheet':sheet.title,'rows':count,
                'start_datetime':str(first) if first is not None else '',
                'end_datetime':str(last) if last is not None else '',
                'datetime_available':bool(first is not None),
                'condition':'same ID and stage are necessary, but SOC/rest/aging match not established'})
        wb.close()
        print(path.name,flush=True)
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'raw_time_inventory.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(json.dumps(rows,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
