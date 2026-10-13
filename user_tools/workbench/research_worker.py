"""Finite multi-objective noisy HVI, independent calibration and decision diagnostics."""
import json
from pathlib import Path
import numpy as np
from scipy.stats import qmc
from sklearn.model_selection import GroupKFold
from user_tools.workbench.ml_worker import fit_bundle,predict_bundle,frame,group_metrics,write_csv
from user_tools.workbench.ml_calibration import split_groups,calibrate
from user_tools.workbench.ml_data import number
from user_tools.workbench.research_data import input_conflicts,known_objective_conflicts

def pareto(values):
    y=np.asarray(values,float)
    return [i for i in range(len(y)) if not any(np.all(y[j]>=y[i]) and np.any(y[j]>y[i]) for j in range(len(y)) if j!=i)]

def feasible(values,objectives):
    ok=np.ones(np.asarray(values).shape[:-1],bool)
    for j,o in enumerate(objectives):
        if o.get('lower') not in (None,''):ok&=values[...,j]>=float(o['lower'])
        if o.get('upper') not in (None,''):ok&=values[...,j]<=float(o['upper'])
    return ok

def posterior_draws(bundle,rows,count,seed):
    if bundle['name']=='mean':return np.full((count,len(rows)),bundle['mean'])
    x=bundle['prep'].transform(frame(rows,bundle['fields']))
    return bundle['estimator'].sample_y(x,n_samples=count,random_state=seed).T*bundle['scale']+bundle['center']

def noisy_hvi(draws,baseline_count,objectives,reference,count_grid=1024):
    """q=1 joint latent posterior + shared Sobol hypervolume cubature, up to 5D."""
    signs=np.array([1 if o['direction']=='maximize' else -1 for o in objectives]);utilities=draws*signs
    u=utilities;ref=np.asarray(reference)
    upper=np.maximum(u.max(axis=(0,1)),ref+1e-9);volume=float(np.prod(upper-ref))
    samples=qmc.Sobol(d=len(objectives),scramble=True,seed=91).random_base2(int(np.log2(count_grid)))
    grid=ref+samples*(upper-ref)
    gains=np.zeros((len(draws),draws.shape[1]-baseline_count));passing=np.zeros(gains.shape[1])
    for k,values in enumerate(u):
        valid=feasible(draws[k],objectives)
        old=values[:baseline_count][valid[:baseline_count]]
        covered=np.any(np.all(old[:,None,:]>=grid[None,:,:],axis=2),axis=0) if len(old) else np.zeros(len(grid),bool)
        uncovered=grid[~covered]
        for i,candidate in enumerate(values[baseline_count:]):
            if valid[baseline_count+i]:
                passing[i]+=1
                gains[k,i]=volume*np.sum(np.all(candidate>=uncovered,axis=1))/len(grid)
    return gains.mean(axis=0),gains.std(axis=0,ddof=1)/np.sqrt(len(draws)),passing/len(draws)

def validate_gp(rows,fields,config):
    groups=[r['group_id'] for r in rows]
    if len(set(groups))<5:return {'ready':False,'reason':'独立观测组不足5个'}
    predictions=[];base=[]
    for fold,(tr,te) in enumerate(GroupKFold(n_splits=min(5,len(set(groups)))).split(rows,groups=groups)):
        training=[rows[i] for i in tr];testing=[rows[i] for i in te]
        try:
            gp=fit_bundle(training,fields,config,'gp');mu,_=predict_bundle(gp,testing)
            for r,p in zip(testing,mu):
                predictions.append({'group_id':r['group_id'],'predicted':float(p),'observed':r['target']})
                base.append({'group_id':r['group_id'],'predicted':float(np.mean([r['target'] for r in training])),'observed':r['target']})
        except Exception as e:return {'ready':False,'reason':'分组验证失败：'+str(e)}
    metric=group_metrics(predictions);baseline=group_metrics(base)
    return {'ready':metric['mae']<baseline['mae'],'gp_mae':metric['mae'],'mean_mae':baseline['mae'],
            'reason':'GP仅作探索；不代表前瞻验证' if metric['mae']<baseline['mae'] else 'GP未胜过均值基线'}

