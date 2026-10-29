"""Exploratory leave-one-Wenzhou-cell-out after adding BatteryLife cells."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from user_tools.workbench.sodium_learning import charge_features,grouped_fit,SOH_NORMALIZED_FEATURES


def run(root,holdout_source='wenzhou',selection_policy='mean_group'):
    base=Path(root)/'outputs/sodium_validation'
    cfg={'voltage_lower_V':3.,'voltage_upper_V':3.6,'charge_sign':'positive','feature_mode':'reference_normalized'}
    a,ae=charge_features((base/'batterylife/partial_charge.csv').read_bytes(),cfg,True)
    b,be=charge_features((base/'wenzhou/partial_charge_with_reference.csv').read_bytes(),cfg,True)
    combined=pd.concat([a,b],ignore_index=True);records=[]
    if holdout_source not in ('wenzhou','batterylife'):raise ValueError('未知留出数据来源。')
    for cell in sorted((b if holdout_source=='wenzhou' else a).group_id.unique()):
        output=grouped_fit(combined,SOH_NORMALIZED_FEATURES,[],base/('pooled_loco_'+selection_policy)/cell,
            {'kind':'partial_charge_soh','voltage_lower_V':3.,'voltage_upper_V':3.6,
             'charge_sign':'positive','feature_mode':'reference_normalized'},
            algorithms=['mean','ridge','trees','gp','xgb','catboost'],holdout_groups=[cell],selection_policy=selection_policy)
        records.append(output)
    result={'protocol':'leave each '+holdout_source+' cell out; all other cells in training; grouped CV selects model',
        'selection_policy':selection_policy,
        'qualification':'exploratory: these datasets were used for development and model comparisons; independent future external evaluation required',
        'batterylife_cells':int(a.group_id.nunique()),'wenzhou_cells':int(b.group_id.nunique()),
        'batterylife_rows':len(a),'wenzhou_rows':len(b),'excluded':{'batterylife':len(ae),'wenzhou':len(be)},
        'mean_mae':float(np.mean([r['holdout']['mae'] for r in records])),
        'mean_baseline_mae':float(np.mean([r['holdout_mean_baseline']['mae'] for r in records])),
        'folds':records}
    (base/('pooled_loco_'+holdout_source+'_'+selection_policy+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result


if __name__=='__main__':
    import sys
    result=run(Path.cwd(),sys.argv[1] if len(sys.argv)>1 else 'wenzhou',sys.argv[2] if len(sys.argv)>2 else 'mean_group')
    print(json.dumps({k:result[k] for k in ['batterylife_cells','wenzhou_cells','mean_mae','mean_baseline_mae']}))
