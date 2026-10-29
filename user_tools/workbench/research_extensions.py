"""Optional research tools. These are offline analyses, never device controls."""
from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from user_tools.workbench.multichem_analysis import prepare_hardcarbon


def hardcarbon_shap(raw, config):
    import shap

    model_path = Path(config['_model_path'])
    source_path = Path(config['_training_source_path'])
    if hashlib.sha256(model_path.read_bytes()).hexdigest() != config['_model_sha256']:
        raise ValueError('模型文件校验失败。')
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != config['_training_source_sha256']:
        raise ValueError('训练源文件校验失败。')
    saved = joblib.load(model_path)
    if saved['metadata']['kind'] != 'hardcarbon':
        raise ValueError('需要硬碳模型。')
    rows, _ = prepare_hardcarbon(source_path.read_bytes())
    train = pd.DataFrame([r for r in rows if r['group_id'] in saved['training_groups']])
    target = pd.read_csv(io.BytesIO(raw)).head(20)
    features = saved['features']
    if len(target) == 0 or not set(features).issubset(target.columns):
        raise ValueError('解释文件必须包含模型的六个描述符。')
    for key in features:
        if key in saved['categories']:
            for df in (train, target):
                df[key] = df[key].fillna('missing').astype(str)
        else:
            for df in (train, target):
                df[key] = pd.to_numeric(df[key], errors='coerce')
    transformer = saved['model'].named_steps['columntransformer']
    estimator = saved['model'].steps[-1][1]
    background = transformer.transform(train[features].sample(min(50, len(train)), random_state=42))
    subjects = transformer.transform(target[features])
    if hasattr(background, 'toarray'):
        background = background.toarray()
    if hasattr(subjects, 'toarray'):
        subjects = subjects.toarray()
    names = list(transformer.get_feature_names_out())
    # A fixed training-only background makes the explanation reproducible.
    explainer = shap.Explainer(estimator.predict, background, algorithm='permutation', seed=42)
    values = np.asarray(explainer(subjects, max_evals=2 * len(names) + 1).values)
    importance = [{'transformed_feature': name, 'mean_abs_shap': float(v)}
                  for name, v in sorted(zip(names, np.mean(np.abs(values), axis=0)), key=lambda a: -a[1])]
    return {'backend': 'SHAP permutation', 'sample_count': len(target), 'background_count': len(background),
            'importance': importance,
            'scope': '仅解释模型输出；背景来自训练文献，类别会展开为多个特征。相关特征的归因不代表因果关系。最多解释上传文件前20行。'}


