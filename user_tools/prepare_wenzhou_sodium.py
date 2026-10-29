"""Prepare partial-charge experiments from Wenzhou source files; never modify sources."""
from pathlib import Path
import argparse
import csv
import json
import hashlib
import numpy as np
import pandas as pd
import fastnda


def run(root,out):
    root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    output=[];audit=[]
    for filename in sorted((root/'raw').glob('H-*.nda')):
        cell=filename.name.split('_')[0];summary=root/'summaries'/f'{cell}.xls'
        cycles=pd.read_excel(summary,sheet_name='cycle')
        capacities={int(r['循环序号']):float(r['放电容量(mAh)']) for _,r in cycles.iterrows()
                    if pd.notna(r['循环序号']) and pd.notna(r['放电容量(mAh)']) and float(r['放电容量(mAh)'])>0}
        if 1 not in capacities:raise ValueError(cell+'缺少首循环放电容量。')
        reference=capacities[1]
        data=fastnda.read(str(filename)).to_pandas()
        data=data[(data['step_type'].astype(str)=='CC_Chg') & (data['cycle_count']%10==1)]
        accepted=0
        for cycle,part in data.groupby('cycle_count',sort=True):
            cycle=int(cycle)
            if cycle not in capacities:continue
            part=part[(part['voltage_V']>=2.95)&(part['voltage_V']<=3.65)]
            if len(part)<10:continue
            # Retain endpoints and 100 time-ordered observations at most.
            take=np.unique(np.linspace(0,len(part)-1,min(100,len(part)),dtype=int));part=part.iloc[take]
            label=capacities[cycle]/reference
            for _,r in part.iterrows():
                output.append({'cell_id':cell,'segment_id':str(cycle),'time_s':float(r['total_time_s']),
                    'current_A':float(r['current_mA'])/1000,'voltage_V':float(r['voltage_V']),'soh':label})
            accepted+=1
        audit.append({'cell_id':cell,'segments_exported':accepted,'reference_cycle':1,'reference_discharge_mAh':reference,
                      'nda_sha256':hashlib.sha256(filename.read_bytes()).hexdigest(),'summary_sha256':hashlib.sha256(summary.read_bytes()).hexdigest()})
    if not output:raise ValueError('没有符合条件的原始充电数据。')
    with (out/'partial_charge.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(output[0]));writer.writeheader();writer.writerows(output)
    (out/'provenance.json').write_text(json.dumps({'source':'Wenzhou Sodium-ion Battery Degradation Data',
        'source_url':'https://github.com/lvdongzhen/Wenzhou-Sodium-ion-Battery-Degradation-Data',
        'paper':'Jiahao He et al., Transfer from lithium to sodium: promoting battery lifetime prognosis application, https://doi.org/10.2139/ssrn.5385853',
        'labels':'same-cycle discharge capacity / first-cycle discharge capacity from cycle summary; only charge data within 2.95–3.65 V used as input; every 10th cycle sampled',
        'reference':'first-cycle discharge capacity from per-cell summary; this assumes a known fresh-cell reference',
        'cells':audit},ensure_ascii=False,indent=2),encoding='utf-8')
    return audit


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
    print(json.dumps(run(args.root,args.out),ensure_ascii=False))
