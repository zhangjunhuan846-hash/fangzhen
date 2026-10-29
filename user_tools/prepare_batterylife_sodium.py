"""Prepare sampled BatteryLife Na-ion charge windows from public raw CSV files."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import numpy as np
import pandas as pd


def parse_time(text):
    parts=str(text).split(':')
    if len(parts)!=3:raise ValueError('原始时间格式不正确。')
    return float(parts[0])*3600+float(parts[1])*60+float(parts[2])


def run(root,out):
    root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    result=[];audit=[]
    for path in sorted(root.glob('*.csv')):
        cell=path.stem
        data=pd.read_csv(path,encoding='gb18030',low_memory=False)
        required=['循环号','总时间(hh:mm:ss)','电流(A)','电压(V)','放电容量(Ah)']
        if not set(required)<=set(data.columns):raise ValueError('未知BatteryLife钠电原始表：'+cell)
        data['cycle']=pd.to_numeric(data['循环号'],errors='coerce')
        data['qdis']=pd.to_numeric(data['放电容量(Ah)'],errors='coerce')
        data['current']=pd.to_numeric(data['电流(A)'],errors='coerce')
        data['voltage']=pd.to_numeric(data['电压(V)'],errors='coerce')
        capacities=data.groupby('cycle')['qdis'].max().dropna()
        if 1 not in capacities or capacities.loc[1]<=0:raise ValueError(cell+'缺少首循环放电参考容量。')
        ref=float(capacities.loc[1]);count=0
        for cycle,part in data.groupby('cycle',sort=True):
            if not float(cycle).is_integer() or int(cycle)<=1 or int(cycle)%5!=1 or cycle not in capacities:continue
            part=part[(part['current']>0)&(part['voltage']>=2.95)&(part['voltage']<=3.65)]
            if len(part)<10:continue
            # Preserve temporal order and include both endpoints.
            part=part.iloc[np.unique(np.linspace(0,len(part)-1,min(100,len(part)),dtype=int))]
            times=[parse_time(x) for x in part['总时间(hh:mm:ss)']]
            if any(b<=a for a,b in zip(times,times[1:])):continue
            for t,(_,row) in zip(times,part.iterrows()):
                result.append({'cell_id':'BatteryLife-'+cell,'segment_id':str(int(cycle)),'time_s':t,
                    'current_A':float(row['current']),'voltage_V':float(row['voltage']),
                    'reference_capacity_Ah':ref,'soh':float(capacities.loc[cycle])/ref})
            count+=1
        audit.append({'cell_id':cell,'segments':count,'reference_cycle':1,'reference_discharge_Ah':ref,
                      'raw_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    if not result:raise ValueError('没有符合条件的公开数据。')
    with (out/'partial_charge.csv').open('w',encoding='utf8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(result[0]));writer.writeheader();writer.writerows(result)
    (out/'provenance.json').write_text(json.dumps({'source':'BatteryLife NA-ion raw',
        'url':'https://huggingface.co/datasets/Battery-Life/BatteryLife_Raw/tree/main/NAion',
        'citation':'Ruifeng Tan et al. BatteryLife, KDD 2025, DOI 10.1145/3711896.3737372',
        'selection':'all downloaded cells, every fifth full charge/discharge cycle after cycle 1; charging points 2.95–3.65 V; at most 100 time-ordered points',
        'soh':'same-cycle maximum recorded discharge capacity divided by first-cycle discharge capacity; not a standardized capacity check',
        'cells':audit},ensure_ascii=False,indent=2),encoding='utf8')
    return audit


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);args=p.parse_args()
    print(json.dumps(run(args.root,args.out),ensure_ascii=False))
