"""Independent physics, causality, source-unit and fail-closed interlock checks."""
import copy
import csv
import io
import math
import numpy as np
import pytest

from user_tools.workbench.engineering_contracts import defaults,normalize
from user_tools.workbench.hardware_readiness import SafetyInterlock
from user_tools.workbench.engineering_eis_audit import parse_digatron,stable_kk_fit


def simple_model():
    return dict(capacity_Ah=2.9,soc_grid=[0.,1.],temperature_nodes_C=[25.],
         tables=[[[3.,4.2]],[[.01,.01]],[[.02,.02]],[[1000.,1000.]]],
         thermal_capacity_J_K=60.,heat_transfer_W_K=.1,aging_scales=[1.,1.,1.],dynamic_case_temperature=False)


def stream():
    t=np.arange(0.,121.,2.);i=np.ones(len(t));temp=np.full(len(t),25.)
    return dict(t=t,current=i,temp=temp,ambient=temp.copy(),v=np.full(len(t),4.1),cumulative_charge_As=t)


def test_minimal_public_contracts():
    for action in ['commercial_adaptive','eis_audit']:
        c=normalize(defaults(action));assert c['data_origin']=='public' and 'cell' not in c
        with pytest.raises(ValueError):normalize({**c,'data_origin':'synthetic'})
        with pytest.raises(ValueError):normalize(c,b'a\n1\n2')
    c=defaults('safety_bench');assert 'cell' not in normalize(c)
    with pytest.raises(ValueError):normalize({**c,'data_origin':'public','source':'anything'})
    c['limits']['current_max_A']=float('inf')
    with pytest.raises(ValueError):normalize(c)


def test_fast_solver_matches_independent_RC_and_thermal_closed_form():
    pytest.importorskip('numba')
    from user_tools.workbench.engineering_adaptive_math import predict_fast
    m=simple_model();s=stream();p=predict_fast(m,s);t=s['t'];a=np.exp(-t/20);b=np.exp(-t/600)
    soc=1-t/(3600*2.9);v=3+1.2*soc-.01-.02*(1-a)
    thermal=25+.03/.1*(1-b)-(.02/60)*(a-b)/(1/600-1/20)
    assert p[:,0]==pytest.approx(v,abs=2e-8)
    assert p[:,1]==pytest.approx(thermal,abs=2e-8)
    assert p[:,2]==pytest.approx(soc,abs=1e-10)


def test_fast_and_thevenin_independent_backends():
    pytest.importorskip('numba');pytest.importorskip('thevenin')
    from user_tools.workbench.engineering_adaptive_math import predict_fast,predict_thevenin
    s=stream();s['current'][10:20]=2.;m=simple_model()
    a=predict_fast(m,s);b=predict_thevenin(m,s)
    assert np.max(abs(a-b))<2e-7


def test_augmented_EKF_causal_and_innovation_precedes_voltage_update():
    pytest.importorskip('numba');pytest.importorskip('sox')
    from user_tools.workbench.engineering_adaptive_math import observe
    s=stream();s['current'][10:20]=2.;a,_=observe(simple_model(),s,.02,1e-6)
    changed=copy.deepcopy(s);changed['v'][30:]-=.4
    b,_=observe(simple_model(),changed,.02,1e-6)
    assert np.array_equal(a[:30],b[:30])
    assert a[0,2]==pytest.approx(3+1.2*.85-.01)
    assert a[0,3]==pytest.approx(s['v'][0]-a[0,2])


def test_missing_ambient_is_explicit_but_missing_voltage_rejected():
    pytest.importorskip('numba');pytest.importorskip('scipy')
    from user_tools.workbench.engineering_adaptive import prepare_stream
    raw=dict(Time=np.array([0.,1.,2.]),Current=np.array([-1.,-1.,-1.]),Voltage=np.ones(3)*4,
        Ah=np.array([0.,-.0003,-.0006]),Battery_Temp_degC=np.ones(3)*.5,Chamber_Temp_degC=np.full(3,np.nan))
    s=prepare_stream(raw,0.);assert s['chamber_missing_fraction']==1. and (s['ambient']==0).all()
    assert 'nominal' in s['ambient_source']
    raw['Voltage'][1]=np.nan
    with pytest.raises(ValueError):prepare_stream(raw,0.)


def test_sparse_rest_logs_do_not_generate_fake_voltage_updates():
    pytest.importorskip('numba');pytest.importorskip('scipy')
    from user_tools.workbench.engineering_adaptive import prepare_stream
    raw=dict(Time=np.array([0.,60.005,120.01]),Current=np.zeros(3),Voltage=np.array([4.2,4.18,4.17]),Ah=np.zeros(3),
        Battery_Temp_degC=np.array([25.,26.,27.]),Chamber_Temp_degC=np.full(3,np.nan))
    s=prepare_stream(raw,25.)
    assert not s['measurement_mask'][10] and s['measurement_mask'][60]
    assert int(s['measurement_mask'].sum())<=4
    assert s['sensor_temp_C'][10]==25. and s['sensor_temp_C'][61]==26.