def objective_models(dataset,config):
    models=[];diagnostics=[]
    observed=[r for r in dataset['rows'] if r['status'] in ['completed','partial']]
    alpha=float(config.get('alpha',.1))
    if config.get('joint_calibration'):alpha/=max(1,sum(not o.get('known') for o in dataset['objectives']))
    for obj in dataset['objectives']:
        key=obj['key']
        if obj.get('known'):
            models.append(None);diagnostics.append({'key':key,'known':True,'ready':True,'calibration':{'finite':True,'reason':'用户提供的情景点值，非经校准预测'}});continue
        rows=[{**r,'target':float(r[key])} for r in observed if number(r.get(key)) is not None]
        if len({r['group_id'] for r in rows})<5:raise ValueError(key+'至少需要5个独立已观测工艺组；部分目标可以单独补测。')
        dev,cal,plan=split_groups(rows,alpha)
        gp=fit_bundle(dev,dataset['fields'],config,'gp')
        calibrated=None;interval=plan
        if cal:
            calibrated=gp;cmu,_=predict_bundle(calibrated,cal)
            interval={**plan,**calibrate(cal,cmu,alpha)}
        check=validate_gp(dev,dataset['fields'],config)
        models.append({'gp':gp,'calibrated':calibrated,'interval':interval,'training_rows':dev})
        diagnostics.append({'key':key,'known':False,'calibration':interval,'acquisition_training_ids':[r['record_id'] for r in dev],**check})
    return models,diagnostics

def measurement_advice(dataset,diagnostics):
    advice=[];observed=[r for r in dataset['rows'] if r['status'] in ['completed','partial']]
    for d in diagnostics:
        if d.get('known'):continue
        missing=[r['record_id'] for r in observed if number(r.get(d['key'])) is None]
        if missing:advice.append({'type':'complete_missing_target','target':d['key'],'record_ids':missing[:10],'reason':'已制备样品缺少这一目标，优先完成匹配测试而非补零'})
        if not d['calibration'].get('finite') or d['calibration'].get('coverage_warning'):advice.append({'type':'independent_calibration','target':d['key'],
            'reason':'独立校准组不足，补充非自适应的代表性工艺组；不能把重复时间点当新组'})
        if not d.get('ready'):advice.append({'type':'model_diagnosis','target':d['key'],'reason':d.get('reason')})
        groups={}
        for r in observed:
            if number(r.get(d['key'])) is not None:groups.setdefault(r['group_id'],[]).append(r)
        replicated=[rs for rs in groups.values() if len(rs)>1]
        variances=[float(np.var([r[d['key']] for r in rs],ddof=1)) for rs in replicated]
        if not variances:
            sorted_rows=sorted([r for r in observed if number(r.get(d['key'])) is not None],key=lambda r:r[d['key']],reverse=True)
            advice.append({'type':'repeat_condition','target':d['key'],'record_ids':[r['record_id'] for r in sorted_rows[:2]],
                           'reason':'缺少独立重复，先确认高响应条件的实验波动；这是规则建议，未声称最优信息增益'})
        else:advice.append({'type':'replicate_noise','target':d['key'],'replicate_groups':len(variances),
                           'mean_within_group_variance':float(np.mean(variances)),'reason':'重复方差与模型误差分开报告；工艺组仍是验证单位'})
    failures=[r for r in dataset['rows'] if r['status'].startswith('failed_')]
    for r in failures:advice.append({'type':r['status'],'record_ids':[r['record_id']],
        'reason':'测量故障需修复/复测，制备失败需核查可实施性；均未赋零性能'})
    return advice

