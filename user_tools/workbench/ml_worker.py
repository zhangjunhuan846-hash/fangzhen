"""Grouped descriptor regression. All fitted preprocessing stays inside each fold."""
import csv
import hashlib
import json
from pathlib import Path
import warnings
import sys
import sklearn
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.cross_decomposition import PLSRegression
from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold, LeaveOneGroupOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
import joblib
from user_tools.workbench.ml_data import validate_selection, number

MODELS = ['mean', 'ridge', 'pls', 'random_forest', 'extra_trees', 'gp']

def frame(rows, fields):
    return pd.DataFrame({f['key']: [number(r.get(f['key'])) if f['kind'] == 'numeric' else str(r.get(f['key']) or '__missing__') for r in rows] for f in fields})

def select_columns(x, y, fields, config):
    usable = [f['key'] for f in fields if x[f['key']].nunique(dropna=True) > 1]
    if not usable:
        raise ValueError('训练折中所有描述符都缺失或为常数。')
    if config.get('selector', 'manual') == 'manual':
        return usable
    if config['selector'] not in ['spearman', 'mrmr']:
        raise ValueError('未知描述符筛选方法。')
    relevance = {}
    numeric = {f['key'] for f in fields if f['kind'] == 'numeric'}
    filled = x.copy()
    for key in usable:
        if key in numeric:
            filled[key] = filled[key].fillna(filled[key].median())
            value = spearmanr(filled[key], y).statistic
            relevance[key] = abs(float(value)) if np.isfinite(value) else 0.
        else:
            # Correlation ratio for categories; no artificial ordinal encoding.
            total = np.sum((y - y.mean()) ** 2)
            relevance[key] = float(np.sqrt(sum(np.sum(filled[key] == c) * (np.mean(y[filled[key] == c]) - y.mean()) ** 2 for c in filled[key].unique()) / total)) if total > 0 else 0.
    count = int(config.get('top_k', 5))
    if not 1 <= count <= 30:
        raise ValueError('筛选数量需1–30。')
    picked = []
    while len(picked) < min(count, len(usable)):
        scores = {}
        for key in usable:
            if key in picked:
                continue
            redundancy = []
            if config['selector'] == 'mrmr' and key in numeric:
                for other in picked:
                    if other in numeric:
                        v = spearmanr(filled[key], filled[other]).statistic
                        redundancy.append(abs(float(v)) if np.isfinite(v) else 0.)
            scores[key] = relevance[key] - (np.mean(redundancy) if redundancy else 0.)
        picked.append(sorted(scores, key=lambda k: (-scores[k], k))[0])
    return picked

def fit_bundle(rows, fields, config, model):
    y = np.array([float(r['target']) for r in rows]); x = frame(rows, fields)
    if model == 'mean':
        return {'name': model, 'mean': float(y.mean()), 'selected': [], 'fields': fields}
    chosen = select_columns(x, y, fields, config)
    numeric = [f['key'] for f in fields if f['key'] in chosen and f['kind'] == 'numeric']
    categorical = [k for k in chosen if k not in numeric]
    if any(x[k].nunique() > 30 for k in categorical):
        raise ValueError('类别描述符超过30种，可能误选编号或未清洗数值列。')
    transforms = []
    if numeric:
        transforms.append(('numeric', Pipeline([('imputer', SimpleImputer(strategy='median')), ('scale', StandardScaler())]), numeric))
    if categorical:
        transforms.append(('categorical', OneHotEncoder(handle_unknown='ignore', sparse_output=False), categorical))
    prep = ColumnTransformer(transforms)
    a = prep.fit_transform(x); center = float(y.mean()); scale = max(float(y.std()), 1e-12); z = (y - center) / scale
    if model == 'ridge':
        estimator = Ridge(alpha=1.)
    elif model == 'pls':
        estimator = PLSRegression(n_components=max(1, min(2, a.shape[1], len(y) - 1)), scale=False)
    elif model in ['random_forest', 'extra_trees']:
        cls = RandomForestRegressor if model == 'random_forest' else ExtraTreesRegressor
        estimator = cls(n_estimators=100, max_depth=4, min_samples_leaf=2, n_jobs=1, random_state=42)
    elif model == 'gp':
        noise = float(config.get('noise_fraction', .05))
        if not .001 <= noise <= 1:
            raise ValueError('GP相对噪声标准差需0.001–1。')
        estimator = GaussianProcessRegressor(kernel=ConstantKernel(1., 'fixed') * Matern(np.ones(a.shape[1]), 'fixed', nu=2.5),
                                              alpha=noise ** 2, optimizer=None, normalize_y=False)
    else:
        raise ValueError('未知回归模型。')
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always'); estimator.fit(a, z)
    return {'name': model, 'prep': prep, 'estimator': estimator, 'center': center, 'scale': scale,
            'selected': chosen, 'fields': fields, 'warnings': list(dict.fromkeys(str(w.message) for w in caught))[:5],
            'training_numeric_bounds': {f['key']: [float(x[f['key']].min()), float(x[f['key']].max())]
                                        for f in fields if f['kind']=='numeric' and x[f['key']].notna().any()},
            'training_categories': {f['key']: list(x[f['key']].unique()) for f in fields if f['kind']=='categorical'}}

