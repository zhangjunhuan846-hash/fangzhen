"""Paired hard-carbon capacity/ICE group validation and finite candidate selection."""
from __future__ import annotations
import csv
import hashlib
import io
import unicodedata
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit
from user_tools.workbench.multichem_analysis import table, value
from user_tools.workbench.sodium_learning import grouped_fit


def paired_frame(raw, mode):
    if mode in ('measured','measured_extended'):
        features=['carbonization_temperature_C','d002_nm','id_ig','ssa_m2_g','electrolyte_type','current_density_mA_g']
        if mode=='measured_extended':features+=['carbonization_time_h','heating_rate_C_min','pore_volume_cm3_g','lc_nm','la_nm']
        categories=['electrolyte_type']
    elif mode in ('process','process_precursor'):
        features=['carbonization_temperature_C','carbonization_time_h','heating_rate_C_min','current_density_mA_g']
        categories=[]
        if mode=='process_precursor':
            features+=['precursor_type','electrolyte_type'];categories=['precursor_type','electrolyte_type']
    else:raise ValueError('feature_mode仅支持measured、measured_extended、process或process_precursor。')
    original=table(raw,['doi','mapping_found','ice','reversible_capacity_mAh_g']+features)
    excluded=[]
    records=[]
    for idx,src in enumerate(original):
        source=unicodedata.normalize('NFKC',src['doi']).strip()
        if not source or src['mapping_found'].strip().lower()!='true':
            excluded.append({'source_row':idx+2,'reason':'来源映射缺失'});continue
        try:
            capacity=value(src['reversible_capacity_mAh_g'],'可逆容量')
            ice=value(src['ice'],'ICE')
        except ValueError:
            excluded.append({'source_row':idx+2,'reason':'ICE或可逆容量缺失'});continue
        if not (0<capacity<=1000 and 0<=ice<=1):
            excluded.append({'source_row':idx+2,'reason':'ICE或可逆容量超出范围'});continue
        group='paper_'+hashlib.sha256(source.casefold().encode('utf8')).hexdigest()[:16]
        records.append({'record_id':'source_row_'+str(idx+2),'group_id':group,'batch_id':group,
                        **{f:src.get(f,'') for f in features},'ice':ice,'capacity_mAh_g':capacity})
    if not records:raise ValueError('没有同时具备有效ICE、容量与文献来源的样本。')
    return pd.DataFrame(records),features,categories,excluded


def train(raw,config,out):
    frame,features,categories,excluded=paired_frame(raw,config.get('feature_mode','measured'))
    seed=config.get('split_seed',42)
    if isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<=10000:raise ValueError('split_seed须为0–10000整数。')
    groups=frame.group_id.astype(str).to_numpy()
    if len(set(groups))<4:raise ValueError('至少需要4个独立来源组。')
    _,test=next(GroupShuffleSplit(n_splits=1,test_size=.25,random_state=seed).split(frame,groups=groups))
    holdout=sorted(set(groups[test]));out=Path(out);out.mkdir(parents=True,exist_ok=True)
    results={};models={}
    for target in ('ice','capacity_mAh_g'):
        work=frame.rename(columns={target:'target'})
        output=out/target
        results[target]=grouped_fit(work,features,categories,output,
            {'kind':'hardcarbon_joint','target':target,'feature_mode':config.get('feature_mode','measured')},
            seed,config.get('algorithms'),holdout_groups=holdout)
        models[target]=joblib.load(output/'trained_model.joblib')
    bundle=out/'trained_model.joblib'
    # Suspend optimization when an objective has not beaten the baseline by 5%.
    # This holdout check is a deployment gate, not a model-selection score.
    gate={target:bool(res['holdout']['mae'] <= .95*res['holdout_mean_baseline']['mae']) for target,res in results.items()}
    joblib.dump({'kind':'hardcarbon_joint','features':features,'categories':categories,'holdout_beats_mean':gate,
                 'feature_mode':config.get('feature_mode','measured'),'models':models},bundle)
    a=pd.read_csv(out/'ice'/'holdout.csv'); b=pd.read_csv(out/'capacity_mAh_g'/'holdout.csv')
    hold=a[['record_id','group_id','observed','predicted','baseline_mean']].merge(
        b[['record_id','observed','predicted','baseline_mean']],on='record_id',validate='one_to_one',suffixes=('_ice','_capacity_mAh_g'))
    hold.to_csv(out/'holdout.csv',index=False,encoding='utf-8-sig')
    frame.to_csv(out/'prepared.csv',index=False,encoding='utf-8-sig')
    return {'targets':results,'model_sha256':hashlib.sha256(bundle.read_bytes()).hexdigest(),
            'eligible_records':len(frame),'excluded_count':len(excluded),'holdout_group_ids':holdout,
            'feature_mode':config.get('feature_mode','measured'),'features':features,'holdout_beats_mean_by_5_percent':gate,
            'scope':'两个目标使用同一批来源明确且具备配对标签的样本，共用留出文献组；每个模型仅用训练组交叉验证选择。留出误差未比均值基线低5%时暂停Pareto推荐。measured包含制备后表征，process仅使用已记录工艺与测试电流；预测和Pareto排序需要独立实验验证。文献字符串分组不保证材料家族隔离。'}


