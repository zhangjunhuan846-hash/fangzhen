import csv
import io
import json
import hashlib
import numpy as np
import pytest

pytest.importorskip('scipy')
pytest.importorskip('impedance')
from user_tools.workbench.engineering_eis_grid import run_grid
from user_tools.workbench.engineering_contracts import defaults
from user_tools.workbench.engineering_service import bridge_eis_grid


def test_kk_diagnostics_distinguish_order_limit_from_residual(monkeypatch):
    import impedance.validation as validation
    from user_tools.workbench import engineering_eis_audit as audit
    f=np.geomspace(.1,1000,16);z=np.full(len(f),.02+0j)
    monkeypatch.setattr(audit,'stable_kk_fit',lambda f,z,order,add_cap: (z,{'rank':3,'columns':3,'scaled_condition_number':1.}))
    monkeypatch.setattr(validation,'linKK',lambda *a,**k:(8,1.,z,np.zeros(len(f)),np.zeros(len(f))))
    _,r=audit.lin_kk(f,z,True)
    assert not r['screening_pass']
    assert r['screening_failures']==['mu_cutoff_not_reached_at_max_M']
    monkeypatch.setattr(validation,'linKK',lambda *a,**k:(3,.5,z,np.full(len(f),.03),np.zeros(len(f))))
    _,r=audit.lin_kk(f,z,True)
    assert r['screening_failures']==['relative_rms_above_threshold']


def synthetic_grid():
    out=io.StringIO(newline='');w=csv.writer(out)
    w.writerow(['cell_id','spectrum_id','role','soc','temperature_C','frequency_Hz','Z_real_ohm','Z_imag_ohm'])
    for soc,role in [(.2,'train'),(.8,'train'),(.5,'test')]:
        r=.02+.01*soc
        for f in np.geomspace(.5,1400,28):
            z=.012+r/(1+2j*np.pi*f*r*1500)
            w.writerow(['synthetic-5Ah-1RC',f's{soc}',role,soc,25,f,z.real,z.imag])
    return out.getvalue().encode()


def test_grid_holdout_and_bms_bridge(tmp_path):
    config=defaults('eis_grid');result=run_grid(config,tmp_path,synthetic_grid())
    assert result['grid_usable_for_replay'],result['spectra_summary']
    held=next(x for x in result['spectra_summary'] if x['role']=='test')
    assert held['relative_rms']<1e-4
    assert held['kk_diagnostics']['fit_type']=='complex'
    assert held['kk_diagnostics']['screening_pass'] == held['kk_pass']
    assert 'screening_failures' in held['kk_diagnostics']
    cfg=defaults('ecm_bms');cfg['cell']['isothermal']=True;cfg['cell']['initial_soc']=.5;cfg['same_cell_eis_confirmed']=True
    artifact=(tmp_path/'rc_grid.json').read_bytes()
    bridged=bridge_eis_grid(cfg,result,'parent',artifact)
    assert len(bridged['cell']['rc_table'])==2
    assert bridged['cell']['R_ohm'][0]==pytest.approx(.025,rel=1e-3)
    pytest.importorskip('thevenin');pytest.importorskip('sox')
    from user_tools.workbench.engineering_bms import run_bms
    bridged['steps']=5
    replay=run_bms(bridged,tmp_path/'bms')
    assert replay['eis_grid_source']['job_id']=='parent' and replay['points']==6
    with pytest.raises(ValueError,match='校验'):bridge_eis_grid(cfg,result,'parent',artifact+b' ')
    cfg['cell']['cell_id']='other'
    with pytest.raises(ValueError,match='电芯编号'):bridge_eis_grid(cfg,result,'parent',artifact)


def test_holdout_outside_grid_cannot_bridge(tmp_path):
    raw=synthetic_grid().replace(b's0.5,test,0.5,25',b's0.9,test,0.9,25')
    result=run_grid(defaults('eis_grid'),tmp_path,raw)
    assert not result['grid_usable_for_replay']
    assert any(x['status']=='outside_grid' for x in result['spectra_summary'])
    cfg=defaults('ecm_bms');cfg['same_cell_eis_confirmed']=True
    with pytest.raises(ValueError,match='未通过'):bridge_eis_grid(cfg,result,'parent',(tmp_path/'rc_grid.json').read_bytes())


