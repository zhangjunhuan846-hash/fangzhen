import csv
import io
from pathlib import Path
import numpy as np
import pytest

pytest.importorskip('sklearn')
from user_tools.workbench.hardcarbon_joint import train,recommend,ax_mobo


def test_joint_uses_same_holdout_and_suspends_when_baseline_wins(tmp_path):
    header='doi,mapping_found,ice,reversible_capacity_mAh_g,carbonization_temperature_C,d002_nm,id_ig,ssa_m2_g,electrolyte_type,current_density_mA_g\n'
    raw=(header+''.join(f'paper{i//2},True,{.7+i*.005},{200+i},900,0.38,1.1,10,1,20\n' for i in range(20))).encode()
    result=train(raw,{'algorithms':['mean']},tmp_path)
    ice=result['targets']['ice'];capacity=result['targets']['capacity_mAh_g']
    assert ice['holdout_group_ids']==capacity['holdout_group_ids']
    assert result['holdout_beats_mean_by_5_percent']=={'ice':False,'capacity_mAh_g':False}
    candidate=b'record_id,carbonization_temperature_C,d002_nm,id_ig,ssa_m2_g,electrolyte_type,current_density_mA_g\na,900,0.38,1.1,10,1,20\n'
    # CSV reader requires at least two candidates.
    candidate+=b'b,900,0.38,1.1,10,1,20\n'
    prediction=recommend(candidate,{},tmp_path/'trained_model.joblib',result['model_sha256'])
    assert not prediction['pareto_enabled'] and not any(x['pareto'] for x in prediction['predictions'])
    exploratory=recommend(candidate,{'allow_exploratory':True},tmp_path/'trained_model.joblib',result['model_sha256'])
    assert exploratory['pareto_enabled'] and any(x['pareto'] for x in exploratory['predictions'])
    with pytest.raises(ValueError,match='校验'):recommend(candidate,{},tmp_path/'trained_model.joblib','wrong')


def test_dfn_rejects_same_curve_in_both_roles(tmp_path):
    pytest.importorskip('pybamm')
    from user_tools.workbench.sodium_identification import run
    raw=b'curve_id,role,time_s,voltage_V,c_rate,temperature_C\na,train,0,3.8,1,25\na,test,10,3.7,1,25\n'
    with pytest.raises(ValueError,match='同曲线'):run(raw,{},tmp_path)


def test_process_precursor_accepts_preparation_only_data(tmp_path):
    header='doi,mapping_found,ice,reversible_capacity_mAh_g,carbonization_temperature_C,carbonization_time_h,heating_rate_C_min,current_density_mA_g,precursor_type,electrolyte_type\n'
    raw=(header+''.join(f'paper{i//2},True,{.7+i*.005},{200+i},900,2,3,20,biomass,salt\n' for i in range(20))).encode()
    result=train(raw,{'feature_mode':'process_precursor','algorithms':['mean']},tmp_path)
    assert 'precursor_type' in result['features'] and result['eligible_records']==20


def test_ax_mobo_uses_paired_observed_values():
    pytest.importorskip('ax')
    header='doi,mapping_found,ice,reversible_capacity_mAh_g,carbonization_temperature_C,carbonization_time_h,heating_rate_C_min,current_density_mA_g\n'
    raw=(header+''.join(f'paper{i},True,{.7+i*.01},{200+i*5},{800+i*20},2,3,20\n' for i in range(8))).encode()
    result=ax_mobo(raw,{'parameters':[{'name':'carbonization_temperature_C','bounds':[700,1200]}],
                        'thresholds':{'ice':.5,'capacity_mAh_g':150}})
    assert result['generator']=='BoTorch' and result['completed_rows']==8
    assert 700<=result['candidate']['carbonization_temperature_C']<=1200


def test_dfn_synthetic_parameter_recovery(tmp_path):
    pytest.importorskip('pybamm')
    from user_tools.workbench.sodium_identification import run,simulate
    stream=io.StringIO(newline='');w=csv.writer(stream);w.writerow(['curve_id','role','time_s','voltage_V','c_rate','temperature_C'])
    times=np.linspace(0,200,8)
    for name,role,rate in [('train','train',.8),('test','test',1.)]:
        voltages=simulate(rate,25,times,2.,.03)
        for t,v in zip(times,voltages):w.writerow([name,role,t,v,rate,25])
    result=run(stream.getvalue().encode(),{'max_nfev':15},tmp_path)
    assert result['solver_success']
    assert result['negative_diffusivity_scale']==pytest.approx(2.,rel=.04)
    assert result['effective_drop_V_per_C']==pytest.approx(.03,abs=.002)
    test=next(c for c in result['curves'] if c['role']=='test')
    assert test['fitted_rmse_V'] < test['baseline_rmse_V']*.01
