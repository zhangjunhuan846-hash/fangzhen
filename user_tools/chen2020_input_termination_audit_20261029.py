"""New DFN replay with recorded actual model input and solver termination."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pybamm
from battery_sim.registry import get_dataset
from battery_sim.simulation.baseline import _filter_and_downsample
from user_tools.calibrate_chen2020_development_20261029 import frame

BASE=Path('outputs/chen2020_openloop_20261029');OUT=Path('outputs/chen2020_diagnostics_20261029')

def main():
    OUT.mkdir(parents=True,exist_ok=True);a=get_dataset('chen2020');metrics=[]
    for rate in a.list_rates():
        df=frame(a,'02',rate)
        t,i,v=_filter_and_downsample(df.time_s,df.current_A,df.voltage_V)
        temp=float(df.temperature_ambient_C.median());p=pybamm.ParameterValues('Chen2020')
        p.update({'Ambient temperature [K]':temp+273.15,'Initial temperature [K]':temp+273.15,
                  'Current function [A]':pybamm.Interpolant(t,i,pybamm.t)})
        sim=pybamm.Simulation(pybamm.lithium_ion.DFN(),parameter_values=p);solution=sim.solve(t_eval=t,initial_soc=1.)
        common=t[t<=solution.t[-1]]
        predicted=np.interp(common,solution.t,solution['Voltage [V]'].entries)
        actual_current=np.interp(common,solution.t,solution['Current [A]'].entries)
        source_current=np.interp(common,t,i)
        measured=np.interp(common,t,v)
        trace=pd.DataFrame({'time_s':common,'source_current_A':source_current,'model_current_A':actual_current,
                'measured_voltage_V':measured,'model_voltage_V':predicted})
        trace.to_csv(OUT/f'02_{rate}_dfn_recorded_input.csv',index=False)
        old=pd.read_csv(BASE/f'02_{rate}_DFN.csv');n=min(len(old),len(trace))
        if not np.allclose(old.time_s.iloc[:n],common[:n],atol=1e-7):raise ValueError('prior and new sample times differ')
        metrics.append({'cell':'02','rate':rate,'termination':str(solution.termination),
           'model_end_s':float(solution.t[-1]),'observed_end_s':float(t[-1]),
           'predicted_cutoff_time_minus_observed_s':float(solution.t[-1]-t[-1]) if 'Minimum voltage' in str(solution.termination) else None,
           'model_input_integrated_Ah':float(np.trapezoid(solution['Current [A]'].entries,solution.t)/3600),
           'experimental_current_integrated_Ah':float(np.trapezoid(i,t)/3600),
           'coverage':float(min(solution.t[-1],t[-1])/t[-1]),
           'current_max_abs_difference_A':float(np.max(abs(source_current-actual_current))),
           'prior_voltage_max_abs_difference_mV':float(1000*np.max(abs(old.model_voltage_V.iloc[:n]-predicted[:n]))),
           'timepoint_count':len(common),'ambient_C':temp,
           'interpretation':'new recorded rerun; not the original run log'})
        print(rate,metrics[-1],flush=True)
    (OUT/'recorded_input_termination.json').write_text(json.dumps(metrics,indent=2),encoding='utf8')
if __name__=='__main__':main()
