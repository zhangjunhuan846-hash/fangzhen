"""TU Berlin sodium-cell EIS to independent HPPC resistance diagnostics."""
from __future__ import annotations
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile
import argparse
import numpy as np
import pandas as pd
from user_tools.workbench.engineering_contracts import defaults
from user_tools.workbench.engineering_eis_grid import run_grid


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--branches',type=int,choices=[1,2],default=1);args=parser.parse_args()
    root=Path('data/external/tu_berlin_sodium_25036');archive=root/'data_EvalSIB.zip'
    out=Path('outputs/eis_bms_validation/tu_berlin_sodium'+('_2rc' if args.branches==2 else ''));out.mkdir(parents=True,exist_ok=True)
    rows=[];manifest=[]
    with zipfile.ZipFile(archive) as z:
        names=sorted(n for n in z.namelist() if n.startswith('raw_EIS_plotting/TC23SIB03/auxiliary/') and n.endswith('_EIS.csv'))
        if len(names)!=10:raise ValueError('预期10条钠电谱。')
        for idx,name in enumerate(names):
            data=z.read(name);f=pd.read_csv(io.BytesIO(data),encoding='latin1')
            soc=(idx+1)/10;role='test' if idx in (3,6) else 'train'
            temp_col=next(c for c in f.columns if c.startswith('Temperature['))
            measured_temp=float(pd.to_numeric(f[temp_col],errors='coerce').median())
            manifest.append({'file':name,'sha256':hashlib.sha256(data).hexdigest(),'inferred_soc':soc,'role':role,'measured_temp_C':measured_temp})
            for row in f.itertuples(index=False,name=None):
                cols=dict(zip(f.columns,row))
                rows.append({'cell_id':'TC23SIB03','spectrum_id':Path(name).stem,'role':role,'soc':soc,'temperature_C':25.,
                    'frequency_Hz':cols['EISFreq[Hz]'],'Z_real_ohm':cols['Zre[Ohm]'],'Z_imag_ohm':cols['Zim[Ohm]']})
        hppc_name='data_Ri_HPPC/TC23SIB03_HPPC_dis_00.csv';hppc_raw=z.read(hppc_name)
    buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows);raw=buffer.getvalue().encode()
    (out/'eis_input.csv').write_bytes(raw)
    cfg=defaults('eis_grid');cfg.update(data_origin='public',source='https://doi.org/10.14279/depositonce-25036',source_sha256=hashlib.sha256(raw).hexdigest(),rc_branches=args.branches)
    result=run_grid(cfg,out,raw)
    hppc=pd.read_csv(io.BytesIO(hppc_raw),sep=';',encoding='latin1');hppc.columns=[x.strip() for x in hppc.columns]
    nodes=result['parameters'];socs=np.array([r['soc'] for r in nodes]);comparisons=[]
    for _,r in hppc.iterrows():
        s=float(r['SOC']);t=float(r['dt_1s']);measured=float(r['R_1s'])
        if not socs.min()<=s<=socs.max() or measured<=0 or not .8<=t<=1.2:continue
        calculated=np.interp(s,socs,[x['R0_ohm'] for x in nodes])
        for i in range(1,args.branches+1):
            r1=np.interp(s,socs,[x[f'R{i}_ohm'] for x in nodes]);c=np.interp(s,socs,[x[f'C{i}_F'] for x in nodes])
            calculated+=r1*(1-np.exp(-t/(r1*c)))
        comparisons.append({'soc':s,'pulse_time_s':t,'measured_resistance_ohm':measured,
                            'eis_rc_predicted_resistance_ohm':float(calculated),'error_ohm':float(calculated-measured)})
    if not comparisons:raise ValueError('没有可比较的HPPC一秒阻抗。')
    mae=float(np.mean([abs(x['error_ohm']) for x in comparisons]));mean=float(np.mean([x['measured_resistance_ohm'] for x in comparisons]))
    audit={'source':'https://doi.org/10.14279/depositonce-25036','paper':'https://doi.org/10.3390/batteries11110420',
        'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'hppc_file':hppc_name,'hppc_sha256':hashlib.sha256(hppc_raw).hexdigest(),
        'assignment':'10–100% SOC inferred from ascending filename OCV and author plotting legend; file has no per-spectrum explicit SOC. Nominal 25C based on paper; individual measured temperatures retained.',
        'frequency_band_Hz':[cfg['frequency_min_Hz'],cfg['frequency_max_Hz']],'source_spectra':manifest,
        'hppc_1s':{'pairs':len(comparisons),'mae_ohm':mae,'mean_measured_ohm':mean,'rows':comparisons},
        'interpretation':'EIS at one nominal temperature; RC point-to-step prediction versus processed HPPC of same cell. SOC assignment, state, temperature, 1C pulse conditions, timing and linear-perturbation differences may contribute. This is not independent cell validation or a full dynamic voltage trace.'}
    (out/'public_validation.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'grid_usable_for_replay':result['grid_usable_for_replay'],'spectra':result['spectra_summary'],
                      'hppc_1s':audit['hppc_1s']},ensure_ascii=False))


if __name__=='__main__':main()