def test_calibration_never_decodes_fresh_holdout_records(tmp_path,monkeypatch):
    pytest.importorskip('numba');pytest.importorskip('sox')
    import user_tools.workbench.engineering_adaptive as module
    if not (module.TEMP_DATA/'download_manifest.json').exists():pytest.skip('Public calibration data not installed')
    original=module.load_measurement;calls=[]
    def guarded(path):
        name=path.name
        assert any(part in name for part in ['HPPC','Cycle_1_','Dis1C_1.mat','Dis1C_Rp.mat']),name
        calls.append(name);return original(path)
    monkeypatch.setattr(module,'load_measurement',guarded)
    result=module.select_and_freeze(tmp_path)
    assert len(calls)==7 and result['fresh_holdout_signals_decoded_during_calibration'] is False


def test_adaptive_bridge_uses_parent_cell_and_rejects_changed_model():
    import hashlib
    from user_tools.workbench.engineering_service import bridge_adaptive_control
    exported={'action':'mpc','cell':{'capacity_Ah':2.5},'source':'public'};artifact=b'frozen model'
    parent={'action':'commercial_adaptive','frozen_model_sha256':hashlib.sha256(artifact).hexdigest()}
    result=bridge_adaptive_control({'action':'mpc','cell':{'capacity_Ah':999},'target_soc':.8},parent,'parent',artifact,exported)
    assert result['cell']['capacity_Ah']==2.5 and result['target_soc']==.8
    assert 'adaptive_parameter_source' in result and 'adaptive_parameter_source' not in exported
    with pytest.raises(ValueError):bridge_adaptive_control({'action':'mpc'},parent,'parent',b'changed',exported)


def test_MPC_SOC_table_requires_verified_parent_and_runs_plant_mismatch(tmp_path):
    pytest.importorskip('do_mpc');pytest.importorskip('thevenin');pytest.importorskip('sox')
    from user_tools.workbench.engineering_control import run_control
    c=defaults('mpc');c['steps']=5;cell=c['cell']
    cell['rc_table']=[dict(soc=s,temperature_C=t,R0_ohm=.01+.01*s,R1_ohm=.025,C1_F=1500.) for s in [0.,1.] for t in [0.,60.]]
    with pytest.raises(ValueError,match='参数表'):run_control(c,tmp_path)
    c['adaptive_parameter_source']={'job_id':'verified-unit-parent','frozen_model_sha256':'a'*64,'table_replay_source_verified':True}
    result=run_control(c,tmp_path)
    assert result['metrics']['plant_violation_count']==0 and 'SOC-table plant' in result['controller_model_scope']


def test_unit_inference_checks_redundant_amplitude_and_phase():
    text=io.StringIO();fields=['Time Stamp','ActFreq','Zreal1','Zimg1','Betrag','Phase','AAmplitude','VRelativ','mvIdeal','U1']
    w=csv.DictWriter(text,fieldnames=fields,delimiter=';');w.writeheader()
    for f in np.geomspace(.01,100,12):
        z=.02+.01/(1+2j*np.pi*f*.1);w.writerow({'Time Stamp':'fixed','ActFreq':f,'Zreal1':z.real*1000,'Zimg1':z.imag*1000,
            'Betrag':abs(z)*1000,'Phase':np.degrees(np.angle(z)),'AAmplitude':.01/abs(z),'VRelativ':1.,'mvIdeal':10.,'U1':3.8})
    f,z,audit=parse_digatron(text.getvalue().encode());assert audit['unit_consistency_pass']
    assert z.real.min()<.03 and audit['amplitude_ratio_relative_max']<1e-12


def test_independent_SVD_recovers_exact_RC_inductor_and_series_capacitor():
    f=np.geomspace(.01,100,61);tau=np.geomspace(1/(2*np.pi*100),1/(2*np.pi*.01),9)[4]
    z=.02+.03/(1+2j*np.pi*f*tau)+1j*2*np.pi*f*1e-6+1/(2j*np.pi*f*2000.)
    fitted,info=stable_kk_fit(f,z,9,True)
    assert max(abs(fitted-z))<1e-12 and info['rank']==info['columns']


@pytest.mark.parametrize('fault',[{'voltage_V':4.21},{'temperature_C':46.},{'measurement_time_s':.2},{'current_A':3.}, {'device_fault':True}])
def test_interlock_latches_stop_and_never_sends_physical_command(fault):
    gate=SafetyInterlock(defaults('safety_bench')['limits'])
    frame=dict(sequence=1,measurement_time_s=0.,voltage_V=3.8,temperature_C=25.,current_A=-1.)
    result=gate.step({**frame,**fault},0.,1.)
    assert result['stop_latched'] and result['command_charge_A']==0. and not result['physical_command_sent']
    assert gate.step({**frame,'sequence':2,'measurement_time_s':.1},.1,1.)['command_charge_A']==0.


def test_interlock_invalid_clock_missing_measurement_and_repeated_sequence():
    frame=dict(sequence=1,measurement_time_s=0.,voltage_V=3.8,temperature_C=25.,current_A=-1.)
    for now in [float('nan'),'unknown']:
        assert SafetyInterlock(defaults('safety_bench')['limits']).step(frame,now,1.)['command_charge_A']==0.
    gate=SafetyInterlock(defaults('safety_bench')['limits']);assert gate.step(frame,0.,1.)['command_charge_A']==1.
    assert gate.step(frame,0.,1.)['command_charge_A']==0.
    assert SafetyInterlock(defaults('safety_bench')['limits']).step({},0.,1.)['command_charge_A']==0.
    gate=SafetyInterlock(defaults('safety_bench')['limits']);gate.step(frame,.5,1.)
    assert gate.step({**frame,'sequence':2,'measurement_time_s':.4},.4,1.)['command_charge_A']==0.
