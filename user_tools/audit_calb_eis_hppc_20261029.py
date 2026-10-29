"""Recompute reported window errors from exported predictions, without refitting."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

root = Path('outputs/eis_bms_validation/calb_eis_hppc_ablation_20261029')
summary = json.loads((root / 'summary.json').read_text(encoding='utf8'))
traces = pd.read_csv(root / 'window_traces.csv')
records = pd.DataFrame(summary['records'])
for (kind, window), group in traces.groupby(['window_type', 'window']):
    methods = {name: part.reset_index(drop=True) for name, part in group.groupby('method')}
    assert set(methods) == {'hppc_only', 'eis_initial', 'joint'}
    baseline = methods['hppc_only']
    for method, part in methods.items():
        for column in ('time_s', 'current_A', 'measured_voltage_V', 'soc_proxy'):
            assert np.allclose(part[column], baseline[column], atol=1e-12, rtol=0), (kind, window, method, column)
        row = records[(records.window_type == kind) & (records.window == window) & (records.method == method)].iloc[0]
        for prediction, observed, key, factor in (
            ('open_loop_voltage_V', 'measured_voltage_V', 'open_loop_rmse_mV', 1000),
            ('ekf_prior_voltage_V', 'measured_voltage_V', 'ekf_prior_rmse_mV', 1000),
            ('ekf_posterior_voltage_V', 'measured_voltage_V', 'ekf_posterior_residual_rmse_mV', 1000),
            ('soc_ekf', 'soc_proxy', 'soc_proxy_rmse_pp', 100),
        ):
            value = float(np.sqrt(np.mean((part[prediction] - part[observed]) ** 2)) * factor)
            assert np.isclose(value, row[key], atol=1e-8, rtol=0), (kind, window, method, key, value, row[key])
print(f'PASS: {len(records)} window/method records, common inputs and four metrics recomputed from exported traces')