def uncertainty_audit(raw, config):
    from scipy.optimize import minimize
    from sklearn.metrics.pairwise import rbf_kernel
    from sklearn.preprocessing import StandardScaler
    from user_tools.workbench.vendor.rsa_cp.core import get_rsacp_quantile, standard_conformal_quantile

    df = pd.read_csv(io.BytesIO(raw))
    needed = {'role', 'group_id', 'predicted', 'observed'}
    if not needed.issubset(df.columns):
        raise ValueError('需要role、group_id、predicted、observed列。')
    if not set(df.role).issubset({'reference', 'calibration', 'test'}):
        raise ValueError('role仅可为reference、calibration、test。')
    if df.group_id.isna().any() or (df.group_id.astype(str).str.strip() == '').any():
        raise ValueError('每行必须有独立分组ID。')
    groups = [set(df.loc[df.role == r, 'group_id']) for r in ('reference', 'calibration', 'test')]
    if any(groups[i] & groups[j] for i in range(3) for j in range(i)):
        raise ValueError('参考、校准和测试数据必须按文献或电芯分组隔离。')
    ref, cal, test = [df[df.role == r].copy() for r in ('reference', 'calibration', 'test')]
    if min(len(ref), len(cal), len(test)) < 2 or len(cal) > 1000 or len(test)>2000:
        raise ValueError('各部分至少2行，校准集最多1000行，测试集最多2000行。')
    for d in (ref, cal, test):
        d['predicted'] = pd.to_numeric(d.predicted, errors='raise')
        d['observed'] = pd.to_numeric(d.observed, errors='coerce')
        if not np.isfinite(d.predicted).all():
            raise ValueError('预测值必须有限。')
    if not np.isfinite(ref.observed).all() or not np.isfinite(cal.observed).all():
        raise ValueError('参考和校准数据必须有实测值。')
    alpha = float(config.get('alpha', .1)); beta = float(config.get('beta', .05))
    if not 0 < alpha < 1 or not 0 < beta < 1:
        raise ValueError('alpha和beta必须介于0和1之间。')
    ref_scores = np.abs(ref.observed.to_numpy() - ref.predicted.to_numpy())
    scores = np.abs(cal.observed.to_numpy() - cal.predicted.to_numpy())
    split_q = standard_conformal_quantile(scores, alpha)
    rsa_q = get_rsacp_quantile(scores, ref_scores, alpha, beta)
    cols = config.get('feature_columns', [])
    if not isinstance(cols, list) or not cols or len(cols) > 30 or not set(cols).issubset(df.columns) or set(cols)&{'observed','role','group_id'}:
        raise ValueError('feature_columns须指定1–30个数值描述符列。')
    xc = cal[cols].apply(pd.to_numeric, errors='coerce').to_numpy()
    xt = test[cols].apply(pd.to_numeric, errors='coerce').to_numpy()
    if not np.isfinite(xc).all() or not np.isfinite(xt).all():
        raise ValueError('KMM描述符不可缺失且须有限。')
    scale = StandardScaler().fit(xc); xc = scale.transform(xc); xt = scale.transform(xt)
    gamma = 1.0 / max(1, len(cols))
    kernel = rbf_kernel(xc, gamma=gamma)
    kappa = len(xc) * rbf_kernel(xc, xt, gamma=gamma).mean(axis=1)
    bound = float(config.get('weight_bound', 10))
    if not 1 <= bound <= 100:
        raise ValueError('weight_bound须为1–100。')
    # Standard bounded KMM with normalized weights; no target labels enter this fit.
    fit = minimize(lambda w: .5 * w @ kernel @ w - kappa @ w,
                   np.ones(len(xc)), jac=lambda w: kernel @ w - kappa,
                   bounds=[(0, bound)] * len(xc), constraints={'type':'eq','fun':lambda w: w.sum()-len(xc), 'jac':lambda w: np.ones(len(xc))},
                   method='SLSQP', options={'maxiter':500, 'ftol':1e-8})
    if not fit.success:
        raise ValueError('KMM求解未收敛：' + fit.message)
    order = np.argsort(scores); weights = np.maximum(fit.x, 0); cumulative = np.cumsum(weights[order]) / weights.sum()
    kmm_q = float(scores[order[min(np.searchsorted(cumulative, 1-alpha), len(order)-1)]])
    def evaluate(q):
        if not math.isfinite(q):
            return {'half_width':None, 'coverage':None, 'mean_width':None, 'finite':False}
        mask = np.isfinite(test.observed.to_numpy())
        cov = float(np.mean(np.abs(test.observed.to_numpy()[mask]-test.predicted.to_numpy()[mask]) <= q)) if mask.any() else None
        return {'half_width':float(q), 'coverage':cov, 'mean_width':float(2*q), 'finite':True}
    def interval(q,p):
        return {'lower':float(p-q),'upper':float(p+q)} if math.isfinite(q) else {'lower':None,'upper':None}
    predictions=[{'group_id':str(row.group_id),'predicted':float(row.predicted),
                  'split_cp':interval(split_q,row.predicted),'rsa_cp':interval(rsa_q,row.predicted),
                  'kmm_cp':interval(kmm_q,row.predicted)} for row in test.itertuples()]
    return {'methods':{'split_cp':evaluate(split_q),'rsa_cp':evaluate(rsa_q),'kmm_cp':evaluate(kmm_q)},
            'predictions':predictions,
            'counts':{'reference':len(ref),'calibration':len(cal),'test':len(test)},
            'kmm_effective_sample_size':float(weights.sum()**2 / np.sum(weights**2)),
            'scope':'RSA-CP调用作者代码；KMM-CP按论文的非选择性KMM校准扩展到回归，使用未标注测试特征；未实现选择性KMM。测试标签只用于事后覆盖率。组内相关性和分布偏移使理论覆盖保证不一定成立；需确保预测来自与参考、校准及测试组独立的冻结模型。'}


