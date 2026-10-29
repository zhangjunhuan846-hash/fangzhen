"""Audit existing open-loop traces; do not reuse residuals as calibration targets."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pybamm
from battery_sim.registry import get_dataset
from battery_sim.datasets.chen2020 import RATE_STEP

INPUT=Path('outputs/chen2020_openloop_20261029')
OUT=Path('outputs/chen2020_diagnostics_20261029')

def main():
    OUT.mkdir(parents=True,exist_ok=True);adapter=get_dataset('chen2020');metrics=pd.read_csv(INPUT/'metrics.csv');rows=[];init=[]
    default=pybamm.ParameterValues('Chen2020');adjusted=default.set_initial_state(1.,inplace=False)
    keys=['Initial concentration in negative electrode [mol.m-3]','Initial concentration in positive electrode [mol.m-3]']
    cmax=['Maximum concentration in negative electrode [mol.m-3]','Maximum concentration in positive electrode [mol.m-3]']
    for label,p in [('parameter_default',default),('soc_1_derived',adjusted)]:
        init.append({'case':label,'negative_concentration_mol_m3':float(p[keys[0]]),'negative_stoichiometry':float(p[keys[0]]/p[cmax[0]]),
                     'positive_concentration_mol_m3':float(p[keys[1]]),'positive_stoichiometry':float(p[keys[1]]/p[cmax[1]])})
    for cell in ('02','03','04'):
        raw=adapter.load_raw(cell)
        for rate in adapter.list_rates():
            exp=adapter.load_discharge(cell,rate);step=RATE_STEP[rate]
            rest=raw[(raw.Step==step-1)&(raw.Md=='R')]
            rest_tail=rest[rest['Step Time [s]']>=rest['Step Time [s]'].max()-300] if len(rest) else rest
            nextrest=raw[(raw.Step==step+1)&(raw.Md=='R')]
            ambient=float(raw[(raw.Step==step)&(raw.Md=='D')]['Temperature Chamber [degC]'].median())
            params=pybamm.ParameterValues('Chen2020');params.update({'Ambient temperature [K]':ambient+273.15,'Initial temperature [K]':ambient+273.15,'Current function [A]':0.})
            # Determine SOC=1 using the original voltage limits; after that,
            # widen the upper event only to calculate the unloaded diagnostic
            # voltage (otherwise its initial event can already be violated).
            params=params.set_initial_state(1.,inplace=False)
            params.update({'Upper voltage cut-off [V]':5.0})
            sim=pybamm.Simulation(pybamm.lithium_ion.SPM(),parameter_values=params);sol=sim.solve([0,1])
            v0=float(sol['Voltage [V]'].entries[0]); applied=sim.parameter_values
            for model in ('SPM','SPMe','DFN'):
                trace=pd.read_csv(INPUT/f'{cell}_{rate}_{model}.csv');t=trace.time_s.to_numpy();err=trace.residual_V.to_numpy();duration=float(exp.time_s.iloc[-1]);end=float(t[-1])
                for name,low,high in [('early',0,.1),('middle',.1,.9),('late',.9,1.)]:
                    mask=(t>=low*duration)&(t<=min(high*duration,end))
                    if mask.sum()<2:continue
                    tm=t[mask];em=err[mask];dt=tm[-1]-tm[0]
                    row={'cell':cell,'rate':rate,'model':model,'segment':name,'observed_duration_s':float(dt),
                       'rmse_mV_time_weighted':float(1000*np.sqrt(np.trapezoid(em**2,tm)/dt)),
                       'bias_mV_time_weighted':float(1000*np.trapezoid(em,tm)/dt)}
                    rows.append(row)
            r=metrics[(metrics.cell.astype(str).str.zfill(2)==cell)&(metrics.rate==rate)&(metrics.model=='DFN')].iloc[0]
            init.append({'case':'replay_inputs','cell':cell,'rate':rate,'initial_soc':1.,'ambient_C':ambient,
                'modeled_rest_ocv_V':v0,'measured_preceding_rest_last5min_V':float(rest_tail['Voltage [V]'].median()) if len(rest_tail) else None,
                'pre_rest_duration_s':float(rest['Step Time [s]'].max()) if len(rest) else None,
                'measured_first_loaded_V':float(exp.voltage_V.iloc[0]),
                'negative_concentration_mol_m3':float(applied[keys[0]]),'positive_concentration_mol_m3':float(applied[keys[1]]),
                'negative_stoichiometry':float(applied[keys[0]]/applied[cmax[0]]),'positive_stoichiometry':float(applied[keys[1]]/applied[cmax[1]]),
                'dfn_trace_end_s':end,'dfn_coverage':float(r.coverage_fraction),
                'next_rest_duration_s':float(nextrest['Step Time [s]'].max()) if len(nextrest) else None,
                'model_relaxation_compared':False,'model_termination_reason':'not saved by original baseline; cannot infer exact event from trace'})
    pd.DataFrame(rows).to_csv(OUT/'time_weighted_residual_by_stage.csv',index=False)
    (OUT/'initial_state_and_protocol.json').write_text(json.dumps({'records':init,
       'limitations':['Existing baseline ends at discharge: no model relaxation was retained.',
        'Current originates in same adapter input; previous run did not save model input trace or exact solver termination. Values cannot independently be reconstructed as saved inputs.',
        'The final comparison range does not predict cutoff capacity under a forced measured-current replay.'],
        'source':'https://doi.org/10.5281/zenodo.4032561','pybamm_version':pybamm.__version__},indent=2),encoding='utf8')
    print(json.dumps(init[:4],indent=2))
if __name__=='__main__':main()
