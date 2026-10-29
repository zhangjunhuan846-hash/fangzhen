"""Grouped holdout experiments for hard carbon and partial-charge SOH."""
from __future__ import annotations
import csv
import hashlib
import io
import json
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from user_tools.workbench.multichem_analysis import prepare_hardcarbon,table,value


def grouped_fit(frame,features,categories,out,metadata,seed=42,algorithms=None,holdout_groups=None,selection_policy='mean_group'):
    groups=frame['group_id'].astype(str).to_numpy()
    unique=np.unique(groups)
    if len(unique)<4:raise ValueError('至少需要4个独立文献或电芯组。')
    x=frame[features].copy();y=frame['target'].to_numpy(dtype=float)
    numeric=[f for f in features if f not in categories]
    for k in numeric:x[k]=pd.to_numeric(x[k],errors='coerce')
    for k in categories:x[k]=x[k].replace('',np.nan).fillna('missing').astype(str)
    if isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<=10000:raise ValueError('split_seed须为0–10000的整数。')
    if algorithms is None:algorithms=['mean','ridge','trees']
    if not isinstance(algorithms,list) or not algorithms or len(algorithms)!=len(set(algorithms)) or any(a not in ('mean','ridge','trees','trees_fine','gp','gp_short','gp_smooth','xgb','xgb_l1','catboost','catboost_mae','tabpfn','tabicl') for a in algorithms):
        raise ValueError('algorithms可选mean、ridge、trees、trees_fine、gp、gp_short、gp_smooth、xgb、xgb_l1、catboost、catboost_mae、tabpfn、tabicl，且不能重复。')
    if 'mean' not in algorithms:algorithms=['mean']+algorithms
    if selection_policy not in ('mean_group','worst_group','guarded_group'):raise ValueError('模型选择策略仅支持mean_group、worst_group或guarded_group。')
    if selection_policy=='guarded_group' and metadata.get('kind')!='partial_charge_soh':raise ValueError('guarded_group仅支持部分充电SOH。')
    if holdout_groups is None:
        split=GroupShuffleSplit(n_splits=1,test_size=.25,random_state=seed)
        train,test=next(split.split(x,y,groups))
    else:
        holdout=set(holdout_groups)
        if not holdout or not holdout<=set(groups):raise ValueError('指定留出电芯组不存在。')
        test=np.flatnonzero(np.isin(groups,list(holdout)));train=np.flatnonzero(~np.isin(groups,list(holdout)))
        if len(set(groups[train]))<3:raise ValueError('留出后至少需要三个训练组。')
    train_groups=groups[train]
    folds=list(GroupKFold(n_splits=min(4,len(set(train_groups)))).split(x.iloc[train],y[train],train_groups))
    if set(groups[train])&set(groups[test]):raise ValueError('训练与测试组重叠。')
    def pipeline(name):
        transformer=ColumnTransformer([('num',make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler()),numeric),
            ('cat',OneHotEncoder(handle_unknown='ignore'),categories)],remainder='drop')
        if name=='mean':model=DummyRegressor(strategy='mean')
        elif name=='ridge':model=Ridge(alpha=10)
        elif name in ('trees','trees_fine'):model=ExtraTreesRegressor(n_estimators=100,min_samples_leaf=2 if name=='trees_fine' else 4,random_state=42,n_jobs=1)
        elif name in ('gp','gp_short','gp_smooth'):
            length,noise={'gp':(1.,.01),'gp_short':(.5,.01),'gp_smooth':(2.,.03)}[name]
            model=GaussianProcessRegressor(kernel=ConstantKernel(1.,'fixed')*Matern(length_scale=length,nu=2.5),
                alpha=noise,optimizer=None,normalize_y=True)
        elif name in ('xgb','xgb_l1'):
            from xgboost import XGBRegressor
            model=XGBRegressor(n_estimators=120,max_depth=3,learning_rate=.05,reg_lambda=5,n_jobs=1,random_state=42,
                objective='reg:absoluteerror' if name=='xgb_l1' else 'reg:squarederror')
        elif name in ('catboost','catboost_mae'):
            from catboost import CatBoostRegressor
            model=CatBoostRegressor(iterations=120,depth=4,learning_rate=.05,l2_leaf_reg=5,thread_count=1,random_seed=42,verbose=False,allow_writing_files=False,
                loss_function='MAE' if name=='catboost_mae' else 'RMSE')
        elif name=='tabicl':
            from tabicl import TabICLRegressor
            model=TabICLRegressor(n_estimators=1,device='cpu',n_jobs=2,random_state=42)
        elif name=='tabpfn':
            from tabpfn import TabPFNRegressor
            from tabpfn.constants import ModelVersion
            model=TabPFNRegressor.create_default_for_version(ModelVersion.V2,n_estimators=1,device='cpu',random_state=42)
        return make_pipeline(transformer,model)
    def metric(obs,pred,g):
        per=[float(np.mean(np.abs(obs[g==v]-pred[g==v]))) for v in np.unique(g)]
        return {'mae':float(np.mean(per)),'rmse':float(np.sqrt(np.mean((obs-pred)**2))),
                'row_mae':float(np.mean(np.abs(obs-pred))),'worst_group_mae':max(per),'groups':len(per),'rows':len(obs)}
    comparisons=[]
    for name in algorithms:
        predictions=np.full(len(train),np.nan)
        guarded_cv=np.full(len(train),np.nan)
        for tr,va in folds:
            model=pipeline(name);model.fit(x.iloc[train].iloc[tr],y[train][tr]);predictions[va]=model.predict(x.iloc[train].iloc[va])
            if selection_policy=='guarded_group':
                transform=model.named_steps['columntransformer'];emb=transform.transform(x.iloc[train].iloc[tr]);target=transform.transform(x.iloc[train].iloc[va])
                if hasattr(emb,'toarray'):emb=emb.toarray();target=target.toarray()
                inner_groups=train_groups[tr];q=[]
                for group in np.unique(inner_groups):
                    keep=inner_groups!=group
                    d=NearestNeighbors(n_neighbors=1).fit(emb[keep]).kneighbors(emb[~keep])[0].ravel()
                    q.append(float(np.quantile(d,.95)))
                threshold=float(np.quantile(q,.95))
                dist=NearestNeighbors(n_neighbors=1).fit(emb).kneighbors(target)[0].ravel()
                guarded_cv[va]=np.where(dist>threshold,float(np.mean(y[train][tr])),predictions[va])
        item={'model':name,'cv':metric(y[train],predictions,train_groups)}
        if selection_policy=='guarded_group':item['guarded_cv']=metric(y[train],guarded_cv,train_groups)
        comparisons.append(item)
    score='worst_group_mae' if selection_policy=='worst_group' else 'mae'
    chosen=min(comparisons,key=lambda r:r['guarded_cv' if selection_policy=='guarded_group' else 'cv'][score])['model']
    model=pipeline(chosen);model.fit(x.iloc[train],y[train]);prediction=model.predict(x.iloc[test])
    baseline=pipeline('mean');baseline.fit(x.iloc[train],y[train]);baseline_pred=baseline.predict(x.iloc[test])
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    ranges={k:[float(x.iloc[train][k].min()),float(x.iloc[train][k].max())] for k in numeric
            if x.iloc[train][k].notna().any()}
    levels={k:sorted(set(x.iloc[train][k].astype(str))) for k in categories}
    guard=None;guarded_prediction=prediction.copy();distance=None
    if metadata.get('kind')=='partial_charge_soh':
        transformer=model.named_steps['columntransformer']
        embedding=transformer.transform(x.iloc[train]);target_embedding=transformer.transform(x.iloc[test])
        if hasattr(embedding,'toarray'):embedding=embedding.toarray();target_embedding=target_embedding.toarray()
        group_q=[]
        for group in np.unique(train_groups):
            keep=train_groups!=group
            d=NearestNeighbors(n_neighbors=1).fit(embedding[keep]).kneighbors(embedding[~keep])[0].ravel()
            group_q.append(float(np.quantile(d,.95)))
        threshold=float(np.quantile(group_q,.95))
        distance=NearestNeighbors(n_neighbors=1).fit(embedding).kneighbors(target_embedding)[0].ravel()
        mask=distance>threshold;guarded_prediction=np.where(mask,baseline_pred,prediction)
        guard={'threshold':threshold,'train_embedding':embedding,'training_mean':float(np.mean(y[train])),
               'method':'95th percentile of per-training-cell 95th percentile nearest-other-cell distances'}
    model_path=out/'trained_model.joblib';joblib.dump({'model':model,'features':features,'categories':categories,'metadata':metadata,
        'training_ranges':ranges,'training_levels':levels,'training_groups':sorted(set(train_groups)),'domain_guard':guard},model_path)
    with (out/'holdout.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['record_id','group_id','observed','predicted','baseline_mean','guarded_prediction','joint_distance'])
        writer.writerows(zip(frame.iloc[test]['record_id'],groups[test],y[test],prediction,baseline_pred,guarded_prediction,
                             distance if distance is not None else ['']*len(test)))
    output={'selected_model':chosen,'training_cv':comparisons,'holdout':metric(y[test],prediction,groups[test]),
            'holdout_mean_baseline':metric(y[test],baseline_pred,groups[test]),'train_groups':len(set(train_groups)),
            'holdout_groups':len(set(groups[test])),'train_rows':len(train),'holdout_rows':len(test),
            'split_seed':seed if holdout_groups is None else None,'model_sha256':hashlib.sha256(model_path.read_bytes()).hexdigest(),
            'holdout_group_ids':sorted(set(groups[test])),'features':features,'selection_policy':selection_policy}
    if guard is not None:
        output.update({'domain_guard_threshold':guard['threshold'],'holdout_ood_count':int(np.sum(distance>guard['threshold'])),
                       'holdout_guarded':metric(y[test],guarded_prediction,groups[test]),
                       'guard_scope':'联合特征距离超出训练电芯间距离阈值时，保守回退训练均值；非置信保证。'})
    return output


def hardcarbon_train(raw,config,out):
    rows,excluded=prepare_hardcarbon(raw)
    fields=['carbonization_temperature_C','d002_nm','id_ig','ssa_m2_g','electrolyte_type','current_density_mA_g']
    frame=pd.DataFrame(rows).rename(columns={'ice':'target'})
    output=grouped_fit(frame,fields,['electrolyte_type'],out,{'kind':'hardcarbon'},config.get('split_seed',42),config.get('algorithms'))
    buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fieldnames=['record_id','group_id','batch_id']+fields+['ice']);writer.writeheader();writer.writerows(rows)
    (Path(out)/'prepared.csv').write_text(buffer.getvalue(),encoding='utf-8-sig')
    output.update({'source_records':len(rows)+len(excluded),'excluded':excluded,'eligible_records':len(rows),
        'scope':'按来源字符串分组，固定留出文献组，训练组内交叉验证选择模型。文献标题只是来源代理，不能保证标题变体或材料家族完全隔离；不能用于DFN参数映射。'})
    return output


