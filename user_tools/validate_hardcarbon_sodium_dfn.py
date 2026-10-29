"""Reproducible sodium-DFN synthetic recovery and Wenzhou mismatch experiment."""
from pathlib import Path
import csv
import hashlib
import io
import json
import numpy as np
import pandas as pd
import fastnda
from user_tools.workbench.sodium_identification import simulate,run


def to_csv(rows):
    stream=io.StringIO(newline='');w=csv.DictWriter(stream,fieldnames=['curve_id','role','time_s','voltage_V','c_rate','temperature_C']);w.writeheader();w.writerows(rows)
    return stream.getvalue().encode()


def main():
    base=Path('outputs/hardcarbon_dfn_validation');base.mkdir(parents=True,exist_ok=True)
    times=np.linspace(0,300,16);records=[]
    for name,role,rate in [('train_05','train',.5),('train_08','train',.8),('test_10','test',1.)]:
        volt=simulate(rate,25,times,2.,.03)
        records.extend({'curve_id':name,'role':role,'time_s':float(t),'voltage_V':float(v),'c_rate':rate,'temperature_C':25} for t,v in zip(times,volt))
    synth=base/'dfn_synthetic';synth.mkdir(exist_ok=True);raw=to_csv(records);(synth/'input.csv').write_bytes(raw)
    result=run(raw,{'max_nfev':20},synth)
    result['known_generation']={'diffusivity_scale':2.,'effective_drop_V_per_C':.03}
    (synth/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print('synthetic',json.dumps(result,ensure_ascii=False))
    source=next(Path('data/external/wenzhou_sodium_2026/raw').glob('H-1-2*.nda'))
    dataset=fastnda.read(str(source)).to_pandas();summary=pd.read_excel('data/external/wenzhou_sodium_2026/summaries/H-1-2.xls',sheet_name='cycle')
    capacity=float(summary.loc[summary['循环序号']==1,'放电容量(mAh)'].iloc[0]);records=[]
    for cycle,role in [(1,'train'),(2,'test')]:
        f=dataset[(dataset.cycle_count==cycle)&(dataset.step_type.astype(str)=='CC_DChg')].copy()
        f=f.iloc[:61].copy();f['elapsed']=f.total_time_s-f.total_time_s.iloc[0]
        selected=f.iloc[np.unique(np.linspace(0,len(f)-1,16,dtype=int))]
        rate=float(f.current_mA.abs().median()/capacity)
        records.extend({'curve_id':'cycle_'+str(cycle),'role':role,'time_s':float(r.elapsed),'voltage_V':float(r.voltage_V),
                        'c_rate':rate,'temperature_C':25} for r in selected.itertuples())
    pub=base/'dfn_wenzhou_mismatch';pub.mkdir(exist_ok=True);raw=to_csv(records);(pub/'input.csv').write_bytes(raw)
    result=run(raw,{'max_nfev':20},pub)
    result['source']='Wenzhou Sodium-ion Battery Degradation Data'
    result['source_url']='https://github.com/lvdongzhen/Wenzhou-Sodium-ion-Battery-Degradation-Data'
    result['source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    result['qualification']='Exploratory mismatch diagnostic, not same-chemistry validation. Temperature 25C is an unverified assumption; C-rate normalized by first discharge capacity; same-cell sequential cycles are not independent cells; initial conditions not demonstrated equivalent.'
    (pub/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print('public_mismatch',json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
