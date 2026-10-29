"""Reference sodium-ion DFN using the upstream Chayambuka2022 parameter set."""
from pathlib import Path
import csv
import math
import numpy as np
import pybamm


def run_sodium_dfn(config,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    rate=float(config['c_rate']);duration=float(config['duration_s']);temp=float(config['temperature_C'])
    if not all(math.isfinite(x) for x in [rate,duration,temp]) or not .05<=rate<=3 or not 1<=duration<=3600 or not 10<=temp<=40:
        raise ValueError('钠电参考模型：倍率0.05–3C，时长1–3600秒，温度10–40°C。')
    model=pybamm.sodium_ion.BasicDFN()
    params=pybamm.ParameterValues('Chayambuka2022')
    nominal=float(params['Nominal cell capacity [A.h]'])
    params.update({'Current function [A]':rate*nominal,'Ambient temperature [K]':temp+273.15,'Initial temperature [K]':temp+273.15})
    solver=pybamm.IDAKLUSolver(on_extrapolation='error')
    simulation=pybamm.Simulation(model,parameter_values=params,solver=solver)
    policy=config.get('extrapolation_policy','stop_before_bound')
    if policy not in ('stop_before_bound','error'):raise ValueError('未知参数外推处理策略。')
    bounded=False
    try:
        solution=simulation.solve(t_eval=np.linspace(0,duration,201))
    except pybamm.SolverError as exc:
        if policy!='stop_before_bound' or 'interpolation bounds were exceeded' not in str(exc):raise
        # Return only a previously successful solve. Never extrapolate the source interpolant.
        lo=0.;hi=duration;solution=None
        for _ in range(12):
            mid=(lo+hi)/2
            try:
                candidate=simulation.solve(t_eval=np.linspace(0,mid,201))
            except pybamm.SolverError as trial:
                if 'interpolation bounds were exceeded' not in str(trial):raise
                hi=mid
            else:
                lo=mid;solution=candidate
        if solution is None:raise ValueError('参数插值边界紧邻初始状态，没有可用的安全区间。') from exc
        bounded=True
    t=solution['Time [s]'].entries;v=solution['Battery voltage [V]'].entries
    if len(t)<2 or not np.isfinite(v).all():raise ValueError('钠电解算产生非有限或过短的电压曲线。')
    with (out/'forward_curve.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['time_s','sim_voltage_V']);w.writerows(zip(t,v))
    return {'engine':'PyBaMM sodium_ion.BasicDFN','pybamm_version':pybamm.__version__,
            'chemistry':'sodium-ion','parameter_set':'Chayambuka2022','current_A':rate*nominal,
            'c_rate':rate,'temperature_C':temp,'requested_duration_s':duration,'completed_duration_s':float(t[-1]),
            'modeled_charge_Ah':float(rate*nominal*t[-1]/3600),
            'termination':'参数插值边界前停止（未完成请求时长）' if bounded else str(solution.termination),
            'stopped_before_extrapolation':bounded,
            'evidence_type':'public_sodium_reference_simulation',
            'scope':'NVPF正极/硬碳负极公开参数参考仿真；使用参数集默认初始状态，不是用户电芯校准。参数外推时仅保留边界前成功求解区间，不同电芯不能直接替用。'}
