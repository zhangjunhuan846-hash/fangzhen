"""Isolated optional upstream calculations, invoked in the WSL environment."""
import json
import math
import sys
from pathlib import Path


def cv_surface(config):
    from electrokitty import ElectroKitty
    import numpy as np
    from user_tools.workbench.multichem_analysis import value

    ranges={'initial_V':(-3,3),'turn_V':(-3,3),'scan_rate_V_s':(.001,2),
            'temperature_K':(250,350),'area_m2':(1e-8,.1),
            'surface_mol_m2':(1e-12,.001),'formal_potential_V':(-3,3),
            'rate_constant_s':(.001,1000),'interaction_a':(-10,10),'interaction_b':(-10,10)}
    p={}
    for key,(lo,hi) in ranges.items():
        p[key]=value(config.get(key),key)
        if not lo<=p[key]<=hi:raise ValueError(key+'超出允许范围。')
    nt=value(config.get('points',200),'points')
    if int(nt)!=nt or not 50<=nt<=500:raise ValueError('points需为50–500整数。')
    if p['initial_V']==p['turn_V']:raise ValueError('起始电位与折返电位不能相同。')
    simulator=ElectroKitty('E(1): a*=b*')
    simulator.V_potential(p['initial_V'],p['turn_V'],p['scan_rate_V_s'],0,0,int(nt))
    simulator.create_simulation([[p['formal_potential_V'],p['rate_constant_s'],0.0]],
        [p['temperature_K'],0,0,p['area_m2']], [],
        [p['interaction_a'],p['interaction_b']], [0.001,20,1e-5,0],
        [[p['surface_mol_m2'],0],[]])
    potentials,currents,times=simulator.simulate()
    if not (np.isfinite(potentials).all() and np.isfinite(currents).all() and np.isfinite(times).all()):
        raise ValueError('ElectroKitty输出包含非有限值。')
    return {'backend':'ElectroKitty 1.0.11.6',
        'mechanism':'E(1): a*=b*',
        'points':[{'time_s':float(t),'potential_V':float(e),'current_A':float(i)} for t,e,i in zip(times,potentials,currents)],
        'scope':'ElectroKitty表面限域单电子反应示例；参数由用户提供，无溶液扩散、双电层、膜电阻或拟合；并非电池材料机理验证。'}


def ixdat_alignment(raw,config):
    import numpy as np
    from ixdat import Measurement
    from ixdat.data_series import TimeSeries, ValueSeries
    from user_tools.workbench.multichem_analysis import align, table, value

    result=align(raw,config)  # Validate ordering, overlap and offset before interpolation.
    signal=[r for r in table(raw,['stream','time_s','value']) if r['stream'].strip()=='signal']
    times=np.asarray([value(r['time_s'],'time_s')+value(config.get('offset_s',0),'offset_s') for r in signal])
    values=np.asarray([value(r['value'],'value') for r in signal])
    ts=TimeSeries(name='signal_time',unit_name='s',data=times,tstamp=0)
    vs=ValueSeries(name='signal',unit_name='a.u.',data=values,tseries=ts)
    measurement=Measurement(name='user alignment',series_list=[ts,vs],tstamp=0)
    target=np.asarray([p['time_s'] for p in result['points']])
    interpolated=measurement.grab_for_t('signal',target,remove_background=False)
    if not np.isfinite(interpolated).all():raise ValueError('ixdat插值输出包含非有限值。')
    for point,val in zip(result['points'],interpolated):point['signal']=float(val)
    result['backend']='ixdat 0.4.0'
    result['scope']+=' 已调用ixdat时间序列插值；a.u.为未指定信号单位。'
    return result


