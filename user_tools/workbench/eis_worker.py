"""Version-adapted native PyBaMM frequency-domain EIS, not paper-fit reproduction."""
import csv
from pathlib import Path
import numpy as np


def gaussian_information(sensitivity,prior_covariance,noise_covariance):
    """Exact linear-Gaussian EIG baseline; not variational BOED reproduction."""
    a=np.atleast_2d(np.asarray(sensitivity,float));prior=np.asarray(prior_covariance,float);noise=np.asarray(noise_covariance,float)
    if prior.shape!=(a.shape[1],a.shape[1]) or noise.shape!=(a.shape[0],a.shape[0]):raise ValueError('信息矩阵维度不一致。')
    for matrix in [prior,noise]:
        if not np.isfinite(matrix).all() or not np.allclose(matrix,matrix.T):raise ValueError('协方差需有限且对称。')
    if np.linalg.eigvalsh(prior).min()<-1e-12:raise ValueError('先验协方差必须半正定。')
    np.linalg.cholesky(noise)
    if not np.isfinite(a).all():raise ValueError('灵敏度需为有限数值。')
    _,log_signal=np.linalg.slogdet(noise+a@prior@a.T);_,log_noise=np.linalg.slogdet(noise)
    return float(max(0,.5*(log_signal-log_noise)))


def public_eis(config,out):
    import pybamm
    from battery_sim.models.pybamm_factory import load_parameter_values,build_model
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    ps=config.get('parameter_set','Chen2020');half=ps=='Ecker2015_graphite_halfcell'
    if ps not in ['Chen2020','Ecker2015_graphite_halfcell']:raise ValueError('未支持的EIS参考参数集。')
    model_name=config.get('model','SPMe');options={'surface form':'differential'}
    if half:options['working electrode']='positive'
    pv=load_parameter_values(ps);pv['Current function [A]']=0
    # Chen/Ecker sets do not consistently contain capacitances. Never invent
    # measured values: explicitly record the public-demo assumptions.
    caps={}
    for electrode in ['Negative','Positive']:
        key=f'{electrode} electrode double-layer capacity [F.m-2]'
        value=float(config.get(electrode.lower()+'_double_layer_F_m2',.2))
        if not np.isfinite(value) or value<=0:raise ValueError('双电层容量假设必须为正有限值。')
        caps[key]=value
    pv.update(caps,check_already_exists=False)
    socs=config.get('socs',[.2,.5,.8]);spectra=[]
    low=float(config.get('frequency_min_Hz',.01));high=float(config.get('frequency_max_Hz',10000));count=int(config.get('frequency_points',25))
    if not 1e-4<=low<high<=1e6 or not 5<=count<=100:raise ValueError('频率范围/点数不合法。')
    if not 1<=len(socs)<=5 or any(not .01<float(v)<.99 for v in socs):raise ValueError('SOC/锂化度需在0.01–0.99内，最多5个。')
    frequencies=np.geomspace(low,high,count)
    for soc in socs:
        values=pv.copy();model=build_model(model_name,options)
        if half:values['Initial concentration in positive electrode [mol.m-3]']=float(soc)*float(values['Maximum concentration in positive electrode [mol.m-3]'])
        simulation=pybamm.EISSimulation(model,parameter_values=values)
        solution=simulation.solve(frequencies,initial_soc=None if half else float(soc))
        z=solution.impedance
        if not np.isfinite(z).all():raise ValueError('阻抗求解存在非有限值。')
        points=[{'frequency_Hz':float(f),'Z_real_ohm':float(v.real),'Z_imag_ohm':float(v.imag),
                 'magnitude_ohm':float(abs(v)),'phase_deg':float(np.degrees(np.angle(v)))} for f,v in zip(frequencies,z)]
        name=('x0' if half else 'SOC')+'='+str(soc);spectra.append({'name':name,'points':points})
        with (out/('eis_'+str(soc)+'.csv')).open('w',newline='',encoding='utf-8') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(points[0]));writer.writeheader();writer.writerows(points)
    return {'evidence_type':'public_model_eis','model':model_name,'parameter_set':ps,'eis_spectra':spectra,'pybamm_version':pybamm.__version__,
            'assumed_double_layer_capacitance_F_m2':caps,
            'independent_validation_passed':False,'scope':'公开参数集的零直流工作点、小信号频域EIS探索。halfcell的x0不是全电池SOC；采用differential表面形式，双电层容量是明确记录的演示假设，不是Chen/Ecker实测参数。PyBaMM26.8版本适配，未复现论文拟合或验证自有石墨；实测谱仍需线性/稳态、同样品OCP和跨状态证据。'}


