import copy
import json
import numpy as np
import pytest
from user_tools.workbench.ml_calibration import split_groups,calibrate
from user_tools.workbench.ml_worker import train,infer
from user_tools.workbench.ml_worker import group_metrics
from user_tools.workbench.research_data import parse_campaign,input_conflicts
from user_tools.workbench.research_worker import noisy_hvi,multi_run
from user_tools.workbench.chain_worker import run_chain
from user_tools.workbench.experiment_ledger import ExperimentLedger

def multi_data(n=24):
    objectives=[{'key':'capacity','direction':'maximize','lower':0},
                {'key':'ice','direction':'maximize','lower':.8,'upper':1},
                {'key':'carbon','direction':'minimize','known':True,'lower':0},
                {'key':'cost','direction':'minimize','known':True,'lower':0}]
    rows=[{'record_id':f'o{i}','group_id':f'g{i}','batch_id':'A','status':'completed','x':i/(n-1),
           'capacity':250+100*i/(n-1),'ice':.9+.05*i/(n-1),'carbon':20+i/5,'cost':10+i/5} for i in range(n)]
    rows.append({'record_id':'new','group_id':'newgroup','batch_id':'A','status':'candidate','x':.93,
                 'capacity':None,'ice':None,'carbon':10.,'cost':8.})
    return {'rows':rows,'fields':[{'key':'x','kind':'numeric','stage':'process'}],'objectives':objectives,'source':'synthetic'}

def test_calibration_partition_is_independent_and_small_n_unbounded():
    rows=[{'group_id':f'g{i}','target':i} for i in range(24)]
    dev,cal,plan=split_groups(rows,.1)
    assert len(cal)==9 and len(dev)==15
    assert not {r['group_id'] for r in dev}&{r['group_id'] for r in cal}
    c=calibrate(cal,[r['target']+1 for r in cal],.1)
    assert c['finite'] and c['residual_threshold']==1
    assert not split_groups(rows[:10],.1)[2]['finite']
    assert not calibrate(rows[:9],[r['target'] for r in rows[:9]],.05)['finite']

def test_group_calibration_uses_max_residual_not_replicate_count():
    rows=[{'group_id':f'g{i}','target':i} for i in range(9)]
    rows += [{'group_id':'g0','target':10}]*10
    c=calibrate(rows,[r['target']-2 if r['group_id']!='g0' else 0 for r in rows],.1)
    assert c['calibration_groups']==9 and c['residual_threshold']==10

def test_group_loss_does_not_cancel_opposite_errors():
    r=group_metrics([{'group_id':'a','observed':100,'predicted':110},{'group_id':'a','observed':100,'predicted':90},
                     {'group_id':'b','observed':100,'predicted':100}])
    assert r['mae']==5 and r['bias']==0 and r['rmse']==pytest.approx(np.sqrt(50))

def test_joint_hvi_duplicate_zero_and_five_dimensions():
    obj=[{'key':'a','direction':'maximize'},{'key':'b','direction':'maximize'}]
    mean,se,p=noisy_hvi(np.ones((32,2,2)),1,obj,[0,0],512)
    assert mean[0]==0 and se[0]==0
    objs=[{'key':str(i),'direction':'maximize'} for i in range(5)]
    draws=np.tile(np.array([[.5]*5,[1.]*5]),(32,1,1))
    mean,_,_=noisy_hvi(draws,1,objs,np.zeros(5),4096)
    assert abs(mean[0]-(1-.5**5))<.01
    scaled,_,_=noisy_hvi(draws*np.array([2,3,4,5,6]),1,objs,np.zeros(5),4096)
    np.testing.assert_allclose(mean*np.prod([2,3,4,5,6]),scaled)

def test_multi_objective_with_known_carbon_cost_and_intervals(tmp_path):
    d=multi_data();r=multi_run(d,{'selector':'manual','alpha':.1,'mc_samples':32,'hv_grid':512,'allow_exploration':True},tmp_path)
    assert len(r['objectives'])==4 and len(r['ranking'])==1
    assert r['selected']['record_id']=='new'
    assert r['ranking'][0]['predictions']['carbon']['calibrated_interval']['status']=='known_scenario_point'
    assert all(di['calibration']['finite'] for di in r['diagnostics'])
    assert r['selected']['record']['capacity'] is None

def test_bootstrap_recommends_input_coverage_not_fake_performance(tmp_path):
    d=multi_data(4);r=multi_run(d,{},tmp_path)
    assert r['recommendation_status']=='initial_space_filling_design'
    assert r['ranking']==[] and r['selected']['record']['capacity'] is None

