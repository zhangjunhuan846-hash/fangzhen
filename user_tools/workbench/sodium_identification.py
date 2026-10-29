"""Bounded sodium DFN curve fitting with independent curve holdout."""
from __future__ import annotations
import csv
import io
import math
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
import pybamm
from user_tools.workbench.multichem_analysis import table, value


def simulate(c_rate, temperature_C, times, diffusion_scale=1., drop_per_C=0.):
    params=pybamm.ParameterValues('Chayambuka2022')
    original=params['Negative particle diffusivity [m2.s-1]']
    def scaled(concentration,temperature):return diffusion_scale*original(concentration,temperature)
    nominal=float(params['Nominal cell capacity [A.h]'])
    params.update({'Negative particle diffusivity [m2.s-1]':scaled,'Current function [A]':c_rate*nominal,
                   'Ambient temperature [K]':temperature_C+273.15,'Initial temperature [K]':temperature_C+273.15})
    simulation=pybamm.Simulation(pybamm.sodium_ion.BasicDFN(),parameter_values=params,
        solver=pybamm.IDAKLUSolver(on_extrapolation='error'))
    solution=simulation.solve(t_eval=np.asarray(times))
    t=solution['Time [s]'].entries;v=solution['Battery voltage [V]'].entries
    if t[-1]<times[-1]-1e-5 or not np.isfinite(v).all():raise ValueError('求解提前停止，不能覆盖完整测量曲线。')
    return np.interp(times,t,v)-drop_per_C*c_rate


def run(raw,config,out):
    rows=table(raw,['curve_id','role','time_s','voltage_V','c_rate','temperature_C'],max_rows=3000)
    curves={}
    for row in rows:
        name=row['curve_id'].strip();role=row['role'].strip()
        if not name or role not in ('train','test'):raise ValueError('curve_id不能为空，role仅可为train或test。')
        time=value(row['time_s'],'time_s');voltage=value(row['voltage_V'],'voltage_V')
        rate=value(row['c_rate'],'c_rate');temp=value(row['temperature_C'],'temperature_C')
        if not 0<=time<=3600 or not 0<voltage<6 or not .05<=rate<=3 or not 10<=temp<=40:raise ValueError('时间、电压、倍率或温度超出范围。')
        if name not in curves:curves[name]={'role':role,'rate':rate,'temp':temp,'time':[],'voltage':[]}
        c=curves[name]
        if c['role']!=role or c['rate']!=rate or c['temp']!=temp:raise ValueError('同曲线须保持相同role、倍率和温度。')
        if c['time'] and time<=c['time'][-1]:raise ValueError('每条曲线时间必须严格递增。')
        c['time'].append(time);c['voltage'].append(voltage)
    if not 2<=len(curves)<=8 or not any(c['role']=='train' for c in curves.values()) or not any(c['role']=='test' for c in curves.values()):
        raise ValueError('需要2–8条互不重叠的训练及独立留出曲线。')
    for c in curves.values():
        if len(c['time'])<5 or len(c['time'])>150 or c['time'][0]!=0:raise ValueError('每条曲线需5–150点，从0秒开始。')
        c['time']=np.asarray(c['time']);c['voltage']=np.asarray(c['voltage'])
    train=[c for c in curves.values() if c['role']=='train']
    def fit_residual(theta):
        pieces=[]
        for c in train:
            try:p=simulate(c['rate'],c['temp'],c['time'],10**theta[0],theta[1])
            except (pybamm.SolverError,ValueError,RuntimeError):return np.full(sum(len(x['time']) for x in train),10.)
            # Curves have equal weight, regardless of their number of sampled points.
            pieces.append((p-c['voltage'])/math.sqrt(len(c['time'])))
        return np.concatenate(pieces)
    initial=fit_residual([0,0])
    if np.max(np.abs(initial))>=9/math.sqrt(max(len(c['time']) for c in train)):
        raise ValueError('基准DFN无法覆盖训练曲线；请检查初始状态、数据窗口、倍率和参数插值范围。')
    nfev=config.get('max_nfev',15)
    if isinstance(nfev,bool) or not isinstance(nfev,int) or not 3<=nfev<=60:raise ValueError('max_nfev须为3–60整数。')
    def finite_jac(theta):
        # Default finite differences near zero are too small for a numerical DFN solve.
        lo=np.array([-1.,0.]);hi=np.array([1.,.3]);steps=np.array([.01,.001]);cols=[]
        for j,step in enumerate(steps):
            left=theta.copy();right=theta.copy();left[j]=max(lo[j],theta[j]-step);right[j]=min(hi[j],theta[j]+step)
            cols.append((fit_residual(right)-fit_residual(left))/(right[j]-left[j]))
        return np.column_stack(cols)
    fit=least_squares(fit_residual,[0,.02],jac=finite_jac,bounds=([-1.,0.],[1.,.3]),max_nfev=nfev,
                      xtol=1e-6,ftol=1e-6,gtol=1e-6)
    scale=float(10**fit.x[0]);drop=float(fit.x[1]); details=[];exports=[]
    for name,c in curves.items():
        try:
            base=simulate(c['rate'],c['temp'],c['time']);pred=simulate(c['rate'],c['temp'],c['time'],scale,drop)
        except (pybamm.SolverError,ValueError,RuntimeError) as exc:
            details.append({'curve_id':name,'role':c['role'],'status':'failed','error':str(exc)[:300]});continue
        details.append({'curve_id':name,'role':c['role'],'status':'ok','c_rate':c['rate'],
            'baseline_rmse_V':float(np.sqrt(np.mean((base-c['voltage'])**2))),
            'fitted_rmse_V':float(np.sqrt(np.mean((pred-c['voltage'])**2)))})
        exports.extend({'curve_id':name,'role':c['role'],'time_s':float(t),'observed_V':float(y),'baseline_V':float(b),'fitted_V':float(p)}
                       for t,y,b,p in zip(c['time'],c['voltage'],base,pred))
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if exports:
        with (out/'holdout.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(exports[0]));w.writeheader();w.writerows(exports)
    singular=np.linalg.svd(fit.jac,compute_uv=False)
    condition=float(singular[0]/singular[-1]) if singular[-1]>1e-12 else None
    return {'parameter_set':'Chayambuka2022','negative_diffusivity_scale':scale,'effective_drop_V_per_C':drop,
            'solver_success':bool(fit.success),'solver_message':str(fit.message),'evaluations':int(fit.nfev),
            'near_parameter_bound':bool(abs(fit.x[0])>.98 or drop>.299 or drop<.001),
            'local_jacobian_singular_values':[float(x) for x in singular], 'local_jacobian_condition':condition,
            'curves':details,'pybamm_version':pybamm.__version__,'candidate_link':config.get('_candidate_link'),
            'scope':'以Chayambuka NVPF/硬碳参考电芯默认初始状态为前提；辨识负极扩散系数整体倍率与经验性倍率电压降（并非独立测得接触电阻），训练/留出按整条曲线分开。电流归一化到参考电芯容量，不能把倍率拟合参数直接当成目标电芯物性；参数可辨识性未获证明，跨正极体系结果仅作模型失配诊断。'}
