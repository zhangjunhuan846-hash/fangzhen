import copy
import pytest
from user_tools.validate_joint_cycler_diagnosis import synthetic
from user_tools.workbench.joint_cycler_diagnosis import diagnose

@pytest.mark.parametrize('scenario',['clean','milliseconds','minutes','sign_flip','milliseconds_sign_flip','step_reset','combined_reset'])
def test_identifiable_cases(scenario):
    rows,truth=synthetic(23,scenario);before=copy.deepcopy(rows)
    r=diagnose(rows)
    assert r['auto_applicable']
    assert r['proposed_time_factor']==truth['time_factor']
    assert r['proposed_current_sign']==truth['current_sign']
    assert bool(r['counter_reset_events'])==truth['reset']
    assert rows==before

@pytest.mark.parametrize('scenario',['missing_evidence','clock_charge_conflict','time_rollback'])
def test_unsafe_cases_refused(scenario):
    rows,_=synthetic(23,scenario)
    assert not diagnose(rows)['auto_applicable']

def test_no_direction_cannot_invent_sign_from_clock():
    rows,_=synthetic(23,'missing_evidence')
    for r in rows:r['stamp']=r['t']
    d=diagnose(rows)
    assert d['proposed_time_factor']==1 and d['proposed_current_sign'] is None
    assert not d['auto_applicable']

def test_counter_drop_inside_step_is_not_reset_repair():
    rows,_=synthetic(23,'clean');rows[20]['qc']=-.1
    d=diagnose(rows)
    assert d['counter_anomalies'] and not d['auto_applicable']

def test_nonfinite_required_input_rejected():
    rows,_=synthetic(23,'clean');rows[4]['i']=float('nan')
    with pytest.raises(ValueError):diagnose(rows)