def hardcarbon_predict(raw,config,out,model_path,expected_hash):
    model_path=Path(model_path)
    if hashlib.sha256(model_path.read_bytes()).hexdigest()!=expected_hash:raise ValueError('模型文件校验失败。')
    saved=joblib.load(model_path)
    if saved['metadata']['kind']!='hardcarbon':raise ValueError('模型类型不符。')
    features=saved['features'];rows=table(raw,['record_id']+features)
    ids=[row['record_id'].strip() for row in rows]
    if any(not v for v in ids) or len(ids)!=len(set(ids)):raise ValueError('record_id必须非空且唯一。')
    frame=pd.DataFrame(rows)
    for key in features:
        if key in saved['categories']:
            if any(not str(v).strip() for v in frame[key]):raise ValueError('类别描述符不能为空：'+key)
            frame[key]=frame[key].astype(str)
        else:frame[key]=[value(v,key) for v in frame[key]]
    predictions=saved['model'].predict(frame[features]);output=[]
    for ident,row,p in zip(ids,frame.to_dict('records'),predictions):
        alerts=[k+'超出训练范围' for k,(lo,hi) in saved.get('training_ranges',{}).items() if not lo<=row[k]<=hi]
        alerts += [k+'为未见类别' for k,levels in saved.get('training_levels',{}).items() if row[k] not in levels]
        output.append({'record_id':ident,'predicted_ice':float(p),'outside_physical_range':not 0<=p<=1,'alerts':alerts})
    return {'predictions':output,'scope':'仅适用于已制得硬碳、所需表征和测试条件已知的样品。预测不是独立验证或DFN参数，超出训练范围的结果仅供探索。'}