def multi_run(dataset,config,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    objectives=dataset['objectives'];fields=dataset['fields'];completed=[r for r in dataset['rows'] if r['status']=='completed']
    observed=[r for r in dataset['rows'] if r['status'] in ['completed','partial']]
    candidates=[r for r in dataset['rows'] if r['status']=='candidate']
    conflicts={r['record_id']:input_conflicts(r,fields,observed,config)+known_objective_conflicts(r,objectives) for r in candidates}
    eligible=[r for r in candidates if not conflicts[r['record_id']]]
    if not eligible:raise ValueError('没有满足输入范围、已知目标和配方约束的未测候选。')
    sparse=[o for o in objectives if not o.get('known') and len({r['group_id'] for r in observed if number(r.get(o['key'])) is not None})<5]
    if sparse:
        pool=observed+eligible;matrix=[]
        for f in fields:
            values=[r.get(f['key']) for r in pool]
            if f['kind']=='numeric':
                if any(number(v) is None for v in values):raise ValueError('初始设计需要完整已知输入。')
                a=np.array(values,float);matrix.append(((a-a.min())/(np.ptp(a) or 1))[:,None])
            else:
                levels=sorted(set(str(v) for v in values));matrix.append(np.array([[float(str(v)==level) for level in levels] for v in values]))
        x=np.concatenate(matrix,axis=1);xc=x[len(observed):]
        distance=np.linalg.norm(xc[:,None]-x[None,:,:],axis=2)
        scores=distance[:,:len(observed)].min(axis=1) if observed else distance.mean(axis=1)
        best=eligible[int(np.argmax(scores))]
        result={'evidence_type':'synthetic_multiobjective_campaign' if config.get('data_kind')=='synthetic_demo' else 'user_multiobjective_campaign','objectives':objectives,'features':[f['key'] for f in fields],
                'selected':{'record_id':best['record_id'],'record':best,'inputs':{f['key']:best[f['key']] for f in fields}},
                'ranking':[],'diagnostics':[],'pareto_completed_ids':[],'recommendation_status':'initial_space_filling_design',
                'measurement_advice':[{'type':'initial_design','target':o['key'],'reason':'独立标签不足5组；按已知输入覆盖空间建议新条件，不是性能最优预测'} for o in sparse],
                'excluded_candidates':conflicts,'scope':'初始空间填充设计，仅读候选输入和已观测位置，不读取未来标签，不声称性能提升。'}
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        (out/'ui_result.json').write_text(json.dumps({'result':result,'curves':[]},ensure_ascii=False,allow_nan=False),encoding='utf-8')
        write_csv(out/'campaign.csv',dataset['rows']);return result
    models,diagnostics=objective_models(dataset,config)
    # Calibration outcomes are excluded from BOTH GP likelihood and HVI baseline.
    training_sets=[{r['record_id'] for r in m['training_rows']} for m in models if m is not None]
    baseline_ids=set.intersection(*training_sets) if training_sets else {r['record_id'] for r in completed}
    completed=[r for r in completed if r['record_id'] in baseline_ids]
    allrows=completed+eligible;count=int(config.get('mc_samples',64));grid=int(config.get('hv_grid',1024))
    if count not in [32,64,128,256] or grid not in [512,1024,2048,4096]:raise ValueError('MC/超体积网格数量不支持。')
    draws=[];means=[];stds=[];intervals=[]
    for j,(obj,m) in enumerate(zip(objectives,models)):
        if obj.get('known'):
            vals=np.array([float(r[obj['key']]) for r in allrows]);draws.append(np.broadcast_to(vals,(count,len(vals))))
            means.append(vals[len(completed):]);stds.append(np.zeros(len(eligible)));intervals.append([{'lower':v,'upper':v,'status':'known_scenario_point'} for v in means[-1]])
        else:
            draws.append(posterior_draws(m['gp'],allrows,count,42+j*71));mu,sd=predict_bundle(m['gp'],eligible,std=True)
            means.append(mu);stds.append(sd);q=m['interval'].get('residual_threshold')
            cmu,_=predict_bundle(m['calibrated'],eligible) if m['calibrated'] else (mu,None)
            intervals.append([{'center':float(v),'lower':float(v-q) if q is not None else None,'upper':float(v+q) if q is not None else None,
                               'status':'heldout_residual_diagnostic_not_selected_coverage' if q is not None else 'unbounded'} for v in cmu])
    draws=np.stack(draws,axis=-1);mu=np.array(means).T;sd=np.array(stds).T
    signs=np.array([1 if o['direction']=='maximize' else -1 for o in objectives])
    if completed:
        ys=np.array([[float(r[o['key']]) for o in objectives] for r in completed]);utilities=ys*signs
        reference=utilities.min(axis=0)-.1*np.maximum(np.ptp(utilities,axis=0),1.)
        front=pareto(utilities[feasible(ys,objectives)]);feasible_completed=[r for r,ok in zip(completed,feasible(ys,objectives)) if ok]
        pareto_records=[feasible_completed[i]['record_id'] for i in front]
    else:
        references=[]
        for j,(o,m) in enumerate(zip(objectives,models)):
            values=[float(r[o['key']])*signs[j] for r in m['training_rows']] if m else [float(r[o['key']])*signs[j] for r in allrows]
            references.append(min(values)-.1*max(np.ptp(values),1.))
        reference=np.array(references);pareto_records=[]
    gain,se,pf=noisy_hvi(draws,len(completed),objectives,reference,grid)
    ranking=[]
    for i,row in enumerate(eligible):
        constraints_pass=True
        for j,o in enumerate(objectives):
            interval=intervals[j][i]
            if o.get('lower') not in (None,'') and (interval.get('lower') is None or interval['lower']<float(o['lower'])):constraints_pass=False
            if o.get('upper') not in (None,'') and (interval.get('upper') is None or interval['upper']>float(o['upper'])):constraints_pass=False
        ranking.append({'record_id':row['record_id'],'inputs':{f['key']:row[f['key']] for f in fields},'record':row,
                        'predictions':{o['key']:{'posterior_mean':float(mu[i,j]),'latent_std':float(sd[i,j]),'calibrated_interval':intervals[j][i]} for j,o in enumerate(objectives)},
                        'expected_hypervolume_gain':float(gain[i]),'outer_mc_standard_error':float(se[i]),'sampled_feasible_fraction':float(pf[i]),
                        'calibrated_constraints_pass':constraints_pass})
    ranking.sort(key=lambda r:(-r['expected_hypervolume_gain'],r['record_id']))
    all_ready=all(d.get('ready') for d in diagnostics);all_calibrated=all(d['calibration'].get('finite') for d in diagnostics)
    adaptive=any(r.get('_sampling')=='adaptive_feedback' for r in observed)
    if adaptive:
        all_calibrated=all(o.get('known') for o in objectives)
        for d in diagnostics:
            if not d.get('known'):d['calibration']['coverage_warning']='已含自适应反馈；有限残差带不继承名义覆盖保证'
    decision_ready=all_ready and all_calibrated
    # Residual threshold values never select the candidate. Posterior probability
    # is an exploratory model belief, not a distribution-free coverage guarantee.
    selectable=[r for r in ranking if r['expected_hypervolume_gain']>0 and ((decision_ready and r['sampled_feasible_fraction']>=.95) or config.get('allow_exploration') is True)]
    selected=selectable[0] if selectable else None
    status='model_posterior_exploration' if selected and decision_ready else 'uncalibrated_exploration' if selected else 'needs_measurement_or_no_gain'
    result={'evidence_type':'synthetic_multiobjective_campaign' if config.get('data_kind')=='synthetic_demo' else 'user_multiobjective_campaign','objectives':objectives,'features':[f['key'] for f in fields],
            'ranking':ranking,'selected':selected,'recommendation_status':status,'pareto_completed_ids':pareto_records,
            'diagnostics':diagnostics,'measurement_advice':measurement_advice(dataset,diagnostics),
            'adaptive_feedback_present':adaptive,
            'selected_candidate_coverage_guaranteed':False,
            'calibration_type':'Bonferroni误差分配用于独立新样本；选点无覆盖保证' if config.get('joint_calibration') else '边际残差带；选点无名义覆盖保证',
            'excluded_candidates':conflicts,'mc_samples':count,'hv_sobol_points':grid,'utility_reference':reference.tolist(),
            'scope':'有限候选q=1联合潜在GP抽样与共享Sobol积分；支持1–5目标，输出GP独立，报告原始目标单位乘积的HVI近似，外层MC标准误不含积分误差。校准标签不参与GP拟合、HVI基线、参考点或候选排序；残差阈值仅作事后诊断。经自适应选择的候选不具有名义覆盖保证，需要新的独立验证；模型可行比例也不是可靠性认证。LCA/成本为用户情景点值，未传播清单不确定性。'}
    (out/'ui_result.json').write_text(json.dumps({'result':result,'curves':[]},ensure_ascii=False,allow_nan=False),encoding='utf-8')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    write_csv(out/'campaign.csv',dataset['rows'])
    return result
