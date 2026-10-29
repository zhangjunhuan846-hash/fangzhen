import numpy as np
import pandas as pd
import pytest
pytest.importorskip('scipy')
from user_tools.workbench.engineering_stanford_frozen import replay_frozen,time_metrics

def test_open_loop_ignores_measured_voltage_and_uses_discharge_sign():
    model={'capacity_Ah':5.,'ocv_points':[{'soc':0.,'voltage_V':3.},{'soc':1.,'voltage_V':4.}],
           'rc_nodes':[{'soc':0.,'R0_ohm':.01,'R1_ohm':.02,'tau_s':10.},
                       {'soc':1.,'R0_ohm':.01,'R1_ohm':.02,'tau_s':10.}]}
    frame=pd.DataFrame({'time_s':[0.,1.,2.],'current_A':[0.,-1.,-1.],'step':[4,13,14],
                        'cycle':[1,1,1],'voltage_V':[4.,3.9,3.9],'surface_C':[23.,23.,23.]})
    result=replay_frozen(model,frame);changed=frame.copy();changed.voltage_V=[1.,2.,3.]
    other=replay_frozen(model,changed)
    assert np.allclose(result.model_V,other.model_V)
    assert result.current_discharge_A.iloc[1]==1.
    assert result.soc_proxy.iloc[-1]<1.
    metrics=time_metrics(result)
    assert metrics['rmse_mV']**2 == pytest.approx(metrics['bias_mV']**2+metrics['centered_rmse_mV']**2)
