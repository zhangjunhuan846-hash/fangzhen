"""Nominal and mismatched synthetic MPC versus measured-voltage CC-CV.

This is a simulation-only benchmark, not a validated charging/thermal model.
"""
from pathlib import Path
import copy,json,time
import numpy as np
import pandas as pd
from user_tools.workbench.engineering_contracts import defaults
from user_tools.workbench.engineering_control import run_control
from user_tools.workbench.engineering_bms import plant_parameters

OUT=Path('outputs/eis_bms_validation/control_comparison_20261029')

def run_cccv(cfg,plant_cell):
    import thevenin
    p=plant_parameters(plant_cell);plant=thevenin.Prediction(p);plant.set_options(rtol=1e-8,atol=1e-10)
    state=thevenin.TransientState(plant_cell['initial_soc'],plant_cell['temperature_C']+273.15,0.,np.zeros(len(plant_cell['R_ohm'])))
    rng=np.random.default_rng(cfg['seed']);measured=p['ocv'](state.soc)+rng.normal(0,cfg['voltage_noise_V'])
    previous_current=0.;rows=[];events=[];limit=cfg['cell']['voltage_max_V']-cfg['voltage_guard_V'];dt=cfg['dt_s']
    # Feedback law: CC at Imax, taper via last measured voltage and nominal R0.
    # This is a discrete idealized CC-CV approximation, not a certified charger.
    for k in range(cfg['steps']):
        started=time.perf_counter();charge=float(np.clip(previous_current+(limit-measured)/cfg['cell']['R0_ohm'],0,cfg['cell']['current_max_A']))
        solve_ms=(time.perf_counter()-started)*1000
        state=plant.take_step(state,-charge,dt)
        measured_current=-charge+rng.normal(0,cfg['current_noise_A'])+cfg['current_bias_A']
        measured=state.voltage+rng.normal(0,cfg['voltage_noise_V']);previous_current=charge
        row={'time_s':(k+1)*dt,'charge_A':charge,'voltage_V':float(state.voltage),'temperature_C':float(state.T_cell-273.15),
             'soc_model':float(state.soc),'sensor_current_A':float(measured_current),'sensor_voltage_V':float(measured),'solver_time_ms':solve_ms}
        rows.append(row)
        if state.voltage>cfg['cell']['voltage_max_V']+1e-4 or state.T_cell-273.15>cfg['cell']['temperature_max_C']+1e-4 or not 0<=state.soc<=1:
            events.append('plant_limit_exceeded');break
        if state.soc>=cfg['target_soc']:events.append('model_target_reached');break
    return rows,events

def summarize(name,scenario,rows,events,dt):
    return {'controller':name,'scenario':scenario,'target_reached':'model_target_reached' in events,
       'elapsed_s':rows[-1]['time_s'],'final_soc_model':rows[-1]['soc_model'],
       'energy_into_terminal_Wh':float(sum(x['voltage_V']*x['charge_A']*dt for x in rows)/3600),
       'max_voltage_V':max(x['voltage_V'] for x in rows),'max_temperature_C':max(x['temperature_C'] for x in rows),
       'max_current_A':max(x['charge_A'] for x in rows),'limit_violations':sum(x=='plant_limit_exceeded' for x in events),
       'solver_fallbacks':sum(x=='solver_fallback' for x in events),
       'mean_decision_ms':float(np.mean([x['solver_time_ms'] for x in rows])),
       'max_decision_ms':float(np.max([x['solver_time_ms'] for x in rows]))}

def main():
    OUT.mkdir(parents=True,exist_ok=True);cfg=defaults('mpc');cfg.update(dt_s=20.,steps=180,horizon=6,target_soc=.6,
       voltage_noise_V=.001,current_noise_A=.001,current_bias_A=0.,seed=42)
    cfg['cell'].update(initial_soc=.55,estimated_initial_soc=.55,current_max_A=2.5)
    variants={};nominal=copy.deepcopy(cfg['cell']);variants['nominal']=nominal
    mismatch=copy.deepcopy(nominal);mismatch['R0_ohm']*=1.3;mismatch['R_ohm']=[r*1.3 for r in mismatch['R_ohm']]
    mismatch['capacity_Ah']*=.95;mismatch['heat_transfer_W_K']*=.8;variants['mismatch']=mismatch
    (OUT/'protocol.json').write_text(json.dumps({'config':cfg,'plants':variants,
        'policy':'same initial plant state, charge current limits, voltage/temperature limits, sampling interval and simulated plant SOC stop',
        'MPC_information':'EKF SOC/polarization and simulated plant temperature, noisy current/voltage',
        'CCCV_information':'previous noisy voltage and previous command; no SOC feedback except model SOC used for experiment stop',
        'constraint':'synthetic charge model, mismatch is prescribed, not real-cell calibrated',
        'cccv':'discrete voltage feedback CC-CV approximation','control_scope':'research only, no physical hardware'},indent=2),encoding='utf8')
    output=[]
    for scenario,plant in variants.items():
        folder=OUT/scenario/'mpc';result=run_control(copy.deepcopy(cfg),folder,plant_cell_override=plant,stop_on_model_soc=True)
        mpc=pd.read_csv(folder/'engineering.csv').to_dict(orient='records');events=[x['kind'] for x in result['events']]
        output.append(summarize('MPC',scenario,mpc,events,cfg['dt_s']))
        rows,events=run_cccv(cfg,plant);pd.DataFrame(rows).to_csv(OUT/scenario/'cccv_trace.csv',index=False)
        output.append(summarize('CC-CV',scenario,rows,events,cfg['dt_s']))
        print(scenario,output[-2:],flush=True)
    pd.DataFrame(output).to_csv(OUT/'metrics.csv',index=False)
    (OUT/'summary.json').write_text(json.dumps({'comparisons':output,'scope':'synthetic only; no real battery or temperature/charging validation; two controller information sets differ'},indent=2),encoding='utf8')
if __name__=='__main__':main()