def predict_bundle(bundle, rows, std=False):
    if bundle['name'] == 'mean':
        return np.full(len(rows), bundle['mean']), None
    x = bundle['prep'].transform(frame(rows, bundle['fields']))
    if std and bundle['name'] == 'gp':
        mu, sigma = bundle['estimator'].predict(x, return_std=True)
        return mu.ravel() * bundle['scale'] + bundle['center'], sigma * bundle['scale']
    return np.asarray(bundle['estimator'].predict(x)).ravel() * bundle['scale'] + bundle['center'], None

def group_metrics(rows):
    groups = {}
    for row in rows:
        groups.setdefault(row['group_id'], []).append(row)
    # Equal group weight, but loss is computed per record BEFORE averaging.
    errors=[np.array([r['predicted']-r['observed'] for r in rs]) for rs in groups.values()]
    center=float(np.mean([np.mean([r['observed'] for r in rs]) for rs in groups.values()]))
    mse=float(np.mean([np.mean(e**2) for e in errors]))
    total=float(np.mean([np.mean([(r['observed']-center)**2 for r in rs]) for rs in groups.values()]))
    return {'mae':float(np.mean([np.mean(np.abs(e)) for e in errors])), 'rmse':float(np.sqrt(mse)),
            'bias':float(np.mean([np.mean(e) for e in errors])), 'r2':float(1-mse/total) if total>0 else None,'groups':len(groups)}

