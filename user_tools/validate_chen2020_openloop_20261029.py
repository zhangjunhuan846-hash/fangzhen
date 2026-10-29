"""Reproduce measured-current, open-loop voltage comparisons; never tune on these curves."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import pybamm
from battery_sim.registry import get_dataset
from battery_sim.simulation.baseline import _run_one_replay

OUT = Path('outputs/chen2020_openloop_20261029')
PUBLISHER_MD5 = {'02':'0bbf959cbfc367296ec69d7a74d2f5c1',
                 '03':'a09cbd8eff0af55dfe9bc8728fa89908',
                 '04':'f17615476283d2e15087165697ff9d7c'}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    adapter=get_dataset('chen2020')
    manifest=[]
    for cell,digest in PUBLISHER_MD5.items():
        path=adapter.raw_path(cell); raw=path.read_bytes()
        if hashlib.md5(raw).hexdigest()!=digest: raise ValueError('Zenodo MD5 mismatch: '+str(path))
        manifest.append({'cell':cell,'path':str(path),'md5':digest,'sha256':hashlib.sha256(raw).hexdigest()})
    results=[]
    for cell in PUBLISHER_MD5:
        for rate in adapter.list_rates():
            # Use the verified raw input rather than a potentially stale processed copy.
            df=adapter.load_discharge(cell,rate)
            raw=adapter.load_raw(cell)
            selected=raw[(raw['Cycle C']=={'C10':2,'C2':3,'1C':4,'1p5C':5}[rate]) & (raw['Md']=='D')]
            df['temperature_ambient_C']=float(selected['Temperature Chamber [degC]'].median())
            for model in ('SPM','SPMe','DFN'):
                label={'cell':cell,'rate':rate,'model':model}
                try:
                    result=_run_one_replay(df,model_name=model,parameter_set='Chen2020')
                    trace=pd.DataFrame({'time_s':result['_t_common'],'measured_voltage_V':result['_V_exp_common'],
                         'model_voltage_V':result['_V_sim_common'],'residual_V':result['_residual']})
                    trace.to_csv(OUT/f'{cell}_{rate}_{model}.csv',index=False)
                    results.append({**label,'status':'ok',**{k:v for k,v in result.items() if not k.startswith('_')}})
                    print(cell,rate,model,round(result['rmse_time_aligned_mV'],2),round(result['coverage_fraction'],3),flush=True)
                except Exception as exc:
                    results.append({**label,'status':'failed','error':f'{type(exc).__name__}: {exc}'})
                    print('FAILED',cell,rate,model,exc,flush=True)
    pd.DataFrame(results).to_csv(OUT/'metrics.csv',index=False)
    meta={'source':'https://doi.org/10.5281/zenodo.4032561','files':manifest,'pybamm_version':pybamm.__version__,
          'initialization':'SOC=1.0 per discharge, no history or initial-voltage fitting',
          'protocol':'measured current replay, model receives no measured voltage after initialization; comparison on common time span',
          'temperature':'median chamber temperature during discharge; isothermal; no validated thermal comparison',
          'limitations':['Chen2020 parameter set refers to LG M50 and is related to this characterization; this is not a blind external generalization test.',
             'Early voltage cutoff truncates the comparison; coverage must be reported with error.',
             'A forced measured-current replay is not an independent cutoff-capacity prediction.'],
          'attempted':len(results),'successes':sum(r['status']=='ok' for r in results)}
    (OUT/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'attempted':meta['attempted'],'successes':meta['successes']}),flush=True)
if __name__=='__main__': main()
