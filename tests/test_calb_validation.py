"""Focused contracts for the matched-data BMS validation path."""
import pytest

from user_tools.workbench.engineering_contracts import defaults, normalize


def test_calb_fixed_public_source_and_process_noise_contract():
    cfg=defaults('calb_validation')
    assert normalize(cfg)['data_origin']=='public'
    cfg['source']='https://example.com/other'
    with pytest.raises(ValueError,match='source'):normalize(cfg)
    cfg=defaults('ecm_bms');cfg['soc_process_variance_per_step']=-1
    with pytest.raises(ValueError,match='soc_process_variance_per_step'):normalize(cfg)


def test_open_loop_rc_matches_analytic_signal_without_sensor_feedback():
    np=pytest.importorskip('numpy');pytest.importorskip('scipy')
    from user_tools.workbench.engineering_calb_validation_v2 import open_loop
    cell=defaults('ecm_bms')['cell']
    cell['rc_table']=[{'soc':soc,'temperature_C':25.,'R0_ohm':.012,'R1_ohm':.025,'C1_F':1500.} for soc in (.2,.8)]
    current=np.ones(16);soc=.56;eta=0.;expected=[]
    from user_tools.workbench.engineering_bms import ocv_function
    ocv=ocv_function(cell)
    for i in range(len(current)):
        if i:
            decay=np.exp(-1/(.025*1500.));eta=decay*eta+.025*(1-decay)
            soc-=1/(3600*cell['capacity_Ah'])
        expected.append(ocv(soc)-eta-.012)
    window={'soc_proxy':np.full(len(current),.6),'current':current,'voltage':np.array(expected)}
    assert open_loop(cell,25.,window,'fixed_start')==pytest.approx(0.,abs=1e-10)
    assert open_loop(cell,25.,window,'estimated_grid')==pytest.approx(0.,abs=1e-10)
