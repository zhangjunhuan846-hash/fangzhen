import copy
import pytest
from user_tools.validate_joint_cycler_diagnosis_v2 import fixture
from user_tools.workbench.joint_cycler_diagnosis_v2 import diagnose_v2, PrecisionBudget

@pytest.mark.parametrize('scenario',['clean','milliseconds','minutes','sign_flip','milliseconds_sign_flip','step_reset','combined_reset',
 'coarse_low_current','coarse_combined_reset','exact_duplicate','precision_limited'])
def test_correct_advice(scenario):
    rows,budget,truth=fixture(31,scenario);before=copy.deepcopy(rows)
    r=diagnose_v2(rows,budget)
    assert r['auto_applicable'],r
    assert r['proposed_time_factor']==truth['time_factor'] and r['proposed_current_sign']==truth['current_sign']
    assert rows==before
    if scenario=='precision_limited':assert r['charge_status']=='precision_limited_or_unresolved'

@pytest.mark.parametrize('scenario',['missing_evidence','clock_charge_conflict','time_rollback',
 'coarse_wrong_capacity_scale','coarse_missing_reference','same_time_changed_voltage'])
def test_blocked_advice(scenario):
    rows,budget,_=fixture(31,scenario)
    assert not diagnose_v2(rows,budget)['auto_applicable']

def test_missing_precision_not_invented():
    rows,_,_=fixture(31,'clean')
    assert diagnose_v2(rows)['status']=='precision_budget_required'

def test_bounds_do_not_shrink_with_number_of_points():
    rows,budget,_=fixture(31,'coarse_low_current');r=diagnose_v2(rows,budget)
    assert r['windows']
    assert all(w['counter_error_Ah']==pytest.approx(.0004) for w in r['windows'])

def test_signature_includes_original_voltage():
    rows,budget,_=fixture(31,'same_time_changed_voltage')
    for k,row in enumerate(rows):row['source_signature']=str(k)
    r=diagnose_v2(rows,budget)
    assert not r['removed_exact_duplicate_rows'] and not r['auto_applicable']

def test_invalid_budget_rejected():
    with pytest.raises(ValueError):PrecisionBudget(-1,0,0,0,0,'bad').validate()

def test_integral_bound_contains_independent_endpoint_interval_arithmetic():
    rows,budget,_=fixture(31,'coarse_low_current');r=diagnose_v2(rows,budget)
    for w in r['windows']:
        lower=upper=0.
        # Separate interval-product calculation, not the estimator's error formula.
        for a,b in zip(rows[w['start_row']:w['end_row']],rows[w['start_row']+1:w['end_row']+1]):
            ea=budget.current_abs_A+budget.current_relative*abs(a['i'])
            eb=budget.current_abs_A+budget.current_relative*abs(b['i'])
            il=(a['i']-ea+b['i']-eb)/2;ih=(a['i']+ea+b['i']+eb)/2
            dt=b['t']-a['t'];tl=dt-2*budget.time_abs_raw;th=dt+2*budget.time_abs_raw
            products=[il*tl,il*th,ih*tl,ih*th]
            lower+=min(products)/3600;upper+=max(products)/3600
        assert w['raw_integral_Ah']-w['raw_integral_error_Ah']<=lower+1e-12
        assert w['raw_integral_Ah']+w['raw_integral_error_Ah']>=upper-1e-12

def test_public_signature_preserves_empty_trailing_columns_and_voltage(tmp_path):
    from user_tools.validate_joint_cycler_diagnosis_v2 import public_input
    p=tmp_path/'example.csv'
    p.write_text('test_time_s,current_A,charge_capacity_Ah,discharge_capacity_Ah,date_time_iso_string,step_index,cycle_index,step_name,voltage_V\n'
        '1,0.0002,0.0001,0.0000,2024-01-01 00:00:01,1,1,charge,3.7,\n'
        '1,0.0002,0.0001,0.0000,2024-01-01 00:00:01,1,1,charge,3.8,\n',encoding='utf-8')
    rows,budget,_=public_input(p)
    assert rows[0]['source_signature']!=rows[1]['source_signature']
    out=diagnose_v2(rows,budget)
    assert not out['removed_exact_duplicate_rows'] and out['time_rollbacks']==[1]
