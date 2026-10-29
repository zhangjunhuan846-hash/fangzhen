"""Download a fixed public calibration/holdout split without decoding held-out signals."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    metadata=ROOT/'data/vendor_assets/panasonic_pf_multitemp_files.json'
    if metadata.exists():records=json.loads(metadata.read_text(encoding='utf-8'))
    else:
        records=[]
        folders={'10degC/pulses':'6a8e1a6d-bfa0-4af9-b88d-8f33721da4a8','10degC/drives':'a3d76246-2f07-4d2e-af7b-db42f7d4e669',
                 '0degC/pulses':'33ea6b7c-daf7-4cd3-a8b0-cafd7f7815bf','0degC/drives':'db58eb9f-5b01-4079-9d57-716f0e25f717'}
        for group,folder in folders.items():
            request=urllib.request.Request('https://data.mendeley.com/public-api/datasets/wykht8y7tg/files?folder_id='+folder+'&version=1&$start=0&$limit=1000',headers={'User-Agent':'Mozilla/5.0','Accept':'application/vnd.mendeley-public-dataset.1+json'})
            data=json.load(urllib.request.urlopen(request,timeout=60));items=data if isinstance(data,list) else data['data']
            for item in items:
                if item['filename'].endswith('.mat'):item['group']=group;records.append(item)
        metadata.parent.mkdir(parents=True,exist_ok=True);metadata.write_bytes(json.dumps(records,indent=2).encode('utf-8'))
    selected=[]
    for item in records:
        name=item['filename']; lower=name.lower()
        if ('hppc' in lower or 'Cycle_1_Pan' in name or any(k in name for k in ['US06_Pan','UDDS_Pan','LA92_Pan'])):
            selected.append(item)
    if len(selected)!=10:raise ValueError('Expected2HPPC+2selection+6holdout files')
    root=ROOT/'data/public/panasonic_pf_multitemp_v1';root.mkdir(parents=True,exist_ok=True)
    def download(item):
        target=root/item['group']/item['filename'];details=item['content_details']
        if target.exists():raw=target.read_bytes()
        else:
            request=urllib.request.Request(details['download_url'],headers={'User-Agent':'Mozilla/5.0'})
            raw=urllib.request.urlopen(request,timeout=120).read()
            if hashlib.sha256(raw).hexdigest()!=details['sha256_hash']:raise ValueError('Publisher checksum mismatch')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        sha=hashlib.sha256(raw).hexdigest()
        if sha!=details['sha256_hash']:raise ValueError('Local checksum mismatch')
        role='calibration' if 'hppc' in item['filename'].lower() else 'selection' if 'Cycle_1_Pan' in item['filename'] else 'fresh_condition_holdout'
        print(role,item['filename'],flush=True)
        return dict(path=target.relative_to(ROOT).as_posix(),group=item['group'],role=role,sha256=sha,expected_sha256=sha,bytes=len(raw),decoded_during_download=False)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:files=list(pool.map(download,selected))
    manifest=dict(source='https://data.mendeley.com/datasets/wykht8y7tg/1',license='CC BY4.0',files=files,
                  protocol_sha256=hashlib.sha256((ROOT/'configs/commercial_pf_adaptive_20261029.json').read_bytes()).hexdigest())
    (root/'download_manifest.json').write_bytes(json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8'))


if __name__=='__main__':main()
