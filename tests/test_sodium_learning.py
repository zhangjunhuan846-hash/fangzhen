import csv
import io
import numpy as np
import pytest

pytest.importorskip('sklearn')
from user_tools.workbench.sodium_learning import charge_features,soh_train,soh_predict,hardcarbon_train,hardcarbon_predict
from user_tools.workbench.multichem_analysis import prepare_hardcarbon


def charge_csv():
    out=io.StringIO();w=csv.writer(out);w.writerow(['cell_id','segment_id','time_s','current_A','voltage_V','soh'])
    for cell in range(5):
        for cycle in range(4):
            for n in range(13):w.writerow([f'c{cell}',f's{cycle}',n*(10+cell+cycle),1,2.9+.07*n,1-.03*cycle])
    return out.getvalue().encode()


def test_fixed_window_excludes_future_measurements():
    raw=charge_csv();config={'voltage_lower_V':3.0,'voltage_upper_V':3.6,'charge_sign':'positive'}
    a,_=charge_features(raw,config,True)
    more=raw.decode()+''.join(f'c{c},s{s},10000,1,4.1,{1-.03*s}\n' for c in range(5) for s in range(4))
    # Re-sort each segment to append points for that segment without changing time ordering.
    r=list(csv.DictReader(io.StringIO(more)));r.sort(key=lambda v:(v['cell_id'],v['segment_id'],float(v['time_s'])))
    text=io.StringIO();w=csv.DictWriter(text,fieldnames=r[0].keys());w.writeheader();w.writerows(r)
    b,_=charge_features(text.getvalue().encode(),config,True)
    assert np.allclose(a['duration_s'],b['duration_s'])
    assert np.allclose(a['charge_window_Ah'],b['charge_window_Ah'])


def test_soh_holdout_and_frozen_prediction_and_hash(tmp_path):
    raw=charge_csv();config={'voltage_lower_V':3.0,'voltage_upper_V':3.6,'charge_sign':'positive'}
    result=soh_train(raw,config,tmp_path)
    assert result['holdout_groups'] and result['train_groups']+result['holdout_groups']==5
    prediction=soh_predict(raw,{},tmp_path,tmp_path/'trained_model.joblib',result['model_sha256'])
    assert len(prediction['predictions'])==20
    assert any(p['seen_training_cell'] for p in prediction['predictions'])
    shifted=raw.replace(b',1,',b',100,')
    guarded=soh_predict(shifted,{},tmp_path,tmp_path/'trained_model.joblib',result['model_sha256'])
    assert all(p['joint_outside_domain'] and p['guarded_estimate_basis']=='训练集均值回退' for p in guarded['predictions'])
    with pytest.raises(ValueError,match='校验'):
        soh_predict(raw,{},tmp_path,tmp_path/'trained_model.joblib','incorrect')


def test_hardcarbon_missing_provenance_is_excluded(tmp_path):
    header='doi,mapping_found,ice,carbonization_temperature_C,d002_nm,id_ig,ssa_m2_g,electrolyte_type,current_density_mA_g\n'
    rows=''.join(f'paper{i//2},True,0.{70+i},900,0.38,1.1,10,1,20\n' for i in range(16))
    raw=(header+rows+',False,0.9,900,0.38,1,10,1,20\n').encode()
    prepared,excluded=prepare_hardcarbon(raw)
    assert len(prepared)==16 and len(excluded)==1
    result=hardcarbon_train(raw,{},tmp_path)
    assert result['train_groups']+result['holdout_groups']==8
    assert len(list(csv.DictReader((tmp_path/'holdout.csv').open())))==result['holdout_rows']
    future=b'record_id,carbonization_temperature_C,d002_nm,id_ig,ssa_m2_g,electrolyte_type,current_density_mA_g\na,900,0.38,1.1,10,1,20\nb,3000,0.38,1.1,10,new,20\n'
    pred=hardcarbon_predict(future,{},tmp_path,tmp_path/'trained_model.joblib',result['model_sha256'])
    assert len(pred['predictions'])==2 and len(pred['predictions'][1]['alerts'])==2


def test_reference_normalized_features_reject_changing_capacity():
    raw=charge_csv().decode().replace('voltage_V,soh','voltage_V,reference_capacity_Ah,soh')
    lines=raw.splitlines();lines=[lines[0]]+[line.rsplit(',',1)[0]+',2,'+line.rsplit(',',1)[1] for line in lines[1:]]
    cfg={'voltage_lower_V':3,'voltage_upper_V':3.6,'charge_sign':'positive','feature_mode':'reference_normalized'}
    data,_=charge_features(('\n'.join(lines)+'\n').encode(),cfg,True)
    assert len(data)==20 and data['mean_charge_rate_C'].iloc[0]==pytest.approx(.5)
    lines[1]=lines[1].replace(',2,',',3,')
    with pytest.raises(ValueError,match='参考容量'):
        charge_features(('\n'.join(lines)+'\n').encode(),cfg,True)


def test_optional_boosting_models_train_by_groups(tmp_path):
    pytest.importorskip('xgboost');pytest.importorskip('catboost')
    raw=charge_csv();config={'voltage_lower_V':3.0,'voltage_upper_V':3.6,'charge_sign':'positive',
                             'algorithms':['mean','ridge','gp','xgb','catboost']}
    result=soh_train(raw,config,tmp_path)
    assert {c['model'] for c in result['training_cv']}==set(config['algorithms'])
    assert not set(result['holdout_group_ids'])&set(__import__('joblib').load(tmp_path/'trained_model.joblib')['training_groups'])


def test_reference_sodium_dfn_and_extrapolation_guard(tmp_path):
    pybamm=pytest.importorskip('pybamm')
    from user_tools.workbench.sodium_dfn import run_sodium_dfn
    result=run_sodium_dfn({'c_rate':1,'duration_s':60,'temperature_C':25},tmp_path/'short')
    assert result['chemistry']=='sodium-ion' and result['completed_duration_s']==pytest.approx(60)
    assert (tmp_path/'short'/'forward_curve.csv').exists()
    with pytest.raises(pybamm.SolverError,match='interpolation bounds'):
        run_sodium_dfn({'c_rate':1,'duration_s':3600,'temperature_C':25,'extrapolation_policy':'error'},tmp_path/'long')
    partial=run_sodium_dfn({'c_rate':1,'duration_s':3600,'temperature_C':25},tmp_path/'bounded')
    assert partial['stopped_before_extrapolation'] and 1<partial['completed_duration_s']<3600
