"""Apply frozen W8 identification procedure to W5 diagnostic data only."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
from user_tools.workbench.engineering_stanford_frozen import fit_hppc

W8=Path('outputs/eis_bms_validation/stanford_w8_openloop_20261029')
W5=Path('outputs/eis_bms_validation/stanford_w5_diag2_20261029')

def main():
    # Verify procedure reproduces earlier W8 model before applying it to W5.
    old=json.loads((W8/'frozen_hppc_model.json').read_text(encoding='utf8'))
    check=fit_hppc(pd.read_csv(W8/'capacity_source.csv.gz'),pd.read_csv(W8/'hppc_source.csv.gz'))
    diffs=[abs(a[k]-b[k]) for a,b in zip(old['rc_nodes'],check['rc_nodes']) for k in ('soc','R0_ohm','R1_ohm','tau_s')]
    if len(old['rc_nodes'])!=len(check['rc_nodes']) or max(diffs)>1e-10:raise ValueError('W8 procedure reproduction failed')
    metadata=json.loads((W5/'diagnostic_metadata.json').read_text(encoding='utf8'))
    if max(pd.Timestamp(x['end_datetime']) for x in metadata)>=pd.Timestamp('2020-04-23 19:17:12.222'):raise ValueError('diagnosis is not earlier than cycling')
    model=fit_hppc(pd.read_csv(W5/'capacity_source.csv.gz'),pd.read_csv(W5/'hppc_source.csv.gz'))
    model.update(cell='W5',diagnostic='Diag_2',method='W8 procedure reproduced unchanged; recalibrated on W5 data',
       code_sha256=hashlib.sha256(Path('user_tools/workbench/engineering_stanford_frozen.py').read_bytes()).hexdigest())
    (W5/'frozen_hppc_model.json').write_text(json.dumps(model,indent=2),encoding='utf8')
    print(json.dumps({'capacity_Ah':model['capacity_Ah'],'nodes':len(model['rc_nodes']),
       'at_bound':sum(x['at_bound'] for x in model['rc_nodes']),'source_times':metadata,'max_W8_difference':max(diffs)},indent=2))
if __name__=='__main__':main()
