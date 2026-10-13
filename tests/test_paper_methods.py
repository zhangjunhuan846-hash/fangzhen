import csv
import io
import math
import numpy as np
import pytest
from user_tools.rg_loop.optimization import GaussianProcess,_matern
from user_tools.workbench.candidate_multi import finite_nehvi
from user_tools.workbench.paper_methods import read_eis,split_conformal
from user_tools.workbench.eis_worker import gaussian_information


def gp_fixture():return GaussianProcess().fit(np.array([[0.,0.],[1.,0.],[0.,1.]]),np.array([1.,2.,1.5]),.2)


def test_joint_latent_covariance_matches_gaussian_conditioning():
    gp=gp_fixture();x=np.array([[.2,.3],[.5,.8]])
    mean,cov=gp.joint_posterior(x)
    k=_matern(gp.x,gp.x,gp.length,gp.amplitude)+np.eye(3)*(gp.noise**2+1e-8)
    cross=_matern(gp.x,x,gp.length,gp.amplitude)
    expected=gp.scale**2*(_matern(x,x,gp.length,gp.amplitude)-cross.T@np.linalg.solve(k,cross))
    assert cov==pytest.approx(expected,rel=1e-10,abs=1e-10)
    _,std=gp.predict(x);assert np.diag(cov)==pytest.approx(std**2)


def test_same_location_latent_nehvi_gain_exactly_zero():
    gp=gp_fixture();train=gp.x;xs=train[:1]
    ice=GaussianProcess().fit(train,np.array([.85,.9,.95]),.01)
    gains,stderr,feasible=finite_nehvi([gp,ice],train,xs,[0,0],[0,0],128,42)
    # Same point's latent draw must be the SAME random variable, not independent.
    assert gains[0]==0 and stderr[0]==0
    assert feasible[0]>.99
    samples=gp.joint_samples(np.vstack([xs,xs]),200,42)
    assert np.array_equal(samples[:,0],samples[:,1])


def test_linear_gaussian_eig_baseline_and_noise():
    assert gaussian_information([[1]],[[4]],[[1]])==pytest.approx(.5*math.log(5))
    assert gaussian_information([[0]],[[4]],[[1]])==0
    assert gaussian_information([[1]],[[4]],[[4]])<gaussian_information([[1]],[[4]],[[1]])
    # Correlated observations must not be counted as independent replicates.
    a=[[1],[1]];independent=np.eye(2);correlated=np.array([[1,.9],[.9,1]])
    assert gaussian_information(a,[[4]],correlated)<gaussian_information(a,[[4]],independent)


def calibration_csv(n,duplicate=False,batch='A'):
    rows=[['record_id','group_id','batch_id','protocol_id','role','predicted','observed']]
    rows+=[[f'c{i}',f'g{i}',batch,'1C','calibration','100',str(100+i)] for i in range(n)]
    rows.append(['test','g0' if duplicate else 'test-group','A','1C','test','100','105'])
    handle=io.StringIO();csv.writer(handle).writerows(rows);return handle.getvalue().encode()


def test_conformal_finite_order_statistic_and_unbounded_small_n():
    cfg={'frozen_independent_model':True,'alpha':.1}
    r=split_conformal(calibration_csv(9),cfg)
    assert r['finite_sample_rank']==9 and r['residual_threshold']==8
    assert r['tests'][0]['lower']==92 and r['empirical_test_coverage']==1
    r=split_conformal(calibration_csv(18),dict(cfg,alpha=.05))
    assert not r['finite_interval'] and r['residual_threshold'] is None and r['tests'][0]['lower'] is None


def test_calibration_rejects_overlap_and_batch_shift():
    cfg={'frozen_independent_model':True}
    with pytest.raises(ValueError):split_conformal(calibration_csv(9,duplicate=True),cfg)
    with pytest.raises(ValueError):split_conformal(calibration_csv(9,batch='B'),cfg)
    with pytest.raises(ValueError):split_conformal(calibration_csv(9),{})


def test_eis_units_and_imag_sign_against_analytic_rc():
    raw=b'frequency,Zreal,-Im(Z)/Ohm\n6.283185307179586,100,10\n62.83185307179586,50,5\n'
    r=read_eis(raw,{'frequency_unit':'rad/s','impedance_unit':'mohm'})
    point=r['eis_spectra'][0]['points'][0]
    assert point['frequency_Hz']==pytest.approx(10)
    assert point['Z_real_ohm']==.05 and point['Z_imag_ohm']==-.005
    assert point['phase_deg']<0 and not r['linearity_assessed']


def test_eis_native_reference_models(tmp_path):
    from user_tools.workbench.eis_worker import public_eis
    for ps in ['Chen2020','Ecker2015_graphite_halfcell']:
        r=public_eis({'model':'SPM','parameter_set':ps,'socs':[.5],'frequency_min_Hz':1,'frequency_max_Hz':1000,'frequency_points':5},tmp_path/ps)
        assert len(r['eis_spectra'][0]['points'])==5 and not r['independent_validation_passed']


def test_parquet_recording_is_not_impedance_and_preserves_segments(tmp_path):
    import pandas as pd
    from user_tools.workbench.eis_worker import parquet_recording
    source=tmp_path/'source.parquet'
    pd.DataFrame({'timepoints [s]':[0,1,0,2],'voltages [V]':[.1,.2,.3,float('nan')],
                  'currents [A]':[0,.001,.001,.001],'Command':['Rest','Pulse','Pulse','EIS']}).to_parquet(source)
    result,curves=parquet_recording({'source_path':str(source)},tmp_path/'out')
    assert result['valid_rows']==3 and result['segments']==2 and result['issue_count']==2
    assert not result['qc_pass'] and not result['eis_extracted'] and curves
    assert (tmp_path/'out/normalized.csv').exists()


def test_frequency_matrix_matches_analytic_rc_and_time_domain():
    from user_tools.workbench.eis_worker import linear_impedance
    from scipy.integrate import solve_ivp
    frequencies=np.array([.01,1,100])
    z=linear_impedance([[1000]],[[-1/.04]],[1],[1],.01,frequencies)
    expected=.01+.04/(1+1j*2*np.pi*frequencies*.04*1000)
    assert z==pytest.approx(expected,rel=1e-7,abs=1e-10)
    omega=2*np.pi*.01;t=np.linspace(800,1000,10001)
    solution=solve_ivp(lambda time,y:[(-y[0]/.04+np.cos(omega*time))/1000],[0,1000],[0],t_eval=t,rtol=1e-10,atol=1e-12)
    voltage=.01*np.cos(omega*t)+solution.y[0]
    time_domain=2/(t[-1]-t[0])*np.trapezoid(voltage*np.exp(-1j*omega*t),t)
    assert time_domain==pytest.approx(z[0],rel=1e-5,abs=1e-8)
