"""Equal-per-rate development loss, fixed scalar; 03/04 are seen comparisons."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pybamm
from scipy.optimize import minimize_scalar
from battery_sim.registry import get_dataset
from battery_sim.simulation.baseline import _run_one_replay
from user_tools.calibrate_chen2020_development_20261029 import frame,KEY

ROOT=Path('outputs/chen2020_openloop_20261029');OUT=Path('outputs/chen2020_multirate_development_20261029')
RATES=('C2','1C','1p5C')

def main():
    OUT.mkdir(parents=True,exist_ok=True);adapter=get_dataset('chen2020');default=float(pybamm.ParameterValues('Chen2020')[KEY])
    development={rate:frame(adapter,'02',rate) for rate in RATES};history=[]
    def objective(scale):
        scores=[]
        for rate,df in development.items():
            try:
                r=_run_one_replay(df,model_name='DFN',parameter_set='Chen2020',parameter_overrides={KEY:default*scale})
                score=r['rmse_time_aligned_mV']+1000*(1-r['coverage_fraction']);scores.append(score)
                history.append({'scale':float(scale),'rate':rate,'rmse_mV':r['rmse_time_aligned_mV'],'coverage':r['coverage_fraction'],'score_mV':score})
            except Exception as exc:
                scores.append(10000.);history.append({'scale':float(scale),'rate':rate,'error':str(exc),'score_mV':10000.})
        value=float(np.mean(scores));print('development',scale,value,flush=True);return value
    opt=minimize_scalar(objective,bounds=(.9,1.05),method='bounded',options={'maxiter':16,'xatol':.002})
    freeze={'parameter':KEY,'default':default,'scale':float(opt.x),'value':float(default*opt.x),'success':bool(opt.success),
       'training_cell':'02','training_rates':list(RATES),'objective':'arithmetic mean of per-rate time-aligned RMSE plus 1000 mV * uncovered fraction',
       'note':'Exploratory after test data had been inspected; 03 and 04 are not blind. Effective fitted parameter, not measured physical property.'}
    (OUT/'frozen_parameters.json').write_text(json.dumps(freeze,indent=2),encoding='utf8');pd.DataFrame(history).to_csv(OUT/'development_history.csv',index=False)
    out=[]
    for cell in ('03','04'):
        for rate in ('C10',*RATES):
            r=_run_one_replay(frame(adapter,cell,rate),model_name='DFN',parameter_set='Chen2020',parameter_overrides={KEY:default*opt.x})
            ref=pd.read_csv(ROOT/f'{cell}_{rate}_DFN.csv');common=ref[ref.time_s<=r['_t_common'][-1]+1e-9];t=common.time_s.to_numpy();v=common.measured_voltage_V.to_numpy()
            alt=np.interp(t,r['_t_common'],r['_V_sim_common']);base=common.model_voltage_V.to_numpy()
            # Both models scored on the same time points with time weighting.
            def rmse(e):return float(1000*np.sqrt(np.trapezoid(e**2,t)/(t[-1]-t[0])))
            out.append({'cell':cell,'rate':rate,'baseline_common_rmse_mV':rmse(base-v),'calibrated_common_rmse_mV':rmse(alt-v),
                        'calibrated_coverage':r['coverage_fraction'],'common_duration_s':float(t[-1])})
            print('comparison',cell,rate,out[-1],flush=True)
    pd.DataFrame(out).to_csv(OUT/'cross_cell_metrics.csv',index=False)
if __name__=='__main__':main()