def charge_features(raw,config,require_target):
    required=['cell_id','segment_id','time_s','current_A','voltage_V']+(['soh'] if require_target else [])
    feature_mode=config.get('feature_mode','raw')
    if feature_mode not in ('raw','reference_normalized'):raise ValueError('未知部分充电特征模式。')
    if feature_mode=='reference_normalized':required.append('reference_capacity_Ah')
    rows=table(raw,required,max_rows=150000)
    lower=value(config.get('voltage_lower_V'),'voltage_lower_V');upper=value(config.get('voltage_upper_V'),'voltage_upper_V')
    if lower>=upper:raise ValueError('电压区间上下限无效。')
    sign=config.get('charge_sign');factor=1 if sign=='positive' else -1 if sign=='negative' else 0
    if not factor:raise ValueError('请声明充电电流符号。')
    grouped={}
    for row in rows:
        cell=row['cell_id'].strip();segment=row['segment_id'].strip()
        if not cell or not segment:raise ValueError('cell_id和segment_id不能为空。')
        grouped.setdefault((cell,segment),[]).append(row)
    output=[];excluded=[];cell_references={}
    for (cell,segment),part in grouped.items():
        t=np.array([value(r['time_s'],'time_s') for r in part]);v=np.array([value(r['voltage_V'],'voltage_V') for r in part]);i=np.array([value(r['current_A'],'current_A')*factor for r in part])
        if len(t)<8 or np.any(np.diff(t)<=0) or np.any(i<0):
            excluded.append({'cell_id':cell,'segment_id':segment,'reason':'点数不足、时间不递增或存在反向电流'});continue
        # First upward crossings only; never use points after the window end.
        crossings=[]
        for threshold in np.linspace(lower,upper,9):
            matches=np.flatnonzero((v[:-1]<threshold)&(v[1:]>=threshold))
            if len(matches)==0:crossings=[];break
            k=int(matches[0]);alpha=(threshold-v[k])/(v[k+1]-v[k]);crossings.append((t[k]+alpha*(t[k+1]-t[k]),i[k]+alpha*(i[k+1]-i[k])))
        if not crossings or any(crossings[j][0]<=crossings[j-1][0] for j in range(1,9)):
            excluded.append({'cell_id':cell,'segment_id':segment,'reason':'未完整覆盖固定电压区间或首次穿越顺序异常'});continue
        times=np.array([p[0] for p in crossings]);currents=np.array([p[1] for p in crossings]);elapsed=times-times[0]
        item={'record_id':cell+'::'+segment,'group_id':cell,'duration_s':float(elapsed[-1]),
              'charge_window_Ah':float(np.trapezoid(currents,times)/3600),'mean_current_A':float(np.mean(currents))}
        item.update({f'time_fraction_{j}':float(elapsed[j]) for j in range(1,8)})
        if feature_mode=='reference_normalized':
            refs={value(r['reference_capacity_Ah'],'reference_capacity_Ah') for r in part}
            if len(refs)!=1 or next(iter(refs))<=0:raise ValueError('同一片段参考容量必须一致且大于零。')
            ref=next(iter(refs))
            if cell in cell_references and cell_references[cell]!=ref:raise ValueError('同一电芯的参考容量必须一致。')
            cell_references[cell]=ref;rate=item['mean_current_A']/ref
            item.update({'window_capacity_fraction':item['charge_window_Ah']/ref,'mean_charge_rate_C':rate})
            item.update({f'charge_fraction_{j}':float(elapsed[j]*rate/3600) for j in range(1,8)})
        if require_target:
            targets={value(r['soh'],'soh') for r in part}
            if len(targets)!=1 or not 0<next(iter(targets))<=1.2:raise ValueError('每段SOH需一致且在0–1.2。')
            item['target']=next(iter(targets))
        output.append(item)
    return pd.DataFrame(output),excluded


