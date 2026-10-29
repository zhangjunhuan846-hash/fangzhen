"""Compare MPC estimator feedback and ideal plant-SOC feedback in simulation."""
from pathlib import Path
import copy,json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from user_tools.workbench.engineering_control import run_control
from user_tools.workbench.engineering_contracts import defaults

OUT=Path('outputs/eis_bms_validation/mpc_tail_diagnostics_20261029')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    cfg=defaults('mpc');cfg.update(dt_s=20.,steps=180,horizon=6,target_soc=.6,voltage_noise_V=.001,current_noise_A=.001,current_bias_A=0.,seed=42)
    cfg['cell'].update(initial_soc=.55,estimated_initial_soc=.55,current_max_A=2.5)
    plant=copy.deepcopy(cfg['cell']);plant['R0_ohm']*=1.3;plant['R_ohm']=[r*1.3 for r in plant['R_ohm']]
    plant['capacity_Ah']*=.95;plant['heat_transfer_W_K']*=.8
    outcomes={};fig,axes=plt.subplots(3,1,figsize=(11,9),sharex=True)
    for label,ideal in [('ekf',False),('ideal_soc',True)]:
        folder=OUT/label
        res=run_control(copy.deepcopy(cfg),folder,plant_cell_override=plant,stop_on_model_soc=True,ideal_soc_feedback=ideal)
        d=pd.read_csv(folder/'engineering.csv');drop=d[d.charge_A<2.25];onset=drop.iloc[0] if len(drop) else d.iloc[-1]
        outcomes[label]={'elapsed_s':float(d.time_s.iloc[-1]),'steps':len(d),'terminal_soc_plant':float(d.soc_model.iloc[-1]),
            'terminal_soc_ekf':float(d.soc_ekf.iloc[-1]),'first_current_below_90pct_max':onset.to_dict(),
            'min_voltage_margin_V':float(d.voltage_margin_V.min()),'min_temperature_margin_C':float(d.temperature_margin_C.min()),
            'minimum_command_A':float(d.charge_A.min()),'solver_fallbacks':int(d.fallback.sum()),'events':res['events']}
        axes[0].plot(d.time_s,d.soc_model,label=label+' plant SOC');axes[0].plot(d.time_s,d.soc_ekf,linestyle='--',label=label+' EKF SOC')
        axes[1].plot(d.time_s,d.charge_A,label=label+' command and applied')
        axes[2].plot(d.time_s,d.voltage_margin_V,label=label+' actual voltage margin')
        axes[2].plot(d.time_s,(cfg['cell']['voltage_max_V']-cfg['voltage_guard_V'])-d.predicted_voltage_end_V,linestyle='--',label=label+' first-step predicted guard margin')
    axes[0].axhline(cfg['target_soc'],color='black',linestyle=':',label='target');axes[0].set_ylabel('SOC');axes[1].set_ylabel('charge A');axes[2].set_ylabel('voltage margin V');axes[2].set_xlabel('time s')
    for ax in axes:ax.grid(alpha=.2);ax.legend(fontsize=8)
    fig.tight_layout();fig.savefig(OUT/'mpc_diagnostic.png',dpi=150);plt.close(fig)
    payload={'config':cfg,'plant':plant,'outcomes':outcomes,'scope':'synthetic diagnostic; ideal SOC is supplied only in diagnostic run, EKF polarization retained; first-step predictions are not full-horizon constraint extrema; simulated true SOC is evaluator stop only'}
    (OUT/'summary.json').write_text(json.dumps(payload,indent=2),encoding='utf8')
    print(json.dumps(outcomes,indent=2))
if __name__=='__main__':main()
