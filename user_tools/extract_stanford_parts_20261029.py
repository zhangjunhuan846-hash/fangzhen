"""Extract consecutive workbook parts with per-part provenance and step inventories."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import pandas as pd
import openpyxl

OUT=Path('outputs/eis_bms_validation/stanford_cycle_parts_20261029')

def read_channel(path):
    wb=openpyxl.load_workbook(path,read_only=True,data_only=True)
    sheet=next(s for s in wb if s.title.startswith('Channel_'));it=sheet.iter_rows(values_only=True);header=list(next(it))
    keys=['Date_Time','Test_Time(s)','Step_Time(s)','Step_Index','Cycle_Index','Voltage(V)','Current(A)','Charge_Capacity(Ah)','Discharge_Capacity(Ah)']
    indexes=[header.index(k) for k in keys];temp=next((i for i,x in enumerate(header) if isinstance(x,str) and x.startswith('Aux_Temperature')),None)
    rows=[]
    for values in it:
        if values[indexes[1]] is not None:rows.append([values[i] for i in indexes]+[values[temp] if temp is not None else None])
    wb.close()
    return pd.DataFrame(rows,columns=['datetime','time_s','step_time_s','step','cycle','voltage_V','current_A','charge_Ah','discharge_Ah','surface_C'])

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cell',choices=('W8','W5'),required=True);parser.add_argument('--only',type=int);args=parser.parse_args()
    roots=[Path('data/public/stanford_aging_w8_candidate_20261029/cycling_tests/Cycling_1/W8'),Path('data/public/stanford_aging_w8_continuation_20261029')] if args.cell=='W8' else [Path('data/public/stanford_aging_w5_diag2_20261029/cycling_tests/Cycling_2/W5')]
    dest=OUT/args.cell;dest.mkdir(parents=True,exist_ok=True);records=[]
    for path in sorted([p for root in roots for p in root.glob('*.xlsx')],key=lambda p:int(re.search(r'\.(\d+)\.xlsx$',p.name).group(1))):
        part=int(re.search(r'\.(\d+)\.xlsx$',path.name).group(1))
        if args.only is not None and part!=args.only:continue
        sha=hashlib.sha256(path.read_bytes()).hexdigest();data=read_channel(path)
        if data.time_s.isna().any() or (data.time_s.diff().dropna()<0).any():raise ValueError('time reversal '+str(path))
        csvpath=dest/f'part_{part:02d}.csv.gz';data.to_csv(csvpath,index=False,compression='gzip')
        data['group']=(data.step.ne(data.step.shift())|data.cycle.ne(data.cycle.shift())).cumsum()
        for _,g in data.groupby('group',sort=False):
            records.append({'part':part,'source':str(path),'sha256':sha,'step':int(g.step.iloc[0]),'cycle':int(g.cycle.iloc[0]),
               'first_time_s':float(g.time_s.iloc[0]),'last_time_s':float(g.time_s.iloc[-1]),
               'first_datetime':str(g.datetime.iloc[0]),'last_datetime':str(g.datetime.iloc[-1]),'rows':len(g)})
        print(args.cell,'part',part,'rows',len(data),flush=True)
    pd.DataFrame(records).to_csv(dest/(f'part_{args.only:02d}_step_inventory.csv' if args.only is not None else 'part_step_inventory.csv'),index=False)
    print(json.dumps({'cell':args.cell,'parts':len({r['part'] for r in records})}))
if __name__=='__main__':main()
