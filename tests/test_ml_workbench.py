import copy
import json
import numpy as np
import pytest
from user_tools.workbench.ml_data import csv_dataset, validate_selection, workspace_dataset
from user_tools.workbench.store import blank_tables
from user_tools.workbench.ml_worker import train, infer, fit_bundle, predict_bundle

def data(n=24, repeat=False):
    rows = []
    for i in range(n):
        x = i / (n - 1)
        rows.append({'record_id': 's' + str(i), 'group_id': 'g' + str(i // 2 if repeat else i), 'batch_id': 'A',
                     'x': x, 'z': (i % 3) / 3, 'target': 100 + 20*x, 'junk': None})
    return {'rows': rows, 'fields': [{'key': 'x', 'label': 'x', 'kind': 'numeric', 'stage': 'process'},
                                   {'key': 'z', 'label': 'z', 'kind': 'numeric', 'stage': 'process'},
                                   {'key': 'junk', 'label': 'junk', 'kind': 'numeric', 'stage': 'measured'}],
            'target': 'capacity', 'exclusions': [], 'group_basis': 'declared', 'source': 'synthetic'}

def config():
    return {'features': ['x', 'z'], 'purpose': 'process', 'selector': 'spearman', 'top_k': 1}

def test_selector_cannot_select_target_or_future():
    d = data(); c = config(); c['features'] = ['capacity']
    with pytest.raises(ValueError, match='目标|编号'):
        validate_selection(d, c)
    c['features'] = ['junk']
    with pytest.raises(ValueError, match='实验前'):
        validate_selection(d, c)

def test_grouped_oof_and_saved_predictions(tmp_path):
    d = data(repeat=True); result = train(d, config(), tmp_path)
    assert result['independent_groups'] == 12 and len(result['oof']) == 24
    for group in {r['group_id'] for r in result['oof']}:
        assert len({r['fold'] for r in result['oof'] if r['group_id'] == group}) == 1
    assert all(c['status'] == 'complete' for c in result['comparisons'])
    assert result['comparisons'][1]['metrics']['mae'] < result['comparisons'][0]['metrics']['mae']
    r = infer({'mode': 'ml_predict', 'model_path': str(tmp_path/'model.joblib'),
               'prediction_rows': [{'record_id': 'new', 'batch_id': 'A', 'x': .45, 'z': .1}]}, tmp_path/'pred')
    assert abs(r['predictions'][0]['prediction'] - 109) < 4
    assert r['selected'] is None

def test_fold_preprocessing_does_not_see_holdout():
    d = data(); fields = d['fields'][:2]; cfg = config()
    training = d['rows'][:16]
    first = fit_bundle(training, fields, cfg, 'ridge')
    testing = copy.deepcopy(d['rows'][16:]); testing[0]['target'] = 1e9
    second = fit_bundle(training, fields, cfg, 'ridge')
    assert first['selected'] == second['selected'] == ['x']
    np.testing.assert_allclose(predict_bundle(first, testing)[0], predict_bundle(second, testing)[0])
    np.testing.assert_allclose(first['prep'].named_transformers_['numeric']['imputer'].statistics_,
                               [np.median([r['x'] for r in training])])

def test_unknown_batch_extrapolation_and_duplicate_blocked(tmp_path):
    train(data(), config(), tmp_path)
    r = infer({'mode': 'ml_recommend', 'model_path': str(tmp_path/'model.joblib'),
               'prediction_rows': [{'record_id': 'old', 'batch_id': 'A', 'x': '0.0', 'z': '0.0'},
                                   {'record_id': 'outside', 'batch_id': 'A', 'x': 2, 'z': .1},
                                   {'record_id': 'batch', 'batch_id': 'B', 'x': .42, 'z': .1}]}, tmp_path/'infer')
    assert r['selected'] is None and all(r['alerts'] for r in r['predictions'])

def test_material_cannot_recommend(tmp_path):
    c = config(); c['purpose'] = 'material'; train(data(), c, tmp_path)
    with pytest.raises(ValueError, match='材料表征模型'):
        infer({'mode': 'ml_recommend', 'model_path': str(tmp_path/'model.joblib'), 'prediction_rows': [{'record_id': 'x', 'x': .4, 'z': .5}]}, tmp_path/'infer')

def test_missing_targets_not_imputed_and_ids_checked():
    raw = b'record_id,group_id,batch_id,x,capacity\na,g,A,1,100\nb,h,A,2,\n'
    d = csv_dataset(raw, {'target': 'capacity'})
    assert len(d['rows']) == 1 and len(d['exclusions']) == 1
    with pytest.raises(ValueError, match='record_id'):
        csv_dataset(raw+b'a,k,A,3,103\n', {'target': 'capacity'})

def test_workspace_joins_char_target_without_halfcells():
    t = blank_tables()
    for i in range(5):
        t['处理工艺'].append({'sample_id': 's'+str(i), 'batch_id': 'A', 'temperature_C': 600, 'method': 'heat'})
        t['表征'].append({'sample_id': 's'+str(i), 'true_density_g_cm3': 2.1+i*.01})
    d = workspace_dataset(t, {'target': '表征.true_density_g_cm3'})
    assert len(d['rows']) == 5 and len({r['group_id'] for r in d['rows']}) == 1
    assert d['rows'][0]['target'] == 2.1
    with pytest.raises(ValueError, match='独立工艺组'):
        train(d, {'features': ['处理工艺.temperature_C']}, 'unused')

def test_workspace_replicates_require_consistent_protocol():
    t = blank_tables(); t['处理工艺'] = [{'sample_id': 's', 'batch_id': 'A', 'temperature_C': 600}]
    t['极片'] = [{'electrode_id': 'e', 'sample_id': 's'}]
    base = {'sample_id': 's', 'electrode_id': 'e', 'c_rate': 1, 'cycle': 1, 'temperature_C': 25,
            'electrolyte_recipe': 'EC', 'separator_type': 'PP', 'voltage_lower_V': .01, 'voltage_upper_V': 1.5, 'capacity': 300}
    t['半电池'] = [{**base, 'cell_id': 'a'}, {**base, 'cell_id': 'b', 'capacity': 320}]
    d = workspace_dataset(t, {'target': '半电池.capacity'})
    assert d['rows'][0]['target'] == 310 and d['rows'][0]['replicates'] == 2
    t['半电池'][1]['electrolyte_recipe'] = 'PC'
    with pytest.raises(ValueError, match='测试体系不同'):
        workspace_dataset(t, {'target': '半电池.capacity'})

def test_prediction_cannot_include_hidden_label(tmp_path):
    train(data(), config(), tmp_path)
    with pytest.raises(ValueError, match='目标标签'):
        infer({'mode': 'ml_predict', 'model_path': str(tmp_path/'model.joblib'), 'prediction_rows': [{'record_id': 'n', 'x': .4, 'z': .2, 'capacity': 110}]}, tmp_path/'infer')

def test_dropped_constant_route_still_blocks_unseen_route(tmp_path):
    d=data(); d['fields'].append({'key':'route','label':'route','kind':'categorical','stage':'process'})
    for r in d['rows']:r['route']='thermal'
    cfg=config();cfg['features'].append('route');train(d,cfg,tmp_path)
    r=infer({'mode':'ml_recommend','model_path':str(tmp_path/'model.joblib'),
             'prediction_rows':[{'record_id':'n','batch_id':'A','x':.42,'z':.21,'route':'acid'}]},tmp_path/'infer')
    assert r['selected'] is None and any('未见类别' in a for a in r['predictions'][0]['alerts'])

def test_saved_model_hash_checked_before_loading(tmp_path):
    train(data(),config(),tmp_path)
    with pytest.raises(ValueError,match='校验值'):
        infer({'mode':'ml_predict','model_path':str(tmp_path/'model.joblib'),'expected_model_sha256':'0'*64,
               'prediction_rows':[{'record_id':'n','batch_id':'A','x':.4,'z':.1}]},tmp_path/'infer')
