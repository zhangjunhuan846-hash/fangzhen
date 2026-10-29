"""Out-of-chemistry stress test using Zenodo 14359482 Figure 10."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from user_tools.validate_hardcarbon_sodium_dfn import to_csv
from user_tools.workbench.sodium_identification import run


def main():
    data=Path('data/external/zenodo_14359482');out=Path('outputs/hardcarbon_dfn_validation/dfn_zenodo_mismatch');out.mkdir(parents=True,exist_ok=True)
    curves=[]
    for file,name,role,rate in [('Fig10b.csv','C5_cycle5','train',.2),('Fig10a.csv','C20_cycle1','test',.05)]:
        # The data columns are capacity,voltage although the first header pair is reversed.
        df=pd.read_csv(data/file,sep=';',header=1).iloc[:,[2,3]].apply(pd.to_numeric,errors='coerce').dropna()
        df.columns=['capacity_mAh_g','voltage_V']
        df=df[(df.capacity_mAh_g>=0)&(df.voltage_V>1)&(df.voltage_V<5)].copy()
        df['time_s']=df.capacity_mAh_g/(150*rate)*3600
        df=df[df.time_s<=3000].drop_duplicates('time_s').sort_values('time_s')
        if len(df)<5 or df.time_s.iloc[0]!=0:raise ValueError('实测曲线时间转换失败。')
        df=df.iloc[np.unique(np.linspace(0,len(df)-1,16,dtype=int))]
        curves.extend({'curve_id':name,'role':role,'time_s':float(r.time_s),'voltage_V':float(r.voltage_V),
                       'c_rate':rate,'temperature_C':23} for r in df.itertuples())
    raw=to_csv(curves);(out/'input.csv').write_bytes(raw)
    result=run(raw,{'max_nfev':20},out)
    result['source_url']='https://zenodo.org/records/14359482'
    result['paper_url']='https://doi.org/10.1002/batt.202500015'
    result['source_sha256']={f:hashlib.sha256((data/f).read_bytes()).hexdigest() for f in ['Fig10a.csv','Fig10b.csv']}
    result['qualification']='NaMnHCF/HC full-cell data differ from NVPF/HC model chemistry; nominal C-rate reference differs, initial states are not demonstrated equivalent, and train/test are different cycles, not different cells. Time inferred from specific capacity / stated specific current. Mismatch test only.'
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
