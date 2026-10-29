"""Select first complete W5 cycle from step/time metadata without voltage."""
from pathlib import Path
import hashlib,json
import pandas as pd

ROOT=Path('outputs/eis_bms_validation/stanford_cycle_parts_20261029/W5')
OUT=Path('outputs/eis_bms_validation/stanford_w5_diag2_20261029')
def main():
    dest=OUT/'selection.json'
    if dest.exists():raise FileExistsError('selection already exists')
    paths=sorted(ROOT.glob('part_*.csv.gz'))
    d=pd.concat([pd.read_csv(p,usecols=['time_s','datetime','step','cycle']).assign(part=int(p.name[5:7])) for p in paths],ignore_index=True)
    if (d.time_s.diff().dropna()<0).any():raise ValueError('time reversal')
    d=d.drop_duplicates('time_s',keep='last').reset_index(drop=True)
    d['group']=(d.step.ne(d.step.shift())|d.cycle.ne(d.cycle.shift())).cumsum();groups=[]
    for _,g in d.groupby('group',sort=False):
        groups.append({'step':int(g.step.iloc[0]),'start_s':float(g.time_s.iloc[0]),'end_s':float(g.time_s.iloc[-1]),
           'start_datetime':str(g.datetime.iloc[0]),'end_datetime':str(g.datetime.iloc[-1]),'parts':sorted([int(x) for x in g.part.unique()])})
    candidates=[]
    for i,g in enumerate(groups):
        if g['step']==14 and i>=2 and i+1<len(groups) and groups[i-1]['step']==13 and groups[i-2]['step'] in (4,11) and groups[i+1]['step']==7:
            candidates.append({'rest':groups[i-2],'predischarge':groups[i-1],'dynamic':g,'next_step':groups[i+1]})
    if not candidates:raise ValueError('No complete W5 cycle')
    model=OUT/'frozen_hppc_model.json';code=Path('user_tools/workbench/engineering_stanford_frozen.py')
    selection={'selection_rule':'first complete rest -> predischarge -> dynamic -> next charge after Diag_2',
       'selection_uses_voltage':False,'selection_uses_current':False,'cycle':candidates[0],
       'frozen_model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
       'replay_code_sha256':hashlib.sha256(code.read_bytes()).hexdigest(),
       'parts':[{'file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
       'scope':'same methodology, new W5 cell calibrated using its own capacity and HPPC; no EIS'}
    dest.write_text(json.dumps(selection,indent=2),encoding='utf8');print(json.dumps(selection['cycle'],indent=2))
if __name__=='__main__':main()
