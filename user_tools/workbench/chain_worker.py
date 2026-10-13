"""Nested group out-of-fold process -> structure -> performance surrogate."""
import json
from pathlib import Path
import numpy as np
from sklearn.model_selection import GroupKFold
from user_tools.workbench.ml_worker import fit_bundle,predict_bundle,group_metrics,write_csv
from user_tools.workbench.ml_calibration import split_groups,calibrate
from user_tools.workbench.ml_data import number

def fields_for(keys,kind='numeric'):
    return [{'key':k,'label':k,'kind':kind,'stage':'process'} for k in keys]

def fit_chain(rows,fields,config):
    process=config['process_features'];intermediates=config['intermediates']
    process_fields=[f for f in fields if f['key'] in process]
    groups=[r['group_id'] for r in rows]
    if len(set(groups))<4:raise ValueError('级联内层需要至少4个独立工艺组。')
    surrogate_rows=[dict(r) for r in rows]
    for tr,te in GroupKFold(n_splits=min(3,len(set(groups)))).split(rows,groups=groups):
        for key in intermediates:
            training=[{**rows[i],'target':float(rows[i][key])} for i in tr]
            gp=fit_bundle(training,process_fields,config,'gp')
            mu,_=predict_bundle(gp,[rows[i] for i in te])
            for i,value in zip(te,mu):surrogate_rows[i][key]=float(value)
    structural={key:fit_bundle([{**r,'target':float(r[key])} for r in rows],process_fields,config,'gp') for key in intermediates}
    second=fit_bundle(surrogate_rows,process_fields+fields_for(intermediates),config,'gp')
    return {'structural':structural,'performance':second,'fields':process_fields,'config':config}

def chain_predict(model,rows,count=128):
    results=[]
    for row in rows:
        rng=np.random.default_rng(42);samples=[dict(row) for _ in range(count)];structural={};valid=np.ones(count,bool)
        for key,gp in model['structural'].items():
            mu,sd=predict_bundle(gp,[row],std=True);values=rng.normal(mu[0],sd[0],count)
            bounds=model['config'].get('intermediate_bounds',{}).get(key)
            if bounds:
                if len(bounds)!=2:raise ValueError('结构描述符边界需[下限,上限]，不限制可填null。')
                if bounds[0] is not None:valid&=values>=float(bounds[0])
                if bounds[1] is not None:valid&=values<=float(bounds[1])
            structural[key]={'mean':float(mu[0]),'latent_std':float(sd[0])}
            for r,v in zip(samples,values):r[key]=float(v)
        if np.sum(valid)<max(16,count//4):raise ValueError('结构预测大量违反声明的物理边界，不能继续级联。')
        mu,sd=predict_bundle(model['performance'],[r for r,ok in zip(samples,valid) if ok],std=True)
        process_var=float(np.var(mu));conditional_var=float(np.mean(sd**2))
        results.append({'record_id':row['record_id'],'prediction':float(np.mean(mu)),
                        'propagated_std':float(np.sqrt(process_var+conditional_var)),
                        'structure_induced_variance':process_var,'conditional_performance_variance':conditional_var,
                        'structural_predictions':structural,'invalid_structure_fraction':float(1-np.mean(valid))})
    return results

def run_chain(dataset,config,prediction_rows,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    process=config.get('process_features',[]);intermediates=config.get('intermediates',[])
    catalog={f['key']:f for f in dataset['fields']}
    if not process or not 1<=len(intermediates)<=5 or set(process)&set(intermediates) or dataset['target'] in set(process+intermediates):
        raise ValueError('请选择互不重叠的工艺输入、1–5个结构中间量和性能目标。')
    if any(k not in catalog or catalog[k]['stage']!='process' for k in process):raise ValueError('第一阶段仅使用实验前已知工艺。')
    if any(k not in catalog or catalog[k]['kind']!='numeric' for k in intermediates):raise ValueError('中间表征需数值列。')
    good=[r for r in dataset['rows'] if all(number(r.get(k)) is not None for k in intermediates)]
    missing=[{'record_id':r['record_id'],'missing':[k for k in intermediates if number(r.get(k)) is None]} for r in dataset['rows'] if r not in good]
    if len({r['group_id'] for r in good})<8:raise ValueError('完整工艺/结构/性能数据至少需要8个独立组。缺失中间量请补测，不能造标签。')
    dev,cal,plan=split_groups(good,config.get('alpha',.1),minimum_training_groups=8)
    groups=[r['group_id'] for r in dev];oof=[]
    for fold,(tr,te) in enumerate(GroupKFold(n_splits=min(5,len(set(groups)))).split(dev,groups=groups)):
        model=fit_chain([dev[i] for i in tr],dataset['fields'],config)
        pred=chain_predict(model,[dev[i] for i in te])
        for i,p in zip(te,pred):oof.append({**p,'fold':fold,'group_id':dev[i]['group_id'],'observed':float(dev[i]['target']), 'predicted':p['prediction']})
    final=fit_chain(dev,dataset['fields'],config);interval=plan
    if cal:
        cp=chain_predict(final,cal);interval={**plan,**calibrate(cal,[p['prediction'] for p in cp],config.get('alpha',.1))}
    if any(r.get('_sampling')=='adaptive_feedback' for r in good):interval['coverage_warning']='含自适应反馈，仅作残差带诊断'
    predictions=chain_predict(final,prediction_rows) if prediction_rows else []
    q=interval.get('residual_threshold')
    for row,pred in zip(prediction_rows,predictions):
        alerts=[]
        for f in final['fields']:
            key=f['key'];value=row.get(key)
            if value in (None,''):alerts.append(key+'缺失');continue
            if f['kind']=='numeric':
                vals=[number(r.get(key)) for r in dev if number(r.get(key)) is not None]
                if number(value) is None or (vals and not min(vals)<=float(value)<=max(vals)):alerts.append(key+'超出训练范围')
            elif str(value) not in {str(r.get(key)) for r in dev}:alerts.append(key+'未见类别')
        if row.get('batch_id') not in {r['batch_id'] for r in dev}:alerts.append('未知原料批次')
        pred.update(interval_lower=pred['prediction']-q if q is not None else None,
                    interval_upper=pred['prediction']+q if q is not None else None,alerts=alerts,
                    usable_for_model_exploration=not alerts,usable_for_decision=False,
                    decision_reason='范围内也不等于通过独立材料验证；选点不继承区间名义覆盖')
    result={'evidence_type':'synthetic_process_structure_chain' if config.get('data_kind')=='synthetic_demo' else 'user_process_structure_chain','process_features':process,'intermediates':intermediates,
            'target':dataset['target'],'training_samples':len(dev),'calibration':interval,'group_oof_metrics':group_metrics(oof),
            'oof':oof,'predictions':predictions,'missing_intermediate_measurements':missing,
            'scope':'外层按工艺组留出；性能GP训练输入为内层折外结构预测，而非训练内拟合值。结构GP相互独立，Monte Carlo用全方差公式传播结构与性能模型不确定性；固定核近似不含超参数/模型失配不确定性。独立留组校准不足时区间无界，级联是数据代理模型，不是材料因果机制或PyBaMM验证。'}
    write_csv(out/'chain_oof.csv',[{k:r[k] for k in ['record_id','group_id','fold','observed','predicted','propagated_std']} for r in oof])
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    (out/'ui_result.json').write_text(json.dumps({'result':result,'curves':[]},ensure_ascii=False,allow_nan=False),encoding='utf-8')
    return result