def test_2rc_curves_preserve_both_branches(tmp_path):
    out=io.StringIO(newline='');w=csv.writer(out)
    w.writerow(['cell_id','spectrum_id','role','soc','temperature_C','frequency_Hz','Z_real_ohm','Z_imag_ohm'])
    for soc,role in [(.2,'train'),(.8,'train'),(.5,'test')]:
        for f in np.geomspace(.5,1400,28):
            z=.012+.015/(1+2j*np.pi*f*.015*50)+(.03+.005*soc)/(1+2j*np.pi*f*(.03+.005*soc)*2500)
            w.writerow(['synthetic-5Ah-1RC',f's{soc}',role,soc,25,f,z.real,z.imag])
    config=defaults('eis_grid');config['rc_branches']=2
    result=run_grid(config,tmp_path,out.getvalue().encode())
    assert len(result['parameters'])==2 and all('R2_ohm' in r and 'C2_F' in r for r in result['parameters'])
    assert all(r['R1_ohm']*r['C1_F']<=r['R2_ohm']*r['C2_F'] for r in result['parameters'])
    assert next(x for x in result['spectra_summary'] if x['role']=='test')['relative_rms']<.02


def test_duplicate_train_as_test_spectrum_is_rejected(tmp_path):
    rows=list(csv.DictReader(io.StringIO(synthetic_grid().decode())))
    original=[r for r in rows if r['role']=='train' and r['soc']=='0.2']
    for row in rows:
        if row['role']=='test':
            source=original.pop(0);row['Z_real_ohm']=source['Z_real_ohm'];row['Z_imag_ohm']=source['Z_imag_ohm']
    out=io.StringIO(newline='');w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    with pytest.raises(ValueError,match='内容完全相同'):run_grid(defaults('eis_grid'),tmp_path,out.getvalue().encode())


def test_filter_estimated_grid_uses_estimate_and_refuses_extrapolation(tmp_path):
    pytest.importorskip('thevenin');pytest.importorskip('sox')
    from user_tools.workbench.engineering_bms import run_bms, estimate_stream
    result=run_grid(defaults('eis_grid'),tmp_path/'grid',synthetic_grid())
    cfg=defaults('ecm_bms');cfg['cell']['isothermal']=True;cfg['cell']['initial_soc']=.5
    cfg['same_cell_eis_confirmed']=True;cfg['filter_rc_mode']='estimated_grid';cfg['steps']=5
    bridged=bridge_eis_grid(cfg,result,'parent',(tmp_path/'grid'/'rc_grid.json').read_bytes())
    replay=run_bms(bridged,tmp_path/'bms')
    assert replay['points']==6 and 'estimated SOC' in replay['filter_model']
    # Reference/model SOC are labels, not inputs to the estimated-grid filter.
    rows=[{'time_s':0.,'sensor_current_A':1.,'sensor_voltage_V':3.7,'measured_temperature_C':25.,'soc_reference':.3},
          {'time_s':10.,'sensor_current_A':1.,'sensor_voltage_V':3.7,'measured_temperature_C':25.,'soc_reference':.3}]
    a,_=estimate_stream(bridged,rows)
    for row in rows:row['soc_reference']=.75
    b,_=estimate_stream(bridged,rows)
    assert [r['soc_ekf'] for r in a]==pytest.approx([r['soc_ekf'] for r in b])
    # The one-step voltage at an observation does not use that observation.
    later=[dict(row) for row in rows];later[1]['sensor_voltage_V']+=.1
    c,_=estimate_stream(bridged,later)
    assert c[1]['voltage_ekf_prior_V']==pytest.approx(b[1]['voltage_ekf_prior_V'])
    assert c[1]['voltage_ukf_prior_V']==pytest.approx(b[1]['voltage_ukf_prior_V'])
    bridged['filter_rc_mode']='estimated_grid_jacobian'
    jac,metrics=estimate_stream(bridged,rows)
    assert np.isfinite(metrics['ekf_prior_voltage_rmse_V'])
    assert np.isfinite(jac[-1]['soc_ekf'])
    rows[0]['measured_temperature_C']=26.
    with pytest.raises(ValueError,match='输入温度不一致'):estimate_stream(bridged,rows)
    rows[0]['measured_temperature_C']=25.
    bridged['cell']['estimated_initial_soc']=.1
    with pytest.raises(ValueError,match='不支持外推'):estimate_stream(bridged,rows)


