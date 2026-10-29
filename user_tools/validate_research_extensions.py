"""Exploratory public hard-carbon validation; group-level disjoint splits."""
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBRegressor

from user_tools.workbench.multichem_analysis import prepare_hardcarbon
from user_tools.workbench.research_extensions import uncertainty_audit, hardcarbon_shap


def main():
    source=Path('data/external/hardcarbon_2026/source_master.csv')
    out=Path('outputs/new_methods_validation/intervals'); out.mkdir(parents=True,exist_ok=True)
    rows,_=prepare_hardcarbon(source.read_bytes())
    # One paper contributes one calibration/test row; repeated paper rows can violate exchangeability.
    frame=pd.DataFrame(rows).groupby('group_id',sort=True,as_index=False).first()
    features=['carbonization_temperature_C','d002_nm','id_ig','ssa_m2_g','electrolyte_type','current_density_mA_g']
    numeric=[c for c in features if c!='electrolyte_type']
    for c in numeric:frame[c]=pd.to_numeric(frame[c],errors='coerce')
    frame['electrolyte_type']=frame.electrolyte_type.fillna('missing').astype(str)
    rng=np.random.RandomState(20261029); order=rng.permutation(len(frame))
    parts=np.array_split(order,[int(.55*len(frame)),int(.70*len(frame)),int(.85*len(frame))])
    train,ref,cal,test=[frame.iloc[p].copy() for p in parts]
    transformer=ColumnTransformer([('num',make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler()),numeric),
                                    ('cat',OneHotEncoder(handle_unknown='ignore'),['electrolyte_type'])])
    model=make_pipeline(transformer,XGBRegressor(n_estimators=120,max_depth=3,learning_rate=.05,reg_lambda=5,n_jobs=1,random_state=42))
    model.fit(train[features],train.ice)
    # KMM's numerical input is imputed using training data only.
    med=train[numeric].median().fillna(0)
    audit=[]
    for role,subset in [('reference',ref),('calibration',cal),('test',test)]:
        p=subset[numeric].fillna(med).copy();p['role']=role;p['group_id']=subset.group_id
        p['predicted']=model.predict(subset[features]);p['observed']=subset.ice
        audit.append(p)
    audit=pd.concat(audit); raw=audit.to_csv(index=False).encode()
    (out/'group_predictions.csv').write_bytes(raw)
    result=uncertainty_audit(raw,{'alpha':.1,'beta':.05,'feature_columns':numeric,'weight_bound':10})
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    # Reuse the prior frozen grouped model to test SHAP against real held-out examples.
    prior=Path('outputs/new_methods_validation/combined_seed2026/trained_model.joblib')
    if prior.exists():
        saved=joblib.load(prior)
        held=frame[~frame.group_id.isin(saved['training_groups'])].head(5)
        explanation=hardcarbon_shap(held[features].to_csv(index=False).encode(),
            {'_model_path':str(prior),'_model_sha256':hashlib.sha256(prior.read_bytes()).hexdigest(),
             '_training_source_path':str(source),'_training_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
        (out/'shap.json').write_text(json.dumps(explanation,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(explanation,ensure_ascii=False))


if __name__=='__main__':main()
