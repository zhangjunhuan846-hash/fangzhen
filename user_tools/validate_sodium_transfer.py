"""Frozen BatteryLife model evaluated on Wenzhou cells, with/without one anchor."""
import json
from pathlib import Path
import numpy as np
from sklearn.model_selection import GroupShuffleSplit
from user_tools.workbench.sodium_learning import charge_features,soh_predict


def run(root):
    root=Path(root);base=root/'outputs/sodium_validation'
    cfg={'voltage_lower_V':3,'voltage_upper_V':3.6,'charge_sign':'positive','feature_mode':'reference_normalized'}
    train,_=charge_features((base/'batterylife/partial_charge.csv').read_bytes(),cfg,True)
    raw=(base/'wenzhou/partial_charge_with_reference.csv').read_bytes()
    target,_=charge_features(raw,cfg,True)
    folder=base/'batterylife/train6';summary=json.loads((folder/'result.json').read_text(encoding='utf8'))
    predictions=soh_predict(raw,{},folder,folder/'trained_model.joblib',summary['model_sha256'])
    indexed={r['record_id']:r for r in predictions['predictions']}
    train_idx,_=next(GroupShuffleSplit(n_splits=1,test_size=.25,random_state=42).split(train,groups=train.group_id))
    training_mean=float(train.iloc[train_idx]['target'].mean())
    result=[]
    for cell,part in target.groupby('group_id'):
        part=part.copy();part['cycle']=part.record_id.str.split('::').str[-1].astype(int);part=part.sort_values('cycle')
        anchor=part.iloc[0];later=part.iloc[1:]
        offset=float(anchor.target)-indexed[anchor.record_id]['predicted_soh']
        predicted=np.array([indexed[r]['predicted_soh'] for r in later.record_id]);observed=later.target.to_numpy()
        guarded=np.array([indexed[r]['guarded_estimate_soh'] for r in later.record_id])
        result.append({'cell':cell,'anchor_cycle':int(anchor.cycle),'later_segments':len(later),
            'uncalibrated_mae':float(np.mean(abs(observed-predicted))),
            'guarded_mae':float(np.mean(abs(observed-guarded))),
            'training_mean_baseline_mae':float(np.mean(abs(observed-training_mean))),
            'one_anchor_calibrated_mae':float(np.mean(abs(observed-(predicted+offset)))),
            'last_known_soh_baseline_mae':float(np.mean(abs(observed-float(anchor.target)))),
            'outside_training_domain_count':sum(bool(indexed[r]['joint_outside_domain']) for r in later.record_id)})
    out={'dataset':'Wenzhou sodium held out in its entirety','training_dataset':'BatteryLife NA-ion (7 of 10 cells)',
        'model_selection':'BatteryLife training group CV only; Wenzhou results did not select this model',
        'anchor_protocol':'one known measured SOH at first available segment of each Wenzhou cell; evaluate later segments only',
        'per_cell':result,'macro_uncalibrated_mae':float(np.mean([x['uncalibrated_mae'] for x in result])),
        'macro_guarded_mae':float(np.mean([x['guarded_mae'] for x in result])),
        'macro_training_mean_mae':float(np.mean([x['training_mean_baseline_mae'] for x in result])),
        'macro_anchor_mae':float(np.mean([x['one_anchor_calibrated_mae'] for x in result])),
        'macro_last_known_mae':float(np.mean([x['last_known_soh_baseline_mae'] for x in result]))}
    (base/'batterylife/cross_anchor_wenzhou.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
    return out


if __name__=='__main__':print(json.dumps(run(Path.cwd()),ensure_ascii=False))