def osbad_statistics(raw,config):
    import numpy as np
    from osbad.stats import outlier_method
    from user_tools.workbench.preprocess import normalize_csv

    records,qc=normalize_csv(raw,config)
    method=config.get('method','iqr')
    field=config.get('field','voltage_V')
    if method not in ('sd','mad','iqr','zscore','mod_zscore'):raise ValueError('不支持的OSBAD统计方法。')
    if field not in ('voltage_V','current_A'):raise ValueError('字段只能是voltage_V或current_A。')
    differences=[(records[i]['source_row'],records[i][field]-records[i-1][field]) for i in range(1,len(records))
        if records[i]['segment']==records[i-1]['segment'] and records[i][field] is not None and records[i-1][field] is not None]
    if len(differences)<5:raise ValueError('需要至少5个同时间段有效差分。')
    values=np.asarray([d for _,d in differences],dtype=float)
    if method in ('mad','mod_zscore') and np.median(np.abs(values-np.median(values)))==0:
        raise ValueError('差分MAD为零，无法使用此方法；请选择IQR或SD。')
    if method=='zscore' and np.std(values,ddof=1)==0:raise ValueError('差分标准差为零，无法计算Z分数。')
    detector=outlier_method[method]
    indexes,low,high=detector.compute(values,**detector.params.copy())
    findings=[{'source_row':differences[int(i)][0],'difference':float(values[int(i)])} for i in indexes[:100]]
    return {'backend':'OSBAD 1.7.0 stats','method':method,'field':field,'count':len(indexes),
        'threshold_low':float(low),'threshold_high':float(high),'suspects':findings,'quality':qc,
        'scope':'仅使用OSBAD统计检测器，筛查同时间段相邻差分；正常工况切换也可能被标出。不是完整OSBAD基准或电池故障诊断。'}


def main():
    kind,config_path,source_path,out_path=sys.argv[1:5]
    config=json.loads(Path(config_path).read_text(encoding='utf-8'))
    if kind=='cv_sim':result=cv_surface(config)
    elif kind=='ixdat':result=ixdat_alignment(Path(source_path).read_bytes(),config)
    elif kind=='osbad':result=osbad_statistics(Path(source_path).read_bytes(),config)
    elif kind=='hardcarbon_train':
        from user_tools.workbench.sodium_learning import hardcarbon_train
        result=hardcarbon_train(Path(source_path).read_bytes(),config,Path(out_path).parent)
    elif kind=='soh_train':
        from user_tools.workbench.sodium_learning import soh_train
        result=soh_train(Path(source_path).read_bytes(),config,Path(out_path).parent)
    elif kind=='soh_predict':
        from user_tools.workbench.sodium_learning import soh_predict
        result=soh_predict(Path(source_path).read_bytes(),config,Path(out_path).parent,config['_model_path'],config['_model_sha256'])
    elif kind=='hardcarbon_predict':
        from user_tools.workbench.sodium_learning import hardcarbon_predict
        result=hardcarbon_predict(Path(source_path).read_bytes(),config,Path(out_path).parent,config['_model_path'],config['_model_sha256'])
    elif kind=='hardcarbon_joint_train':
        from user_tools.workbench.hardcarbon_joint import train
        result=train(Path(source_path).read_bytes(),config,Path(out_path).parent)
    elif kind=='hardcarbon_joint_recommend':
        from user_tools.workbench.hardcarbon_joint import recommend
        result=recommend(Path(source_path).read_bytes(),config,config['_model_path'],config['_model_sha256'])
    elif kind=='hardcarbon_ax_mobo':
        from user_tools.workbench.hardcarbon_joint import ax_mobo
        result=ax_mobo(Path(source_path).read_bytes(),config)
    elif kind=='sodium_identify':
        from user_tools.workbench.sodium_identification import run
        result=run(Path(source_path).read_bytes(),config,Path(out_path).parent)
    elif kind in ('hardcarbon_shap','uncertainty_audit','ax_recommend','helao_plan'):
        from user_tools.workbench import research_extensions
        result=getattr(research_extensions,kind)(Path(source_path).read_bytes(),config)
    else:raise ValueError('未知上游功能。')
    Path(out_path).write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')


if __name__=='__main__':
    main()