def recommend(raw,config,model_path,expected_hash):
    path=Path(model_path)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected_hash:raise ValueError('模型文件校验失败。')
    bundle=joblib.load(path)
    if bundle.get('kind')!='hardcarbon_joint':raise ValueError('请选择硬碳联合训练模型。')
    features=bundle['features']; categories=bundle['categories'];rows=table(raw,['record_id']+features,max_rows=1000)
    ids=[r['record_id'].strip() for r in rows]
    if any(not x for x in ids) or len(set(ids))!=len(ids):raise ValueError('record_id必须非空且唯一。')
    frame=pd.DataFrame(rows)
    for key in features:
        if key in categories:
            if any(not str(x).strip() for x in frame[key]):raise ValueError('类别描述符不能为空。')
            frame[key]=frame[key].astype(str)
        else:frame[key]=[value(v,key) for v in frame[key]]
    predictions={k:m['model'].predict(frame[features]) for k,m in bundle['models'].items()}
    min_ice=float(config.get('minimum_ice',0));min_capacity=float(config.get('minimum_capacity_mAh_g',0))
    if not np.isfinite([min_ice,min_capacity]).all() or not 0<=min_ice<=1 or not 0<=min_capacity<=1000:raise ValueError('目标下限无效。')
    gate=bundle.get('holdout_beats_mean',{})
    if not isinstance(config.get('allow_exploratory',False),bool):raise ValueError('allow_exploratory必须是布尔值。')
    allow=bool(all(gate.values()) and len(gate)==2) or config.get('allow_exploratory',False)
    results=[]
    for i,row in enumerate(frame.to_dict('records')):
        alerts=[]
        for saved in bundle['models'].values():
            alerts += [k+'超出训练范围' for k,(lo,hi) in saved['training_ranges'].items() if not lo<=row[k]<=hi]
            alerts += [k+'为未见类别' for k,levels in saved['training_levels'].items() if row[k] not in levels]
        ice=float(predictions['ice'][i]);capacity=float(predictions['capacity_mAh_g'][i])
        valid=0<=ice<=1 and capacity>0 and not alerts
        results.append({'record_id':ids[i],'predicted_ice':ice,'predicted_capacity_mAh_g':capacity,
                        'alerts':sorted(set(alerts)),'eligible':bool(valid and ice>=min_ice and capacity>=min_capacity),'pareto':False})
    for a in results:
        if not a['eligible'] or not allow:continue
        a['pareto']=not any(b['eligible'] and b is not a and b['predicted_ice']>=a['predicted_ice'] and
            b['predicted_capacity_mAh_g']>=a['predicted_capacity_mAh_g'] and
            (b['predicted_ice']>a['predicted_ice'] or b['predicted_capacity_mAh_g']>a['predicted_capacity_mAh_g']) for b in results)
    return {'predictions':results,'feature_mode':bundle['feature_mode'],'holdout_beats_mean_by_5_percent':gate,'pareto_enabled':allow,
            'scope':'对用户给定候选的两个模型点预测做非支配筛选，不是贝叶斯采集函数或真实实验验证；若任何目标未比留出均值基线低5%，默认暂停Pareto，可设置allow_exploratory=true查看探索性结果。超出训练范围、未知类别或物理范围异常的候选不进入Pareto集合。process模式仍需预先确定原料、测试电流等条件，不能保证跨原料泛化。'}


def ax_mobo(raw,config):
    """Run Ax on observed paired records, without pretending predicted labels are experiments."""
    from user_tools.workbench.research_extensions import ax_recommend
    frame,features,_,_=paired_frame(raw,'process')
    parameters=config.get('parameters',[])
    names=[p.get('name') for p in parameters] if isinstance(parameters,list) else []
    if not 1<=len(names)<=3 or not set(names).issubset(set(features)) or len(names)!=len(set(names)):
        raise ValueError('parameters需指定1–3个工艺或测试变量，且不能重复。')
    thresholds=config.get('thresholds',{})
    ice=value(thresholds.get('ice'),'ice阈值');capacity=value(thresholds.get('capacity_mAh_g'),'容量阈值')
    if not 0<=ice<=1 or not 0<=capacity<=1000:raise ValueError('双目标参考阈值无效。')
    for name in names:frame[name]=pd.to_numeric(frame[name],errors='coerce')
    frame=frame.dropna(subset=names).copy()
    for p in parameters:
        lo,hi=map(float,p['bounds'])
        if not np.isfinite([lo,hi]).all() or lo>=hi:raise ValueError('参数边界无效。')
        frame=frame[frame[p['name']].between(lo,hi)]
    # Choose one sample per paper deterministically to reduce dominance by large studies.
    frame=frame.sort_values(['group_id','record_id']).groupby('group_id',as_index=False).first()
    frame=frame.sample(frac=1,random_state=42).drop_duplicates(names).head(100)
    if len(frame)<5:raise ValueError('符合边界的独立来源与参数组合不足5个。')
    data=frame[names+['ice','capacity_mAh_g']].to_csv(index=False).encode()
    result=ax_recommend(data,{'parameters':parameters,'objectives':[{'name':'ice','threshold':ice},
            {'name':'capacity_mAh_g','threshold':capacity}]})
    result.update(eligible_groups=int(len(frame)),objectives=['ice','capacity_mAh_g'],
                  scope='调用Ax/BoTorch对公开文献配对实测数据生成双目标候选；每篇最多取一条，跨论文原料和测试条件可能混杂。参数范围由用户声明，目标阈值是采集函数参考点，候选未经实验验证，不发送设备。')
    return result
