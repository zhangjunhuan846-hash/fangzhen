"""Official BatteryLife architectures; whole-cell and protocol-group holdout validation."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import time
from types import SimpleNamespace
import numpy as np

from user_tools.workbench.engineering_common import ROOT, finish, save, write_csv
from user_tools.workbench.engineering_vendor import upstream


def run_batterylife(config, out):
    import torch
    from sklearn.linear_model import Ridge
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    start = time.perf_counter(); out = Path(out)
    torch.set_num_threads(1); torch.manual_seed(config['seed']); np.random.seed(config['seed'])
    audit = upstream('BatteryLife', out)
    root = ROOT/'data/public/hust_batterylife'
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256((root/'early10.npz').read_bytes()).hexdigest() != manifest['npz_sha256']:
        raise ValueError('BatteryLife公开特征文件校验失败。')
    data = np.load(root/'early10.npz', allow_pickle=False)
    x, y, roles, ids = (data[k] for k in ['features', 'labels', 'roles', 'cell_ids'])
    if len(set(ids)) != len(ids) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('特征需有限且每个电芯只允许一个预测快照。')
    train, val, test = [np.flatnonzero(roles == r) for r in ['train', 'validation', 'test']]
    if min(map(len, [train, val, test])) < 3:
        raise ValueError('训练/验证/测试均需至少3个独立电芯。')
    # Fit feature and target transformations on training cells only.
    xm = x[train].mean(axis=(0, 1, 3), keepdims=True)
    xs = x[train].std(axis=(0, 1, 3), keepdims=True).clip(1e-6)
    ym, ys = y[train].mean(), max(y[train].std(), 1.)
    xt = torch.tensor((x-xm)/xs, dtype=torch.float32)
    yt = torch.tensor((y-ym)/ys, dtype=torch.float32).reshape(-1, 1)
    args = SimpleNamespace(d_model=32, d_ff=64, charge_discharge_length=64, early_cycle_threshold=10,
            dropout=.1, e_layers=1, d_layers=1, n_heads=4, factor=3, activation='gelu', output_num=1)
    model = importlib.import_module('models.'+config['architecture']).Model(args)
    optimizer = torch.optim.Adam(model.parameters(), lr=.001, weight_decay=1e-4)
    mask = torch.ones(len(x), 10)
    history, best, checkpoint, best_epoch = [], float('inf'), None, None
    for epoch in range(config['epochs']):
        model.train(); optimizer.zero_grad()
        loss = torch.nn.functional.mse_loss(model(xt[train], mask[train]), yt[train])
        if not torch.isfinite(loss): raise ValueError('BatteryLife训练损失非有限。')
        loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 5.); optimizer.step()
        model.eval()
        with torch.no_grad(): validation = float(torch.nn.functional.mse_loss(model(xt[val], mask[val]), yt[val]))
        history.append(dict(epoch=epoch+1, train_loss=float(loss.detach()), validation_loss=validation))
        if validation < best:
            best, checkpoint, best_epoch = validation, copy.deepcopy(model.state_dict()), epoch+1
    model.load_state_dict(checkpoint); model.eval()
    # No test prediction or metric is computed before validation-only checkpoint selection.
    with torch.no_grad(): prediction = model(xt, mask).ravel().numpy()*ys+ym
    torch.save({'state_dict': checkpoint, 'architecture': config['architecture'], 'config': vars(args),
         'feature_mean': xm.tolist(), 'feature_std': xs.tolist(), 'label_mean': float(ym), 'label_std': float(ys),
         'selected_epoch': best_epoch, 'training_cell_ids': ids[train].tolist()}, out/'batterylife_checkpoint.pt')
    flat = xt.numpy().reshape(len(x), -1)
    ridge = Ridge(alpha=100.).fit(flat[train], y[train]).predict(flat)
    predictions = {'BatteryLife_'+config['architecture']: prediction, 'Ridge_alpha100': ridge, 'training_mean': np.full(len(y), ym)}
    rows = []
    for name, pred in predictions.items():
        for i in test:
            rows.append(dict(cell_id=str(ids[i]), role='test', model=name, reference_rul_cycles=float(y[i]), predicted_rul_cycles=float(pred[i])))
    scores = {name: {'test_mae_cycles': mean_absolute_error(y[test], pred[test]),
                      'test_rmse_cycles': mean_squared_error(y[test], pred[test])**.5,
                      'test_mape_percent': float(np.mean(abs(pred[test]-y[test])/y[test])*100),
                      'test_r2': r2_score(y[test], pred[test])} for name, pred in predictions.items()}
    save(out/'batterylife_split.json', {'data': manifest, 'normalizers_fit_on': ids[train], 'validation_ids': ids[val],
         'test_ids': ids[test], 'selected_epoch': best_epoch, 'upstream': audit,
         'scores': scores, 'future_curve_read_by_model': False, 'retrained_on_test': False})
    write_csv(out/'batterylife_training.csv', history)
    metrics = dict(train_cells=len(train), validation_cells=len(val), test_cells=len(test), selected_epoch=best_epoch,
                   **scores['BatteryLife_'+config['architecture']], elapsed_s=time.perf_counter()-start)
    curve = [{'name': '独立电芯寿命预测', 'primary': '预测RUL', 'secondary': '公开标签RUL', 'y_label': '剩余循环数',
              'points': [[int(i), float(prediction[k]), float(y[k])] for i, k in enumerate(test)]}]
    return finish(config, out, {'kind': 'engineering', 'title': 'BatteryLife '+config['architecture']+' · HUST独立电芯验证',
         'engine': 'official BatteryLife.models.'+config['architecture'], 'upstream_commit': audit['commit'],
         'metrics': metrics, 'baselines': scores,
         'details': {'scope': 'HUST公开LFP/石墨1.1Ah电芯；前10循环预测作者给定RUL。按协议组划分电芯，训练集标准化，验证集选epoch后一次测试。此分支与Panasonic PF电芯不同。'}}, rows, curve, ['torch', 'numpy', 'scikit-learn'])