SOH_FEATURES=['duration_s','charge_window_Ah','mean_current_A']+[f'time_fraction_{j}' for j in range(1,8)]
SOH_NORMALIZED_FEATURES=['window_capacity_fraction','mean_charge_rate_C']+[f'charge_fraction_{j}' for j in range(1,8)]


def soh_train(raw,config,out):
    frame,excluded=charge_features(raw,config,True)
    if len(frame)<12:raise ValueError('至少需要12个符合窗口的已标注充电片段。')
    mode=config.get('feature_mode','raw');features=SOH_NORMALIZED_FEATURES if mode=='reference_normalized' else SOH_FEATURES
    result=grouped_fit(frame,features,[],out,{'kind':'partial_charge_soh','voltage_lower_V':config['voltage_lower_V'],
        'voltage_upper_V':config['voltage_upper_V'],'charge_sign':config['charge_sign'],'feature_mode':mode},config.get('split_seed',42),config.get('algorithms'),
        selection_policy=config.get('selection_policy','mean_group'))
    result.update({'eligible_segments':len(frame),'excluded':excluded[:100],'excluded_count':len(excluded),
        'validation_warning':'留出电芯少于5只，结论仅供探索；须增加电芯、工况及跨数据集验证。' if result['holdout_groups']<5 else '留出误差只适用于所测电芯和工况。',
        'scope':'固定电压区间的充电时间、电流和电量特征；按电芯留出、训练电芯分组CV选模型。标签来自用户独立容量测试；测试电芯结果不代表新化学体系通用。'})
    return result


