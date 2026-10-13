"""Explicitly approximate user-parameter SPM half-cell forward solve (WSL)."""
from pathlib import Path
import csv
import math
import numpy as np


def run_sample_forward(config,out):
    import pybamm
    from battery_sim.models.pybamm_factory import load_parameter_values
    from user_tools.rg_loop.physics import save
    packet=config['sample_packet'];p={k:v['value'] for k,v in packet['parameters'].items()}
    if not packet['candidate_complete'] or packet['conflicts']:raise ValueError('参数候选不完整或存在冲突。')
    pv=load_parameter_values('Ecker2015_graphite_halfcell');reference_keys=set(pv.keys())
    rows=list(csv.DictReader(Path(config['ocp_path']).open(encoding='utf-8-sig')))
    x=np.array([float(r['stoichiometry']) for r in rows]);v=np.array([float(r['voltage_V']) for r in rows])
    if not x[0]<p['initial_x0']<x[-1]:raise ValueError('初始锂化度不在OCP表内部。')
    def ocp(sto):return pybamm.Interpolant(x,v,sto,extrapolate=False)
    def i0(c_e,c_s_surf,c_s_max,T):return pybamm.Scalar(p['i0_A_m2'])
    updates={
        'Electrode height [m]':math.sqrt(p['area_cm2']*1e-4),'Electrode width [m]':math.sqrt(p['area_cm2']*1e-4),
        'Positive electrode thickness [m]':p['thickness_um']*1e-6,
        'Positive electrode porosity':p['porosity'],'Positive electrode active material volume fraction':p['active_volume_fraction'],
        'Positive particle radius [m]':p['radius_um']*1e-6,'Maximum concentration in positive electrode [mol.m-3]':p['c_max_mol_m3'],
        'Initial concentration in positive electrode [mol.m-3]':p['initial_x0']*p['c_max_mol_m3'],
        'Positive particle diffusivity [m2.s-1]':p['ds_m2_s'],'Positive electrode exchange-current density [A.m-2]':i0,
        'Positive electrode OCP [V]':ocp,'Separator thickness [m]':p['separator_thickness_um']*1e-6,
        'Separator porosity':p['separator_porosity'],'Initial concentration in electrolyte [mol.m-3]':p['electrolyte_concentration_mol_L']*1000,
        'Current function [A]':p['current_mA']/1000,'Lower voltage cut-off [V]':p['voltage_lower_V'],
        'Upper voltage cut-off [V]':p['voltage_upper_V'],'Ambient temperature [K]':p['temperature_C']+273.15,
        'Initial temperature [K]':p['temperature_C']+273.15,
    }
    pv.update(updates);model=pybamm.lithium_ion.SPM({'working electrode':'positive'})
    surface=model.variables['Positive particle surface concentration [mol.m-3]']/p['c_max_mol_m3']
    model.events.extend([pybamm.Event('OCP domain lower',pybamm.min(surface)-float(x[0])),
                         pybamm.Event('OCP domain upper',float(x[-1])-pybamm.max(surface))])
    horizon=float(config.get('duration_s',3600))
    if not 1<=horizon<=20000:raise ValueError('仿真时长需为1–20000秒。')
    solution=pybamm.Simulation(model,parameter_values=pv).solve(np.linspace(0,horizon,250))
    t=np.asarray(solution['Time [s]'].entries).ravel();voltage=np.asarray(solution['Voltage [V]'].entries).ravel()
    q=np.abs(p['current_mA']/1000*(t-t[0])/3600)
    mean_concentration=np.asarray(solution['Average positive particle concentration [mol.m-3]'].entries).ravel()
    mean_x=mean_concentration/p['c_max_mol_m3']
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    np.savetxt(out/'forward_curve.csv',np.c_[t,voltage,q],delimiter=',',header='time_s,voltage_sim_V,capacity_sim_Ah',comments='')
    termination=str(solution.termination);cutoff='voltage' in termination.lower() and 'event' in termination.lower()
    result={'evidence_type':'user_parameter_model_exploration','sample_id':packet['sample_id'],'electrode_id':packet['electrode_id'],
            'model':'SPM','working_electrode':'positive','graphite_slot':'positive','current_A':p['current_mA']/1000,
            'direction':'lithiation' if p['current_mA']>0 else 'delithiation','termination':termination,'reached_voltage_cutoff':cutoff,
            'modeled_charge_Ah':float(q[-1]),'capacity_is_predictive':False,'independent_validation_passed':False,
            'initial_mean_stoichiometry':float(mean_x[0]),'final_mean_stoichiometry':float(mean_x[-1]),
            'applied_keys':list(updates),'inherited_reference_keys':sorted(reference_keys-set(updates)),
            'sample_packet':packet,'scope':'用户参数+Ecker参考辅助参数的SPM半电池探索；Ds/i0采用常数近似。面积用等面积正方形表达，非真实形状重建。明确符号：正电流嵌锂，负电流脱锂。未通过独立预测；达到时长/OCP边界时电量不是截止容量。'}
    save(out/'result.json',result);return result
