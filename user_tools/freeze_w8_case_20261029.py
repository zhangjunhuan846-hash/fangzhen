"""Freeze the already-seen W8 model, source identities and next-record rule."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import platform
import shutil
from datetime import datetime,timezone

ROOT=Path('.')
SOURCE=ROOT/'outputs/eis_bms_validation/stanford_w8_openloop_20261029'
OUT=ROOT/'outputs/eis_bms_validation/stanford_w8_frozen_20261029'

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    if (OUT/'manifest.json').exists():raise FileExistsError('Freeze already exists; refusing overwrite')
    OUT.mkdir(parents=True,exist_ok=True)
    artifacts=[SOURCE/'frozen_hppc_model.json', SOURCE/'openloop_metrics.csv',SOURCE/'openloop_trace.csv.gz',
       ROOT/'user_tools/validate_stanford_w8_hppc_openloop_20261029.py',ROOT/'user_tools/prepare_stanford_w8_20261029.py',
       ROOT/'user_tools/report_stanford_w8_openloop_20261029.py',ROOT/'data/public/stanford_aging_w8_candidate_20261029/manifest.json']
    records=[]
    for p in artifacts:
        target=OUT/('source_manifest.json' if p.name=='manifest.json' else p.name);shutil.copyfile(p,target);records.append({'source':str(p),'snapshot':str(target),'sha256':digest(target)})
    original_sources=json.loads((ROOT/'data/public/stanford_aging_w8_candidate_20261029/manifest.json').read_text(encoding='utf8'))
    for item in original_sources['files']:
        p=Path(item['path'])
        if digest(p)!=item['sha256_local']:raise ValueError('source SHA256 mismatch: '+str(p))
    dependencies={x:importlib.metadata.version(x) for x in ('numpy','scipy','pandas','openpyxl','impedance')}
    manifest={'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'already observed/development case; no prospective experimental claim',
       'selection_rule':'After Diag_1 and before Diag_2, choose earliest two complete post-baseline charge/rest/predischarge/UDDS cycles. Consecutive XLSX parts are concatenated; a file or window is not a cycle. Select via step/cycle/time metadata before scoring.',
       'initialization':'after full charge and rest, SOC=1 and RC polarization=0; then simulate the actual pre-discharge and complete UDDS, no measured voltage feedback',
       'input':'raw Arbin discharge current negative, model discharge current positive; duplicate times keep last; left-sample piecewise-constant RC; trapezoidal SOC current integral',
       'rc_policy':'SOC interpolation inside grid; endpoint hold and its time fraction recorded; OCV outside measured range rejected',
       'source_files':original_sources['files'],'snapshots':records,'dependencies':dependencies,'python':platform.python_version(),
       'integrity_note':'source checksums are local hashes; publisher supplied no Dropbox SHA-256',
       'eis_used':False,'bms_soc_accuracy_established':False}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf8');print(digest(OUT/'manifest.json'))
if __name__=='__main__':main()