def soh_predict(raw,config,out,model_path,expected_hash):
    model_path=Path(model_path)
    if hashlib.sha256(model_path.read_bytes()).hexdigest()!=expected_hash:raise ValueError('模型文件校验失败。')
    saved=joblib.load(model_path)
    meta=saved['metadata']
    if meta['kind']!='partial_charge_soh':raise ValueError('模型类型不符。')
    cfg={k:meta[k] for k in ['voltage_lower_V','voltage_upper_V','charge_sign']}
    cfg['feature_mode']=meta.get('feature_mode','raw')
    frame,excluded=charge_features(raw,cfg,False)
    if frame.empty:raise ValueError('没有满足训练电压窗口的充电片段。')
    predicted=saved['model'].predict(frame[saved['features']])
    guard=saved.get('domain_guard');distance=None
    gp_std=None
    if 'gaussianprocessregressor' in saved['model'].named_steps:
        transformed=saved['model'].named_steps['columntransformer'].transform(frame[saved['features']])
        _,gp_std=saved['model'].named_steps['gaussianprocessregressor'].predict(transformed,return_std=True)
    if guard is not None:
        embedded=saved['model'].named_steps['columntransformer'].transform(frame[saved['features']])
        if hasattr(embedded,'toarray'):embedded=embedded.toarray()
        distance=NearestNeighbors(n_neighbors=1).fit(guard['train_embedding']).kneighbors(embedded)[0].ravel()
    result=[]
    for j,(row,p) in enumerate(zip(frame.to_dict('records'),predicted)):
        alerts=[k for k,(lo,hi) in saved.get('training_ranges',{}).items() if not lo<=row[k]<=hi]
        outside=bool(distance[j]>guard['threshold']) if guard is not None else None
        result.append({'record_id':row['record_id'],'predicted_soh':float(p),'outside_physical_range':not 0<=p<=1.2,
                       'outside_training_features':alerts,'seen_training_cell':row['group_id'] in saved.get('training_groups',[]),
                       'joint_domain_distance':float(distance[j]) if distance is not None else None,'joint_outside_domain':outside,
                       'guarded_estimate_soh':float(guard['training_mean'] if outside else p),
                       'gp_latent_std':float(gp_std[j]) if gp_std is not None else None,
                       'guarded_estimate_basis':'训练集均值回退' if outside else '模型预测'})
    return {'predictions':result,'excluded':excluded[:100],'excluded_count':len(excluded),
            'scope':'冻结模型仅接受训练时的充电电压窗口和电流符号；联合偏移触发时显示训练均值回退并保留原模型值。回退不是已验证准确值，不自动截断，不构成电芯安全认证。'}
