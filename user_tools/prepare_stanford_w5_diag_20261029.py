"""Extract W5 Diag_2 capacity and HPPC, recording source times and hashes."""
from pathlib import Path
import hashlib,json
from user_tools.extract_stanford_parts_20261029 import read_channel

ROOT=Path('data/public/stanford_aging_w5_diag2_20261029')
OUT=Path('outputs/eis_bms_validation/stanford_w5_diag2_20261029')
def main():
    OUT.mkdir(parents=True,exist_ok=True);manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf8'))
    if manifest['failures']:raise ValueError('incomplete W5 download')
    result=[]
    for r in manifest['files']:
        path=Path(r['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=r['sha256_local']:raise ValueError('source hash mismatch')
        if 'diagnostic_tests' not in str(path):continue
        kind='capacity' if 'Capacity_test' in str(path) else 'hppc'
        d=read_channel(path);d.to_csv(OUT/f'{kind}_source.csv.gz',index=False,compression='gzip')
        result.append({'kind':kind,'source':str(path),'sha256':r['sha256_local'],'rows':len(d),
          'start_datetime':str(d.datetime.iloc[0]),'end_datetime':str(d.datetime.iloc[-1])})
        print(kind,result[-1],flush=True)
    (OUT/'diagnostic_metadata.json').write_text(json.dumps(result,indent=2),encoding='utf8')
if __name__=='__main__':main()
