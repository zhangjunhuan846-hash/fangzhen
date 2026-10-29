"""Contract, data-integrity and physical independent-oracle tests for new adapters."""
import csv
import io
import json
from pathlib import Path
import numpy as np
import pytest

from user_tools.workbench.engineering_contracts import defaults, normalize
from user_tools.workbench.engineering_frontier import observations
from user_tools.workbench.engineering_commercial import resample, voltage_metrics


def test_three_public_contracts():
    for action in ['batterylife','commercial_validation']:
        c=normalize(defaults(action)); assert c['data_origin']=='public'
        with pytest.raises(ValueError): normalize({**c,'data_origin':'synthetic'})
        with pytest.raises(ValueError): normalize(c,b'time_s,current_A\n0,0\n1,1')
    assert normalize(defaults('frontier'))['algorithm']=='mobo_osd'


def test_future_labels_blocked_and_pending_excluded():
    c=defaults('frontier'); rows,*_=observations(c,None)
    def raw():
        text=io.StringIO();w=csv.DictWriter(text,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows);return text.getvalue().encode()
    rows[-1]['status']='pending'
    _,_,_,_,_,done,pool=observations(c,raw());assert len(done)==18 and len(pool)==13
    rows[-1]['objective1']=999
    with pytest.raises(ValueError,match='未来标签'): observations(c,raw())


def test_interval_current_preserves_raw_charge_not_resetting_counter():
    pytest.importorskip('scipy')
    x={'Time':np.array([0.,.5,1.,2.5]),'Current':np.array([-2.,-2.,-2.,-2.]),
       'Ah':np.array([0.,-.001,10.,9.999]),'Voltage':np.ones(4)*4,
       'Battery_Temp_degC':np.ones(4)*25,'Chamber_Temp_degC':np.ones(4)*25}
    s=resample(x)
    assert np.dot(s['current'][1:],np.diff(s['t']))==pytest.approx(5.)
    assert s['current'][1:]==pytest.approx(np.full(len(s['t'])-1,2.))


def test_physics_error_metrics_independent_oracle():
    s={'v':np.array([3.,4.]),'temp':np.array([25.,26.])}
    m=voltage_metrics((np.array([3.003,3.996]),np.array([26.,25.]),np.array([1.,.9])),s)
    assert m['voltage_rmse_mV']==pytest.approx((12.5)**.5)
    assert m['temperature_rmse_C']==pytest.approx(1.)


def test_architecture_whitelist_and_finite_limits():
    with pytest.raises(ValueError):normalize({**defaults('frontier'),'algorithm':'external_command'})
    with pytest.raises(ValueError):normalize({**defaults('batterylife'),'architecture':'../x'})
    with pytest.raises(ValueError):normalize({**defaults('frontier'),'train_iterations':float('nan')})
