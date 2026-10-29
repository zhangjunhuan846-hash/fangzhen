"""Real BatteryML predictors and a vehicle-grouped CH-BatteryGen schema adapter."""
import numpy as np

from user_tools.workbench.engineering_common import finish, save, write_csv
from user_tools.workbench.engineering_contracts import csv_rows, finite


def run_batteryml(config, out, raw=None):
    import torch
    from batteryml.data import DataBundle, ZScoreDataTransformation
    from batteryml.models.rul_predictors.ridge import RidgeRULPredictor
    from batteryml.models.rul_predictors.random_forest import RandomForestRULPredictor
    from batteryml.models.rul_predictors.dummy import DummyRULPredictor
    if raw is None:
        rng = np.random.default_rng(config['seed'])
        rows = []
        for i in range(40):
            a, b = rng.uniform(0, 1, 2)
            rows.append({'cell_id': f'synthetic-cell-{i:03}', 'role': 'train' if i < 28 else 'test',
                         'feature_1': a, 'feature_2': b, 'rul_cycles': 700 - 300*a - 200*b + rng.normal(0, 10)})
    else:
        rows = csv_rows(raw)
        if config.get('features_available_before_prediction') is not True:
            raise ValueError('请声明features_available_before_prediction=true，确认特征来自预测截止前的数据。')
    keys = sorted(k for k in rows[0] if k.startswith('feature_'))
    if not keys or not {'cell_id', 'role', 'rul_cycles'} <= set(rows[0]):
        raise ValueError('寿命CSV需cell_id,role(train/test),rul_cycles以及feature_开头的特征列。')
    seen, train, test = set(), [], []
    for row in rows:
        cell = str(row['cell_id']).strip()
        if not cell or cell in seen:
            raise ValueError('每个电芯只能提供一个预测截止快照；同电芯不得跨训练/测试。')
        seen.add(cell)
        if row['role'] not in ['train', 'test']:
            raise ValueError('寿命role只能train/test。')
        item = {'cell_id': cell, 'x': [finite(row[k], k) for k in keys],
                'y': finite(row['rul_cycles'], 'rul_cycles', 0)}
        (train if row['role'] == 'train' else test).append(item)
    if len(train) < 5 or len(test) < 2:
        raise ValueError('至少5个训练电芯和2个独立测试电芯。')
    bundle = DataBundle(torch.tensor([r['x'] for r in train]), torch.tensor([r['y'] for r in train]),
                        torch.tensor([r['x'] for r in test]), torch.tensor([r['y'] for r in test]),
                        feature_transformation=ZScoreDataTransformation())
    models = {'dummy': DummyRULPredictor(), 'ridge': RidgeRULPredictor(alpha=1.),
              'random_forest': RandomForestRULPredictor(n_estimators=100, random_state=config['seed'], n_jobs=1)}
    metrics, predictions = {}, []
    for name, model in models.items():
        model.fit(bundle)
        prediction = model.predict(bundle)
        metrics[name + '_rmse_cycles'] = bundle.evaluate(prediction, 'RMSE')
        metrics[name + '_mae_cycles'] = bundle.evaluate(prediction, 'MAE')
        predictions.extend({'cell_id': row['cell_id'], 'method': name, 'observed_rul_cycles': row['y'],
                            'predicted_rul_cycles': float(prediction[i])} for i, row in enumerate(test))
    save(out / 'split_manifest.json', {'features': keys, 'train_cells': [r['cell_id'] for r in train],
                                      'test_cells': [r['cell_id'] for r in test], 'scaler_fit': 'train only'})
    result = {'kind': 'engineering', 'title': 'BatteryML官方Dummy/Ridge/RF寿命预测', 'metrics': metrics,
              'feature_columns': keys, 'train_cells': len(train), 'test_cells': len(test),
              'scope': '实际调用固定归档BatteryML的DataBundle、训练折标准化和三个官方预测器。输入为截止时点可用特征；未导入任意pickle模型，也不将合成基线误差当作真实电芯寿命准确率。'}
    return finish(config, out, result, predictions, packages=['BatteryML', 'torch', 'numpy', 'pandas', 'scikit-learn'])


