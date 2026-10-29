"""Descriptive test-set Pareto ranking, not a prospective optimization experiment."""
from pathlib import Path
import json
import numpy as np
import pandas as pd


def nondominated(points):
    return np.array([not np.any(np.all(points>=p,axis=1)&np.any(points>p,axis=1)) for p in points])


def main():
    path=Path('outputs/hardcarbon_dfn_validation/measured_gated/holdout.csv')
    frame=pd.read_csv(path)
    predicted=nondominated(frame[['predicted_ice','predicted_capacity_mAh_g']].to_numpy())
    observed=nondominated(frame[['observed_ice','observed_capacity_mAh_g']].to_numpy())
    n=int((predicted&observed).sum())
    result={'rows':len(frame),'groups':int(frame.group_id.nunique()),'predicted_pareto':int(predicted.sum()),
            'observed_pareto':int(observed.sum()),'overlap':n,
            'precision':float(n/predicted.sum()) if predicted.sum() else None,
            'recall':float(n/observed.sum()) if observed.sum() else None,
            'scope':'Retrospective ranking of heterogeneous measured literature records on the already explored holdout; no new experiments, no operating constraints, and repeated samples per publication. Does not validate prospective optimization.'}
    (path.parent/'pareto_diagnostic.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
