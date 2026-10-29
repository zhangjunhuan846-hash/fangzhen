"""One-parameter exploratory calibration, with a frozen cross-cell comparison."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pybamm
from scipy.optimize import minimize_scalar
from battery_sim.registry import get_dataset
from battery_sim.simulation.baseline import _run_one_replay
from user_tools.validate_chen2020_openloop_20261029 import OUT as INPUT

OUT=Path('outputs/chen2020_development_20261029')
KEY='Negative electrode active material volume fraction'

def frame(adapter,cell,rate):
    df=adapter.load_discharge(cell,rate)
    raw=adapter.load_raw(cell)
    cycle={'C10':2,'C2':3,'1C':4,'1p5C':5}[rate]
    df['temperature_ambient_C']=float(raw[(raw['Cycle C']==cycle)&(raw['Md']=='D')]['Temperature Chamber [degC]'].median())
    return df

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    meta=json.loads((INPUT/'metadata.json').read_text(encoding='utf8'))
    if meta['successes'] != 36: raise ValueError('Required unmodified baseline incomplete')
    adapter=get_dataset('chen2020');default=float(pybamm.ParameterValues('Chen2020')[KEY]); history=[]
    dev=frame(adapter,'02','C2')
    def objective(scale):
        result=_run_one_replay(dev,model_name='DFN',parameter_set='Chen2020',parameter_overrides={KEY:default*scale})
        # Penalize truncation so an artificially short common interval is not rewarded.
        score=result['rmse_time_aligned_mV']+1000*(1-result['coverage_fraction'])
        history.append({'scale':float(scale),'rmse_mV':result['rmse_time_aligned_mV'],
                        'coverage':result['coverage_fraction'],'objective_mV':score})
        print('development',round(scale,5),round(score,3),flush=True)
        return score
    opt=minimize_scalar(objective,bounds=(0.9,1.05),method='bounded',options={'maxiter':16,'xatol':0.002})
    frozen={'parameter':KEY,'default_value':default,'scale':float(opt.x),'value':float(default*opt.x),
            'development':'cell02 C2 only','bounds_scale':[0.9,1.05],'success':bool(opt.success),
            'note':'Optimization selected only on development. Other curves had been inspected in baseline and are not a blind study; fitted fraction is effective, not measured material property.'}
    (OUT/'frozen_parameters.json').write_text(json.dumps(frozen,indent=2),encoding='utf8')
    pd.DataFrame(history).to_csv(OUT/'development_history.csv',index=False)
    rows=[]
    baseline=pd.read_csv(INPUT/'metrics.csv')
    for cell in ('03','04'):
        for rate in adapter.list_rates():
            result=_run_one_replay(frame(adapter,cell,rate),model_name='DFN',parameter_set='Chen2020',
                                   parameter_overrides={KEY:default*opt.x})
            base=baseline[(baseline.cell.astype(str).str.zfill(2)==cell)&(baseline.rate==rate)&(baseline.model=='DFN')].iloc[0]
            reference=pd.read_csv(INPUT/f'{cell}_{rate}_DFN.csv')
            # Score both models against exactly the same measured time points;
            # cutoff differences otherwise make the RMSE comparison misleading.
            comparable=reference[reference.time_s <= result['_t_common'][-1]+1e-9]
            t=comparable.time_s.to_numpy()
            measured=comparable.measured_voltage_V.to_numpy()
            tuned=np.interp(t,result['_t_common'],result['_V_sim_common'])
            baseline_common=float(np.sqrt(np.mean((comparable.model_voltage_V.to_numpy()-measured)**2))*1000)
            tuned_common=float(np.sqrt(np.mean((tuned-measured)**2))*1000)
            pd.DataFrame({'time_s':t,'measured_voltage_V':measured,
                          'baseline_voltage_V':comparable.model_voltage_V.to_numpy(),
                          'calibrated_voltage_V':tuned}).to_csv(OUT/f'{cell}_{rate}_common_trace.csv',index=False)
            row={'cell':cell,'rate':rate,'baseline_rmse_mV':base.rmse_time_aligned_mV,
                 'calibrated_rmse_mV':result['rmse_time_aligned_mV'],'baseline_coverage':base.coverage_fraction,
                 'calibrated_coverage':result['coverage_fraction'], 'common_duration_s':float(t[-1]),
                 'baseline_rmse_common_mV':baseline_common,'calibrated_rmse_common_mV':tuned_common}
            rows.append(row);print('evaluation',cell,rate,row['calibrated_rmse_mV'],flush=True)
    pd.DataFrame(rows).to_csv(OUT/'cross_cell_metrics.csv',index=False)
    print('done',flush=True)
if __name__=='__main__':main()
