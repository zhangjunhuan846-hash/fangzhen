"""Fetch a predeclared, cell-disjoint subset of CALB's published MAT data."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
from pathlib import Path
import hashlib
import json
import requests

ROOT=Path('data/public/calb_matched_v2')
CELLS=('59294','59485','59627','59690')
GROUPS=('c20_charge','c20_discharge','hppc_1c','hppc_c3','dv_wltp','dv_udds','dv_us06','eis_test')


def main():
    global ROOT, CELLS
    parser=argparse.ArgumentParser()
    parser.add_argument('--extra',action='store_true',help='Fetch a separate, previously unscored two-cell holdout')
    parser.add_argument('--extra2',action='store_true',help='Fetch two additional untouched cell holdouts')
    parser.add_argument('--extra3',action='store_true',help='Fetch the remaining three cell holdouts')
    args=parser.parse_args()
    if sum((args.extra,args.extra2,args.extra3))>1:raise ValueError('Choose only one holdout set')
    if args.extra:
        ROOT=Path('data/public/calb_matched_extra_v2');CELLS=('60129','60403')
    if args.extra2:
        ROOT=Path('data/public/calb_matched_extra2_v2');CELLS=('60644','60710')
    if args.extra3:
        ROOT=Path('data/public/calb_matched_extra3_v2');CELLS=('59861','60031','60195')
    dataset=requests.get('https://data.mendeley.com/public-api/datasets/ycx459r5c3',timeout=90);dataset.raise_for_status()
    folders=requests.get('https://data.mendeley.com/public-api/datasets/ycx459r5c3/folders/2',timeout=90);folders.raise_for_status()
    metadata=dataset.json();byid={f['id']:f for f in folders.json()}
    selected=[]
    for entry in metadata['files']:
        if entry['filename'] not in [c+'.mat' for c in CELLS]:continue
        folder=byid.get(entry['folder_id'],{});parent=byid.get(folder.get('parent_id'),{})
        group=folder.get('name','').lower();temp=parent.get('name','')
        if group in GROUPS and temp in ('Temperature_10C','Temperature_25C','Temperature_40C'):
            selected.append({'cell':entry['filename'][:-4],'temperature':temp,'group':group,
               'url':entry['content_details']['download_url'],'sha256':entry['content_details']['sha256_hash'],
               'size':entry['size'],'file_id':entry['id'],
               'path':(ROOT/temp/group/entry['filename']).as_posix()})
    if len(selected)!=len(CELLS)*3*len(GROUPS):raise ValueError(f'Expected {len(CELLS)*3*len(GROUPS)} unique files, got {len(selected)}')
    if len({x['path'] for x in selected})!=len(selected):raise ValueError('Duplicate file path')
    def fetch(item):
        p=Path(item['path']);p.parent.mkdir(parents=True,exist_ok=True)
        if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']:return
        response=requests.get(item['url'],timeout=180);response.raise_for_status();raw=response.content
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Publisher SHA mismatch: '+str(p))
        p.write_bytes(raw)
    failures=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending={pool.submit(fetch,x):x for x in selected}
        for index,future in enumerate(as_completed(pending),1):
            try:future.result()
            except Exception as exc:failures.append({'path':pending[future]['path'],'error':str(exc)})
            if index%12==0:print(f'{index}/{len(selected)} files attempted; failures={len(failures)}',flush=True)
    ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/'manifest.json').write_text(json.dumps({'source':'https://doi.org/10.17632/ycx459r5c3.2',
        'license':'CC BY 4.0','cells':CELLS,'files':selected,'failures':failures},indent=2),encoding='utf8')
    if failures:raise RuntimeError(f'Download failures: {failures}')


if __name__=='__main__':main()