def linear_impedance(mass,jacobian,forcing,output,direct,frequencies):
    """Paper Eq.7 small-signal state transfer, used for independent RC checks."""
    mass=np.asarray(mass,float);jacobian=np.asarray(jacobian,float);forcing=np.asarray(forcing,float);output=np.asarray(output,float)
    return np.array([direct+output@np.linalg.solve(1j*2*np.pi*f*mass-jacobian,forcing) for f in frequencies])


def parquet_recording(config,out):
    import pandas as pd
    import pyarrow.parquet as pq
    out=Path(out);out.mkdir(parents=True,exist_ok=True);source=Path(config['source_path'])
    metadata=pq.ParquetFile(source).metadata
    if metadata.num_rows>3_000_000 or metadata.num_columns>100 or sum(metadata.row_group(i).total_byte_size for i in range(metadata.num_row_groups))>500_000_000:
        raise ValueError('Parquet解码规模超出限制，请分割记录。')
    frame=pd.read_parquet(source)
    aliases={'time_s':['time_s','timepoints [s]'],'voltage_V':['voltage_V','voltages [V]'],'current_A':['current_A','currents [A]']}
    mapping={k:next((c for c in cols if c in frame),None) for k,cols in aliases.items()}
    if any(v is None for v in mapping.values()):raise ValueError('本版Parquet支持明确s/V/A时域列；不推断未知嵌套结构或单位。')
    raw=frame[[mapping[k] for k in aliases]].apply(pd.to_numeric,errors='coerce');raw.columns=list(aliases)
    finite=np.isfinite(raw.to_numpy()).all(axis=1)&(raw.time_s.to_numpy()>=0)
    invalid=int((~finite).sum());valid=raw.loc[finite].copy();valid.insert(0,'source_row',np.flatnonzero(finite)+1)
    diff=valid.time_s.diff().to_numpy();reset=np.isfinite(diff)&(diff<=0);valid.insert(1,'segment',np.cumsum(reset))
    valid.to_csv(out/'normalized.csv',index=False,encoding='utf-8-sig')
    step=max(1,len(valid)//500);points=valid.iloc[::step]
    commands=frame['Command'].value_counts().head(30).to_dict() if 'Command' in frame else {}
    qc={'evidence_type':'user_parquet_recording','valid_rows':len(valid),'issue_count':invalid+int(reset.sum()),
        'segments':int(reset.sum())+1,'consecutive_exact_duplicates_removed':0,'mapping':mapping,
        'commands':{str(k):int(v) for k,v in commands.items()},'warnings':['这是时域波形，不是已提取的阻抗谱；不能直接把voltages列当Z。'],
        'qc_pass':invalid==0 and not reset.any(),'eis_extracted':False,'source_sha256':config.get('source_sha256'),'filename':config.get('filename'),
        'scope':'明确s/V/A列的Parquet时域记录转标准化CSV，原件保留；非有限行与时间回跳计数并分段，不修复。仅生成波形与Command目录，未进行GITT扩散辨识或正弦解调。MJ1为graphite/SiOx三电极记录，不能自动替代纯回收石墨半电池。'}
    return qc,[{'name':'Parquet电压记录','points':[[float(r.time_s),float(r.voltage_V),None] for r in points.itertuples()]}]