def test_log_inverse_temperature_interpolation_is_shared_with_bms():
    from user_tools.workbench.engineering_rc_grid import make_rc_interpolator
    from user_tools.workbench.engineering_bms import plant_parameters
    table=[]
    for soc in (.2,.8):
        for temp in (5.,40.):
            table.append({'soc':soc,'temperature_C':temp,'R0_ohm':.01*(2 if temp==5 else 1),
                          'R1_ohm':.02*(2 if soc==.8 else 1),'C1_F':1000.})
    lookup=make_rc_interpolator(table,1,'log_invT')
    actual=lookup(.5,25.)
    w=(1/(25+273.15)-1/(5+273.15))/(1/(40+273.15)-1/(5+273.15))
    assert actual['R0_ohm']==pytest.approx(.02**(1-w)*.01**w)
    assert actual['R1_ohm']==pytest.approx(np.sqrt(.02*.04))
    cell=defaults('ecm_bms')['cell'];cell.update(rc_table=table,rc_interpolation='log_invT')
    params=plant_parameters(cell)
    assert params['R0'](.5,25+273.15)==pytest.approx(actual['R0_ohm'])
    assert params['R1'](.5,25+273.15)==pytest.approx(actual['R1_ohm'])
    with pytest.raises(ValueError,match='不支持外推'):lookup(.5,41.)


def test_filter_can_use_bounded_temperature_ocv():
    pytest.importorskip('sox')
    from user_tools.workbench.engineering_bms import estimate_stream
    cfg=defaults('ecm_bms');cfg['filter_ocv_mode']='soc_temperature'
    cfg['cell']['estimated_initial_soc']=.5
    cfg['cell']['ocv_temperature_table']=[{'soc':s,'temperature_C':t,'ocv_V':3+s+.001*t} for s in (0.,1.) for t in (10.,40.)]
    row={'time_s':0.,'sensor_current_A':0.,'sensor_voltage_V':3.525,'measured_temperature_C':25.,'soc_reference':.5}
    out,_=estimate_stream(cfg,[row])
    assert out[0]['voltage_ekf_prior_V']==pytest.approx(3.525)
    row['measured_temperature_C']=50.
    with pytest.raises(ValueError,match='不支持外推'):estimate_stream(cfg,[row])


def test_soc_projection_is_explicit_and_counted():
    pytest.importorskip('sox')
    from user_tools.workbench.engineering_bms import estimate_stream
    cfg=defaults('ecm_bms');cfg.update(enable_ukf=False,soc_constraint='project',filter_ocv_mode='soc_temperature')
    cfg['cell']['estimated_initial_soc']=.5
    cfg['cell']['ocv_temperature_table']=[{'soc':s,'temperature_C':t,'ocv_V':3+s} for s in (0.,1.) for t in (10.,40.)]
    rows=[{'time_s':0.,'sensor_current_A':0.,'sensor_voltage_V':5.,'measured_temperature_C':25.,'soc_reference':.5}]
    output,metrics=estimate_stream(cfg,rows)
    assert output[0]['soc_ukf'] is None
    assert output[0]['soc_ekf']<=1 and output[0]['soc_ekf_projected']
    assert metrics['soc_projection_steps']==1
    cfg['enable_ukf']=True
    with pytest.raises(ValueError,match='SOC投影'):estimate_stream(cfg,rows)
