"""Preselect complete step sequences using time/step metadata, before scoring."""
from pathlib import Path
import hashlib
import json
import pandas as pd

ROOT=Path('outputs/eis_bms_validation/stanford_cycle_parts_20261029/W8')
OUT=Path('outputs/eis_bms_validation/stanford_w8_new_cycles_20261029')
FREEZE=Path('outputs/eis_bms_validation/stanford_w8_frozen_20261029')

def main():
    OUT.mkdir(parents=True,exist_ok=True);dest=OUT/'selection.json'
    if dest.exists():raise FileExistsError('selection already exists; do not silently reselect')
    paths=sorted(ROOT.glob('part_*.csv.gz'))
    if not paths:raise ValueError('no extracted parts')
    # No voltage or current data are read to select the records.
    d=pd.concat([pd.read_csv(p,usecols=['time_s','datetime','step','cycle']).assign(part=int(p.name[5:7])) for p in paths],ignore_index=True)
    if (d.time_s.diff().dropna()<0).any():raise ValueError('source parts not chronological')
    d=d.drop_duplicates('time_s',keep='last').reset_index(drop=True)
    d['group']=(d.step.ne(d.step.shift())|d.cycle.ne(d.cycle.shift())).cumsum()
    groups=[]
    for _,g in d.groupby('group',sort=False):
        groups.append({'step':int(g.step.iloc[0]),'cycle':int(g.cycle.iloc[0]),'start_s':float(g.time_s.iloc[0]),
             'end_s':float(g.time_s.iloc[-1]),'start_datetime':str(g.datetime.iloc[0]),'end_datetime':str(g.datetime.iloc[-1]),
             'parts':sorted([int(x) for x in g.part.unique()])})
    complete=[]
    for i,g in enumerate(groups):
        if g['step']!=14 or i<2 or i+1>=len(groups):continue
        pre,rest,after=groups[i-1],groups[i-2],groups[i+1]
        if pre['step']==13 and rest['step'] in (4,11) and after['step']==7:
            complete.append({'order':len(complete)+1,'rest':rest,'predischarge':pre,'dynamic':g,'next_step':after,
                             'classification':'partly observed development cycle' if len(complete)==0 else 'subsequent same-cell protocol cycle'})
    if len(complete)<2:raise ValueError('Need at least one later complete cycle')
    chosen=complete[:3]
    manifest={'selection_rule':'earliest two complete step 13->14->7 cycles after the already-seen first cycle; require preceding step 4 or 11 rest',
       'selection_uses_voltage':False,'selection_uses_current':False,'baseline_and_selected':chosen,
       'only_one_later_available':len(chosen)<3,'freeze_manifest_sha256':hashlib.sha256((FREEZE/'manifest.json').read_bytes()).hexdigest(),
       'frozen_model_sha256':hashlib.sha256((FREEZE/'frozen_hppc_model.json').read_bytes()).hexdigest(),
       'replay_code_sha256':hashlib.sha256(Path('user_tools/workbench/engineering_stanford_frozen.py').read_bytes()).hexdigest(),
       'part_files':[{'file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
       'scope':'metadata-only selection; same cell, same cycling test; not independent cells or new external experiment'}
    dest.write_text(json.dumps(manifest,indent=2),encoding='utf8');print(json.dumps(chosen,indent=2))
if __name__=='__main__':main()