def run_faults(config, out, raw=None):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import f1_score, confusion_matrix, balanced_accuracy_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
    labels = ['normal', 'high_resistance', 'low_capacity', 'self_discharge']
    if raw is None:
        rng = np.random.default_rng(config['seed'])
        rows = []
        for index in range(48):
            label = labels[index % 4]
            for step in range(12):
                spread = {'normal': .01, 'high_resistance': .15, 'low_capacity': .06, 'self_discharge': .1}[label]
                voltage = 370 + rng.normal(0, 2) - step * (3 if label == 'low_capacity' else .3)
                rows.append({'vehicle_id': f'synthetic-vehicle-{index}', 'role': 'train' if index < 32 else 'test',
                             'label': label, 'TIME': step*10, 'SUM_CURRENT': 20 + rng.normal(),
                             'SUM_VOLTAGE': voltage, 'MAX_CELL_VOLT': 3.7 + spread + rng.normal(0, .002),
                             'MIN_CELL_VOLT': 3.7 - spread - (step*.003 if label == 'self_discharge' else 0),
                             'MAX_TEMP': 25 + (5 if label == 'high_resistance' else 0), 'MIN_TEMP': 24})
    else:
        rows = csv_rows(raw)
    signals = ['SUM_CURRENT', 'SUM_VOLTAGE', 'MAX_CELL_VOLT', 'MIN_CELL_VOLT', 'MAX_TEMP', 'MIN_TEMP']
    if not {'vehicle_id', 'role', 'label', 'TIME', *signals} <= set(rows[0]):
        raise ValueError('故障CSV需要vehicle_id,role,label与CH-BatteryGen的总电流/电压、最高最低单体电压和温度列。')
    vehicles = {}
    for row in rows:
        ident = str(row['vehicle_id']).strip()
        label = {'low_capacit': 'low_capacity'}.get(str(row['label']), str(row['label']))
        if not ident or row['role'] not in ['train', 'test'] or label not in labels:
            raise ValueError('车辆编号、train/test或故障标签不合法。')
        entry = vehicles.setdefault(ident, {'role': row['role'], 'label': label, 'points': [], 'last_time': None})
        if (entry['role'], entry['label']) != (row['role'], label):
            raise ValueError('同车辆不得跨训练/测试或使用冲突标签。')
        timestamp = finite(row['TIME'], 'TIME', 0)
        if entry['last_time'] is not None and timestamp <= entry['last_time']:
            raise ValueError('同车辆TIME需严格递增；多次记录请先定义窗口，不得直接拼接重置时间。')
        entry['last_time'] = timestamp
        entry['points'].append([finite(row[k], k) for k in signals])
    train, test, features = [], [], []
    for ident, vehicle in vehicles.items():
        if len(vehicle['points']) < 3:
            raise ValueError('每辆车至少三个时间点。')
        values = np.array(vehicle['points'])
        x = np.r_[values.mean(0), values.std(0), values[-1]-values[0]]
        feature = {'vehicle_id': ident, 'role': vehicle['role'], 'label': vehicle['label'], 'x': x}
        (train if vehicle['role'] == 'train' else test).append(feature)
        features.append(feature)
    if len(train) < 8 or len(test) < 4 or set(r['label'] for r in train) != set(labels) or set(r['label'] for r in test) != set(labels):
        raise ValueError('训练集至少8辆且覆盖全部四类；测试集至少4辆。')
    models = {'RF': RandomForestClassifier(n_estimators=100, random_state=config['seed'], class_weight='balanced', n_jobs=1),
              'SVM': make_pipeline(StandardScaler(), SVC(class_weight='balanced'))}
    metrics, predictions, matrices = {}, [], {}
    for name, model in models.items():
        model.fit([r['x'] for r in train], [r['label'] for r in train])
        observed = [r['label'] for r in test]
        predicted = model.predict([r['x'] for r in test])
        metrics[name + '_macro_f1'] = float(f1_score(observed, predicted, labels=labels, average='macro', zero_division=0))
        metrics[name + '_balanced_accuracy'] = float(balanced_accuracy_score(observed, predicted))
        matrices[name] = confusion_matrix(observed, predicted, labels=labels).tolist()
        predictions.extend({'vehicle_id': row['vehicle_id'], 'method': name, 'observed': row['label'], 'predicted': str(value)}
                            for row, value in zip(test, predicted))
    save(out / 'fault_confusion.json', {'labels': labels, 'matrices': matrices})
    write_csv(out / 'vehicle_features.csv', [{**{k: r[k] for k in ['vehicle_id', 'role', 'label']},
               **{f'feature_{i}': float(value) for i, value in enumerate(r['x'])}} for r in features])
    result = {'kind': 'engineering', 'title': 'CH-BatteryGen字段适配与车辆分组故障基线', 'metrics': metrics,
              'labels': labels, 'confusion_matrices': matrices,
              'dataset_kind': 'synthetic_platform_demo' if raw is None else config.get('dataset_kind', 'user_declared'),
              'scope': 'CH字段和四类标签适配，按车辆隔离训练/测试，真实运行RF/SVM。当前不是论文CNN复现；官方CH公开数据也是生成数据。未用公开或合成故障结果替代真实车队验证。'}
    return finish(config, out, result, predictions, packages=['scikit-learn', 'numpy'])
