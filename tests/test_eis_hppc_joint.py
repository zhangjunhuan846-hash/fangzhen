import numpy as np
import pytest
pytest.importorskip('scipy')
from user_tools.workbench.engineering_eis_hppc_joint import fit_methods,pulse_voltage,eis_impedance

def test_quality_gate_and_shared_synthetic_recovery():
    current=np.r_[np.full(10,3.),np.zeros(90)];truth=[.01,.02,12.,3.7]
    pulse={'current':current,'voltage':pulse_voltage(truth,current),'pre_voltage':3.7}
    f=np.geomspace(.005,1000,40);eis={'frequency_Hz':f,'impedance':eis_impedance(truth,f)}
    with pytest.raises(ValueError,match='质量筛查'):
        fit_methods(pulse,eis,False)
    result=fit_methods(pulse,eis,True)
    for method in ('hppc_only','eis_initial','joint'):
        assert result[method]['fit_success']
        assert result[method]['R0_ohm']==pytest.approx(truth[0],rel=.02)
        assert result[method]['R1_ohm']==pytest.approx(truth[1],rel=.02)
        assert result[method]['tau_s']==pytest.approx(truth[2],rel=.02)
        assert len(result[method]['starts'])==3