def ax_recommend(raw, config):
    from ax.service.ax_client import AxClient, ObjectiveProperties
    from ax.generation_strategy.generation_strategy import GenerationStrategy, GenerationStep
    from ax.adapter.registry import Generators

    df = pd.read_csv(io.BytesIO(raw))
    parameters = config.get('parameters', [])
    metrics = config.get('objectives', [])
    if not 1 <= len(parameters) <= 10 or not 1 <= len(metrics) <= 2 or len(df) > 100:
        raise ValueError('需要1–10个连续参数、1–2个目标和最多100行已完成实验。')
    names = [p['name'] for p in parameters]; objectives = [m['name'] for m in metrics]
    if len(set(names + objectives)) != len(names + objectives) or not set(names + objectives).issubset(df.columns):
        raise ValueError('参数和目标必须为CSV中不同的列。')
    space=[]
    for p in parameters:
        lo,hi = map(float,p['bounds'])
        if not math.isfinite(lo) or not math.isfinite(hi) or lo >= hi:
            raise ValueError('参数边界无效。')
        space.append({'name':p['name'],'type':'range','bounds':[lo,hi],'value_type':'float'})
    values=df[names+objectives].apply(pd.to_numeric,errors='raise')
    if len(values)<2 or not np.isfinite(values.to_numpy()).all():
        raise ValueError('至少两行有限的实测实验数据。')
    for p in space:
        if not values[p['name']].between(*p['bounds']).all():
            raise ValueError('已完成实验超出参数边界。')
    # Imported observations do not advance Ax's Sobol generation counter.
    # When enough completed experiments exist, explicitly start with BoTorch.
    strategy = GenerationStrategy(nodes=[GenerationStep(generator=Generators.BOTORCH_MODULAR, num_trials=-1)]) if len(values)>=5 else None
    ax=AxClient(random_seed=42,verbose_logging=False,generation_strategy=strategy)
    ax.create_experiment(parameters=space, objectives={m['name']:ObjectiveProperties(minimize=bool(m.get('minimize',False)), threshold=m.get('threshold')) for m in metrics})
    for _,row in values.iterrows():
        _, trial = ax.attach_trial(parameters={n:float(row[n]) for n in names})
        ax.complete_trial(trial_index=trial, raw_data={n:float(row[n]) for n in objectives})
    parameters_next, trial = ax.get_next_trial()
    return {'backend':'Ax','candidate':parameters_next,'trial_index':trial,'completed_rows':len(values),
            'generator':'BoTorch' if strategy else 'Sobol',
            'scope':'Ax基于已完成实验生成候选；少于5行使用Sobol冷启动。候选未经实验验证，不发送到仪器。'}


def helao_plan(raw, config):
    import sys
    source = Path('/home/zjh/.local/share/fangzhen/sources/helao-async')
    if not (source/'helao/core/models/sequence.py').is_file():
        raise ValueError('未找到已安装的HELAO源码模型。')
    sys.path.insert(0, str(source))
    from helao.core.models.sequence import ShortSequenceModel
    df = pd.read_csv(io.BytesIO(raw))
    if not 1 <= len(df) <= 100 or 'experiment_name' not in df:
        raise ValueError('需要1–100行，每行包含experiment_name。')
    experiments=[]
    for row in df.to_dict('records'):
        name=str(row.pop('experiment_name')).strip()
        if not name or name.lower()=='nan':
            raise ValueError('实验名称不能为空。')
        params={k:v for k,v in row.items() if pd.notna(v)}
        experiments.append({'experiment_name':name,'experiment_params':params})
    sequence=ShortSequenceModel(sequence_name=str(config.get('sequence_name','battery_plan')),
                                sequence_comment='Offline planning only; no dispatch.',planned_experiments=experiments)
    return {'backend':'HELAO ShortSequenceModel','sequence':sequence.model_dump(mode='json'),
            'scope':'仅生成并验证HELAO序列模型，未校验实验函数名或设备配置，未连接或调度仪器；需要在目标HELAO系统配置和审核后使用。'}
