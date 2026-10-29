"""Verify reusable simulator reproduces the observed, frozen W8 segment."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from user_tools.workbench.engineering_stanford_frozen import replay_frozen,time_metrics

FREEZE=Path('outputs/eis_bms_validation/stanford_w8_frozen_20261029')
OUT=Path('outputs/eis_bms_validation/stanford_w8_openloop_20261029')
def main():
    manifest=json.loads((FREEZE/'manifest.json').read_text(encoding='utf8'))
    for item in manifest['snapshots']:
        if hashlib.sha256(Path(item['snapshot']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('frozen artifact changed')
    model=json.loads((FREEZE/'frozen_hppc_model.json').read_text(encoding='utf8'))
    drive=pd.read_csv(OUT/'drive_source.csv.gz');start=drive[drive.step==4].iloc[-1]
    frame=drive[drive.time_s>=start.time_s]
    result=replay_frozen(model,frame);old=pd.read_csv(FREEZE/'openloop_trace.csv.gz')
    if len(result)!=len(old) or not np.allclose(result.time_s,old.time_s,atol=1e-8):raise ValueError('baseline timestamps do not match')
    maxdiff=float(np.max(np.abs(result.model_V-old.model_V)))
    if maxdiff>1e-9:raise ValueError('reusable model differs from frozen baseline')
    stats=time_metrics(result[result.step==14]);stats.update(max_abs_reproduction_difference_V=maxdiff,
         note='baseline is an observed file fragment, not a complete dynamic cycle')
    (OUT/'frozen_reproduction_check.json').write_text(json.dumps(stats,indent=2),encoding='utf8');print(json.dumps(stats,indent=2))
if __name__=='__main__':main()
