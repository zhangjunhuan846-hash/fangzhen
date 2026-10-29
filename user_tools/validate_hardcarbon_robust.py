"""Prespecified grouped robustness comparison; all tuning is inside training groups."""
from pathlib import Path
import hashlib
import json
import numpy as np
from user_tools.workbench.hardcarbon_joint import train


def main():
    source=Path('data/external/hardcarbon_2026/source_master.csv');raw=source.read_bytes()
    root=Path('outputs/hardcarbon_dfn_validation/robust_grouped');root.mkdir(parents=True,exist_ok=True)
    seeds=[11,29,71,101]
    algorithms=['mean','ridge','trees','trees_fine','xgb','xgb_l1','catboost','catboost_mae','tabpfn','tabicl']
    runs=[]
    for mode in ['process','measured_extended']:
        for seed in seeds:
            out=root/f'{mode}_{seed}';result=train(raw,{'feature_mode':mode,'split_seed':seed,'algorithms':algorithms},out)
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            summary={'mode':mode,'seed':seed,'targets':{}}
            for target,r in result['targets'].items():
                summary['targets'][target]={'selected_model':r['selected_model'],'cv_mae':next(x['cv']['mae'] for x in r['training_cv'] if x['model']==r['selected_model']),
                    'group_mae':r['holdout']['mae'],'baseline_mae':r['holdout_mean_baseline']['mae'],'groups':r['holdout_groups'],
                    'worst_group_mae':r['holdout']['worst_group_mae']}
            runs.append(summary);print(json.dumps(summary,ensure_ascii=False),flush=True)
    aggregate={}
    for mode in ['process','measured_extended']:
        aggregate[mode]={}
        for target in ['ice','capacity_mAh_g']:
            data=[r['targets'][target] for r in runs if r['mode']==mode]
            aggregate[mode][target]={'mean_group_mae':float(np.mean([x['group_mae'] for x in data])),
                'mean_baseline_mae':float(np.mean([x['baseline_mae'] for x in data])),
                'seeds_beating_baseline':sum(x['group_mae']<x['baseline_mae'] for x in data),
                'selected_models':[x['selected_model'] for x in data]}
    payload={'source_sha256':hashlib.sha256(raw).hexdigest(),'seeds':seeds,'candidate_algorithms':algorithms,
             'protocol':'25% groups held out for each split; algorithms selected by training-group CV; same public dataset used in earlier development; repeated tests are not independent prospective validation',
             'runs':runs,'aggregate':aggregate}
    (root/'summary.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(aggregate,ensure_ascii=False))


if __name__=='__main__':main()