def train(dataset, config, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    original_dataset=dataset
    calibration_rows=[];calibration_plan=None
    if config.get('auto_calibrate'):
        from user_tools.workbench.ml_calibration import split_groups
        development,calibration_rows,calibration_plan=split_groups(dataset['rows'],config.get('alpha',.1))
        dataset={**dataset,'rows':development}
    chosen = validate_selection(dataset, config); rows = dataset['rows']
    if not 5 <= len(rows) <= 1000:
        raise ValueError('需要5–1000个有目标的样品；未测目标不能训练。')
    fields = [f for f in dataset['fields'] if f['key'] in chosen]
    group_batch = {}
    for r in rows:
        if r['group_id'] in group_batch and group_batch[r['group_id']] != r['batch_id']:
            raise ValueError('同一group_id跨原料批次，请核对分组。')
        group_batch[r['group_id']] = r['batch_id']
    if len(group_batch) < 5:
        raise ValueError('至少需要5个独立工艺组；重复电芯不能补足独立样本数。')
    split = config.get('validation', 'group')
    if split not in ['group', 'batch']:
        raise ValueError('未知验证划分。')
    grouping = [r['batch_id'] if split == 'batch' else r['group_id'] for r in rows]
    if split == 'batch' and len(set(grouping)) < 2:
        raise ValueError('留批次验证至少需要两个原料批次。')
    splitter = LeaveOneGroupOut() if split == 'batch' else GroupKFold(n_splits=min(5, len(set(grouping))))
    folds = list(splitter.split(rows, groups=grouping))
    if any(len(train_ids) < 3 for train_ids, _ in folds):
        raise ValueError('划分后训练样本不足3个。')
    comparisons, oof, importance = [], [], []
    for model in MODELS:
        predictions, failures, picks = [], [], {}
        for fold, (train_ids, test_ids) in enumerate(folds):
            training = [rows[i] for i in train_ids]; testing = [rows[i] for i in test_ids]
            if {r['group_id'] for r in training} & {r['group_id'] for r in testing}:
                raise ValueError('训练和留出工艺组重叠。')
            try:
                bundle = fit_bundle(training, fields, config, model)
                mu, _ = predict_bundle(bundle, testing)
                if not np.isfinite(mu).all():
                    raise ValueError('模型输出非有限预测。')
                for key in bundle['selected']:
                    picks[key] = picks.get(key, 0) + 1
                foldrows = [{'model': model, 'fold': fold, 'record_id': r['record_id'], 'group_id': r['group_id'],
                             'batch_id': r['batch_id'], 'observed': float(r['target']), 'predicted': float(p)} for r, p in zip(testing, mu)]
                predictions += foldrows
                if model != 'mean':
                    baseline = group_metrics(foldrows)['mae']
                    # Holdout permutation is diagnostic only; never used to select columns.
                    for key in bundle['selected']:
                        losses = []
                        for seed in range(3):
                            shuffled = [dict(r) for r in testing]
                            vals = np.random.default_rng(seed + fold * 23).permutation([r.get(key) for r in testing])
                            for r, value in zip(shuffled, vals):
                                r[key] = value
                            shuffled_mu, _ = predict_bundle(bundle, shuffled)
                            permuted = [{**r, 'predicted': float(p)} for r, p in zip(foldrows, shuffled_mu)]
                            losses.append(group_metrics(permuted)['mae'] - baseline)
                        importance.append({'model': model, 'fold': fold, 'feature': key, 'mae_increase': float(np.mean(losses)),
                                           'informative': len(testing) >= 3})
            except Exception as error:
                failures.append({'fold': fold, 'reason': str(error)})
        complete = len(predictions) == len(rows) and not failures
        comparisons.append({'model': model, 'status': 'complete' if complete else 'failed',
                            'metrics': group_metrics(predictions) if complete else None, 'failures': failures,
                            'selection_frequency': {k: n / len(folds) for k, n in picks.items()}})
        oof += predictions
    eligible = [c for c in comparisons if c['status'] == 'complete' and c['model'] != 'mean']
    if not eligible:
        raise ValueError('所有描述符模型失败，请核对运行日志和数据。')
    selected = min(eligible, key=lambda c: (c['metrics']['mae'], c['model']))['model']
    final = fit_bundle(rows, fields, config, selected)
    gp = final if selected == 'gp' else fit_bundle(rows, fields, config, 'gp')
    baseline = next(c for c in comparisons if c['model'] == 'mean')['metrics']['mae']
    gp_comparison = next(c for c in comparisons if c['model'] == 'gp')
    gp_ready = gp_comparison['status'] == 'complete' and gp_comparison['metrics']['mae'] < baseline
    interval=calibration_plan
    if calibration_rows:
        from user_tools.workbench.ml_calibration import calibrate
        cmu,_=predict_bundle(final,calibration_rows)
        interval={**calibration_plan,**calibrate(calibration_rows,cmu,config.get('alpha',.1))}
    if interval and any(r.get('_sampling')=='adaptive_feedback' for r in original_dataset['rows']):
        interval['coverage_warning']='含自适应反馈，残差带不继承名义覆盖保证'
    saved = {'model': final, 'gp': gp, 'dataset': dataset, 'config': config, 'selected': selected,
             'calibration':interval,
             'metric_definition':'equal_group_mean_of_per_record_losses_v2',
             'gp_improves_mean': gp_ready}
    joblib.dump(saved, out / 'model.joblib')
    write_csv(out / 'oof.csv', oof)
    write_csv(out / 'importance.csv', importance)
    audit = [{'feature': f['key'], 'label': f['label'], 'kind': f['kind'], 'stage': f['stage'],
              'missing': sum(r.get(f['key']) in (None, '') for r in rows),
              'distinct': len({str(r.get(f['key'])) for r in rows if r.get(f['key']) not in (None, '')})} for f in fields]
    result = {'evidence_type': 'user_descriptor_model_exploration', 'selected_model': selected, 'comparisons': comparisons,
              'samples': len(rows), 'independent_groups': len(group_batch), 'batches': len(set(r['batch_id'] for r in rows)),
              'validation': split, 'folds': len(folds), 'features': chosen, 'target': dataset['target'], 'audit': audit,
              'oof': [r for r in oof if r['model'] == selected], 'importance': importance,
              'exclusions': dataset.get('exclusions', []), 'final_selected_features': final['selected'],
              'source_sha256': hashlib.sha256(json.dumps(original_dataset, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
              'training_source_sha256': hashlib.sha256(json.dumps(dataset, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
              'calibration_source_sha256':hashlib.sha256(json.dumps(calibration_rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
              'model_sha256': hashlib.sha256((out/'model.joblib').read_bytes()).hexdigest(),
              'runtime_versions': {'python':sys.version.split()[0],'numpy':np.__version__,'pandas':pd.__version__,
                                   'sklearn':sklearn.__version__,'joblib':joblib.__version__},
              'selector': config.get('selector', 'manual'), 'group_basis': dataset['group_basis'],
              'metric_definition':'equal_group_mean_of_per_record_losses_v2',
              'calibration':interval,
              'gp_recommendation_gate': 'cv_better_than_mean_exploratory' if gp_ready else 'blocked_not_better_than_mean',
              'selector_definition': 'Spearman/类别相关比；冗余控制采用数值列Spearman相关惩罚，不是原版互信息mRMR',
              'scope': '按独立工艺组/留批次验证；预处理与固定数量特征筛选仅在训练折拟合。模型按同一CV结果选择，优胜模型仍需独立实验确认；置换重要性非因果，单组留出时不可靠。GP固定核尺度与声明噪声，非TabPFN/FABO原版复现。'}
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    (out / 'ui_result.json').write_text(json.dumps({'result': result, 'curves': []}, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    return result

def write_csv(path, rows):
    if rows:
        with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)

def infer(config, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    # Only paths created by the local server from a completed same-workspace job.
    model_file=Path(config['model_path'])
    if config.get('expected_model_sha256') and hashlib.sha256(model_file.read_bytes()).hexdigest()!=config['expected_model_sha256']:
        raise ValueError('保存模型校验值不一致，请重新建模。')
    saved = joblib.load(model_file)
    rows = config['prediction_rows']; fields = saved['model']['fields']
    if not 1 <= len(rows) <= 200:
        raise ValueError('预测表需1–200行。')
    for row in rows:
        row['record_id']=str(row.get('record_id') or '').strip()
        row['batch_id']=str(row.get('batch_id') or '').strip()
    ids = [r['record_id'] for r in rows]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('预测record_id缺失或重复。')
    target = saved['dataset']['target']
    if any(r.get(target) not in (None, '') or r.get('target') not in (None, '') for r in rows):
        raise ValueError('未测候选不能带目标标签。')
    for field in fields:
        if any(field['key'] not in r for r in rows):
            raise ValueError('预测CSV缺少描述符：' + field['key'])
        if field['kind'] == 'numeric' and any(r.get(field['key']) not in (None, '') and number(r[field['key']]) is None for r in rows):
            raise ValueError('预测数值无效：' + field['key'])
    recommend = config.get('mode') == 'ml_recommend'
    if recommend and saved.get('metric_definition')!='equal_group_mean_of_per_record_losses_v2':
        raise ValueError('旧模型采用旧验证误差口径，请在v0.3.8重新训练后推荐。')
    if recommend and saved['config'].get('purpose') != 'process':
        raise ValueError('材料表征模型只能预测已制得材料；不能直接推荐未知表征的再生工艺。')
    if recommend and not saved['gp_improves_mean']:
        raise ValueError('GP分组验证未胜过均值基线，暂停自动推荐；可以继续探索性预测或补充实验。')
    model = saved['gp'] if recommend else saved['model']
    mu, sigma = predict_bundle(model, rows, std=True)
    results = []
    train = saved['dataset']['rows']
    for index, row in enumerate(rows):
        alerts = []
        if row.get('batch_id') not in {r['batch_id'] for r in train}:
            alerts.append('原料批次缺失或训练中未见')
        for field in fields:
            key = field['key']; v = row[key]
            if v in (None, ''):
                alerts.append(key + '缺失，使用训练集处理规则')
            elif key in model.get('training_numeric_bounds', {}):
                lo, hi = model['training_numeric_bounds'][key]
                if not lo <= float(v) <= hi:
                    alerts.append(key + '超出训练范围')
            elif key in model.get('training_categories', {}) and str(v) not in model['training_categories'][key]:
                alerts.append(key + '未见类别')
            elif key not in model.get('training_categories', {}) and key not in model.get('training_numeric_bounds', {}):
                alerts.append(key + '训练中没有有效取值')
        duplicate = any(all((number(r.get(f['key'])) == number(row.get(f['key']))) if f['kind'] == 'numeric'
                            else str(r.get(f['key'])) == str(row.get(f['key'])) for f in fields) for r in train)
        if duplicate:
            alerts.append('与已测描述符组合相同')
        results.append({'record_id': row['record_id'], 'prediction': float(mu[index]),
                        'gp_latent_std': float(sigma[index]) if sigma is not None else None, 'alerts': alerts,
                        'eligible_recommendation': not alerts,
                        'score': float(mu[index] + (1 if config.get('direction', 'maximize') == 'maximize' else -1) * 2 * sigma[index]) if recommend else None})
        cal=saved.get('calibration') or {};q=cal.get('residual_threshold')
        if recommend:
            calibrated_mu,_=predict_bundle(saved['model'],[row]); interval_mu=float(calibrated_mu[0])
        else:interval_mu=float(mu[index])
        results[-1].update(interval_lower=interval_mu-q if q is not None else None,
                           interval_upper=interval_mu+q if q is not None else None,
                           interval_center=interval_mu,calibration_coverage=cal.get('nominal_coverage'),
                           interval_status='finite_group_calibration' if q is not None else 'unbounded_or_not_calibrated')
        if q is not None and (recommend or cal.get('coverage_warning')):
            results[-1]['interval_status']='diagnostic_band_not_coverage_for_selected_or_adaptive_sample'
    eligible = [r for r in results if r['eligible_recommendation']]
    if recommend:
        results.sort(key=lambda r: r['score'], reverse=config.get('direction', 'maximize') == 'maximize')
    result = {'evidence_type': 'user_descriptor_model_exploration', 'predictions': results, 'target': target,
              'selected': (max(eligible, key=lambda r: r['score']) if config.get('direction', 'maximize') == 'maximize' else min(eligible, key=lambda r: r['score'])) if recommend and eligible else None,
              'model': model['name'], 'mode': config['mode'],
              'calibration':saved.get('calibration'),
              'scope': '保存模型的新样品预测；GP标准差是潜在函数探索量。独立组校准只在可交换的外部新样本条件下解释覆盖；自适应选中的候选和含自适应反馈的数据仅提供诊断残差带，不承诺名义覆盖。有限候选UCB/LCB仍需真实实验验证。'}
    write_csv(out / 'predictions.csv', [{**r, 'alerts': ';'.join(r['alerts'])} for r in results])
    (out / 'ui_result.json').write_text(json.dumps({'result': result, 'curves': []}, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    return result