def test_partial_target_generates_supplement_advice(tmp_path):
    d=multi_data();d['rows'][0]['status']='partial';d['rows'][0]['ice']=None
    r=multi_run(d,{'allow_exploration':True,'mc_samples':32,'hv_grid':512},tmp_path)
    assert any(a['type']=='complete_missing_target' and a['target']=='ice' for a in r['measurement_advice'])

def test_parser_rejects_future_labels_and_mixed_batches():
    cfg={'features':['x'],'roles':{'x':'process'},'objectives':[{'key':'capacity','direction':'maximize'}],'same_protocol':True}
    raw=b'record_id,group_id,batch_id,status,x,capacity\na,g,A,candidate,1,100\n'
    with pytest.raises(ValueError,match='未来'):parse_campaign(raw,cfg)
    raw=b'record_id,group_id,batch_id,status,x,capacity\na,g,A,candidate,1,\nb,h,B,candidate,2,\n'
    with pytest.raises(ValueError,match='一个原料批次'):parse_campaign(raw,cfg)

def test_input_constraints_and_seen_design_are_blocked():
    fields=[{'key':'a','kind':'numeric'},{'key':'b','kind':'numeric'}]
    observed=[{'a':.2,'b':.8},{'a':.8,'b':.2}]
    cfg={'sum_constraints':[{'keys':['a','b'],'total':1,'tolerance':.01}]}
    assert '配方求和约束冲突' in input_conflicts({'a':.4,'b':.4},fields,observed,cfg)
    assert any('重复' in e for e in input_conflicts({'a':.2,'b':.8},fields,observed,cfg))

def test_versioned_feedback_never_copies_predictions(tmp_path):
    ledger=ExperimentLedger(tmp_path/'ledger.sqlite');d=multi_data()
    plan=ledger.plan('w','campaign','model',d['rows'][-1],d['objectives'])
    assert plan['record']['capacity'] is None and plan['record']['carbon']==10
    partial=ledger.feedback(plan['id'],1,{'capacity':345})
    assert partial['status']=='partial' and partial['record']['ice'] is None
    complete=ledger.feedback(plan['id'],2,{'ice':.94})
    assert complete['status']=='completed'
    with pytest.raises(ValueError,match='已更新'):ledger.feedback(plan['id'],2,{'ice':.93})
    merged=ledger.merge('w','campaign',d['rows'])
    assert next(r for r in merged if r['record_id']=='new')['capacity']==345
    assert d['rows'][-1]['capacity'] is None
    repeat=ledger.plan('w','campaign','model',d['rows'][0],d['objectives'],True)
    assert repeat['record']['group_id']==d['rows'][0]['group_id'] and repeat['record']['capacity'] is None
    failure=ledger.feedback(repeat['id'],1,{},'failed_measurement')
    assert failure['status']=='failed_measurement' and failure['record']['capacity'] is None

def test_chain_nested_oof_and_variance_propagation(tmp_path):
    rows=[]
    for i in range(20):
        x=i/19;structure=2+.2*x;rows.append({'record_id':f's{i}','group_id':f'g{i}','batch_id':'A','x':x,'density':structure,'target':100+50*x})
    d={'rows':rows,'fields':[{'key':'x','kind':'numeric','stage':'process'},{'key':'density','kind':'numeric','stage':'measured'}],
       'target':'capacity','source':'synthetic'}
    cfg={'process_features':['x'],'intermediates':['density'],'selector':'manual','alpha':.1,'intermediate_bounds':{'density':[0,None]}}
    r=run_chain(d,cfg,[{'record_id':'new','batch_id':'A','x':.55}],tmp_path)
    assert r['calibration']['finite'] and len(r['oof'])==11
    p=r['predictions'][0]
    assert abs(p['propagated_std']**2-p['structure_induced_variance']-p['conditional_performance_variance'])<1e-8
    assert p['interval_lower'] is not None and p['structural_predictions']['density']['mean']>0
    assert p['usable_for_model_exploration'] and not p['usable_for_decision']

def test_standard_ml_auto_interval_frozen_calibration(tmp_path):
    rows=[{'record_id':f'r{i}','group_id':f'g{i}','batch_id':'A','x':i/23,'target':100+20*i/23} for i in range(24)]
    d={'rows':rows,'fields':[{'key':'x','label':'x','kind':'numeric','stage':'process'}],'target':'capacity','group_basis':'synthetic','source':'synthetic'}
    r=train(d,{'features':['x'],'auto_calibrate':True,'alpha':.1},tmp_path)
    assert r['samples']==15 and r['calibration']['calibration_groups']==9
    p=infer({'mode':'ml_predict','model_path':str(tmp_path/'model.joblib'),'prediction_rows':[{'record_id':'n','batch_id':'A','x':.5}]},tmp_path/'predict')
    assert p['predictions'][0]['interval_lower'] is not None
