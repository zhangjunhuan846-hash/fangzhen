"""Extract source Channel data to transparent, reproducible CSV and step summaries."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import openpyxl

ROOT=Path('data/public/stanford_aging_w8_candidate_20261029')
OUT=Path('outputs/eis_bms_validation/stanford_w8_openloop_20261029')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf8'))
    for record in manifest['files']:
        path=Path(record['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256_local']:raise ValueError('source hash changed')
        if 'EIS_test' in str(path):continue
        kind='capacity' if 'Capacity_test' in str(path) else 'hppc' if 'HPPC_test' in str(path) else 'drive'
        book=openpyxl.load_workbook(path,read_only=True,data_only=True)
        sheet=next(s for s in book if s.title.startswith('Channel_')); lines=sheet.iter_rows(values_only=True)
        header=list(next(lines));keys=['Date_Time','Test_Time(s)','Step_Time(s)','Step_Index','Cycle_Index','Voltage(V)','Current(A)','Charge_Capacity(Ah)','Discharge_Capacity(Ah)']
        idx=[header.index(k) for k in keys]
        temp=next((i for i,n in enumerate(header) if isinstance(n,str) and n.startswith('Aux_Temperature')),None)
        rows=[]
        for row in lines:
            if row[idx[1]] is None:continue
            rows.append([row[i] for i in idx]+[row[temp] if temp is not None else None])
        book.close();df=pd.DataFrame(rows,columns=['datetime','time_s','step_time_s','step','cycle','voltage_V','current_A','charge_Ah','discharge_Ah','surface_C'])
        if df.time_s.isna().any() or (np.diff(df.time_s.to_numpy(dtype=float))<0).any():raise ValueError('time invalid '+kind)
        df.to_csv(OUT/f'{kind}_source.csv.gz',index=False,compression='gzip')
        df['segment']=(df.step.ne(df.step.shift()) | df.cycle.ne(df.cycle.shift())).cumsum()
        groups=[]
        for _,g in df.groupby('segment',sort=False):
            groups.append({'kind':kind,'step':int(g.step.iloc[0]),'cycle':int(g.cycle.iloc[0]),
                'start_s':float(g.time_s.iloc[0]),'end_s':float(g.time_s.iloc[-1]),'duration_s':float(g.time_s.iloc[-1]-g.time_s.iloc[0]),
                'current_median_A':float(g.current_A.median()),'current_min_A':float(g.current_A.min()),'current_max_A':float(g.current_A.max()),
                'voltage_first_V':float(g.voltage_V.iloc[0]),'voltage_last_V':float(g.voltage_V.iloc[-1]),
                'charge_delta_Ah':float(g.charge_Ah.iloc[-1]-g.charge_Ah.iloc[0]),'discharge_delta_Ah':float(g.discharge_Ah.iloc[-1]-g.discharge_Ah.iloc[0]),
                'n':len(g)})
        pd.DataFrame(groups).to_csv(OUT/f'{kind}_step_inventory.csv',index=False)
        print(kind,len(df),'segments',len(groups),flush=True)
    (OUT/'extraction_metadata.json').write_text(json.dumps({'cell':'W8','source':'https://osf.io/qsabn/',
       'diagnostic':'Diag_1','dynamic':'Cycling_1 first file','current_sign':'Arbin raw; infer from measured charge/discharge steps',
       'scope':'raw channel time series; same cell and earlier diagnostics do not guarantee identical aging or thermal state'},indent=2),encoding='utf8')
if __name__=='__main__':main()
