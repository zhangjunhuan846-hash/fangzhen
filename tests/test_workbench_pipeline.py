import base64
import csv
import io
import json
from pathlib import Path
import pytest
from user_tools.workbench.preprocess import normalize_csv
from user_tools.workbench.sample import build_sample
from user_tools.workbench.server import Application


def fixture():
    return {'极片':[{'electrode_id':'E','sample_id':'S','area_cm2':2,'coating_mass_mg':10,'thickness_um':50,
                    'graphite_fraction':.9,'conductive_fraction':.05,'binder_fraction':.05,
                    'conductive_true_density_g_cm3':2,'binder_true_density_g_cm3':1.8}],
            '表征':[{'sample_id':'S','true_density_g_cm3':2.2,'effective_radius_um':5,'radius_basis':'合成测试'}],
            '半电池':[{'cell_id':'C','sample_id':'S','electrode_id':'E','current_mA':.1,'temperature_C':25,
                       'separator_thickness_um':25,'separator_porosity':.5,'electrolyte_concentration_mol_L':1,
                       'voltage_lower_V':.01,'voltage_upper_V':1.5}],
            '仿真输入':[{'model_input_id':'M','sample_id':'S','initial_x0':.5,'c_max_mol_m3':30000,'ds_m2_s':1e-14,'i0_A_m2':1}]}


def test_sample_geometry_units_and_sources():
    r=build_sample(fixture(),{'electrode_id':'E','cell_id':'C','ocp_job_id':'test'})
    assert r['candidate_complete']
    assert r['parameters']['bulk_density_g_cm3']['value']==pytest.approx(1)
    assert r['parameters']['active_volume_fraction']['value']==pytest.approx(.9/2.2)
    assert r['parameters']['ds_m2_s']['kind']=='declared_model'
    assert not r['physics_validation_passed']


def test_sample_missing_ambiguous_density_and_d50_assumption():
    t=fixture();t['表征']*=2
    r=build_sample(t,{'electrode_id':'E','cell_id':'C'})
    assert 'radius_um' in r['missing'] and not r['candidate_complete']
    t=fixture();t['表征'][0].pop('effective_radius_um');t['表征'][0]['d50_um']=10
    assert 'radius_um' in build_sample(t,{'electrode_id':'E'})['missing']
    assert build_sample(t,{'electrode_id':'E','allow_d50_radius':True})['parameters']['radius_um']['kind']=='assumed'


def test_sample_conflict_and_cross_sample():
    t=fixture();t['极片'][0]['porosity']=.1
    assert build_sample(t,{'electrode_id':'E'})['conflicts']
    t['半电池'][0]['sample_id']='OTHER'
    with pytest.raises(ValueError):build_sample(t,{'electrode_id':'E','cell_id':'C'})


def test_preprocess_units_duplicate_and_time_reset():
    raw=b'time_s,Voltage(mV),Current(mA)\n0,100,1\n1,101,2\n1,101,2\n0,102,3\n2,nan,3\n'
    rows,r=normalize_csv(raw)
    assert rows[0]['voltage_V']==.1 and rows[0]['current_A']==.001
    assert r['consecutive_exact_duplicates_removed']==1
    assert r['segments']==2 and r['issue_count']==2 and not r['qc_pass']


def test_unknown_units_and_ambiguous_header_blocked():
    with pytest.raises(ValueError):normalize_csv(b't,V\n0,.1\n1,.2\n',{'time_column':'t','voltage_column':'V'})
    rows,r=normalize_csv(b't,V\n0,.1\n1,.2\n',{'time_column':'t','voltage_column':'V','time_unit':'s','voltage_unit':'V'})
    assert r['qc_pass'] and len(rows)==2


def test_duration_and_missing_current():
    rows,r=normalize_csv(b'time_s,voltage_V\n00:00:01,.1\n00:01:00,.2\n')
    assert rows[1]['time_s']==60 and r['warnings']


def test_public_cycler_faults_detected():
    root=Path(__file__).resolve().parents[1]/'data/external/cycler_pipeline_qc_18214281/raw'
    if not root.exists():pytest.skip('local public fixtures not downloaded')
    _,landt=normalize_csv(next(root.glob('*Landt.csv')).read_bytes())
    _,neware=normalize_csv(next(root.glob('*Time_Bug.csv')).read_bytes())
    _,digatron=normalize_csv(next(root.glob('*Digatron.csv')).read_bytes())
    assert landt['mapping']['time']=='test_time_s'
    assert not neware['qc_pass'] and neware['segments']>1
    assert not digatron['qc_pass'] and any('1000' in w for w in digatron['warnings'])


def test_archive_report_escape_and_original_bytes(tmp_path):
    app=Application(tmp_path);w=app.store.list()[0]
    raw=b'time_s,voltage_V\n0,.1\n1,.2\n'
    j=app.preprocess({'workspace':w['id'],'content':base64.b64encode(raw).decode(),'filename':'<script>bad</script>'})
    assert (tmp_path/'jobs'/j['id']/'source.csv').read_bytes()==raw
    assert (tmp_path/'jobs'/j['id']/'normalized.csv').exists()
    report=app.report(w['id']).decode();assert '&lt;script&gt;bad&lt;/script&gt;' in report and '<script>bad</script>' not in report


def test_ocp_requires_strict_domain(tmp_path):
    app=Application(tmp_path);w=app.store.list()[0]
    raw=b'stoichiometry,voltage_V\n0,.5\n.5,.2\n1,.1\n'
    j=app.import_ocp({'workspace':w['id'],'content':base64.b64encode(raw).decode()})
    assert j['result']['x_max']==1
    with pytest.raises(ValueError):app.import_ocp({'workspace':w['id'],'content':base64.b64encode(raw.replace(b'.5,.2',b'0,.2')).decode()})


def test_sample_forward_runtime(tmp_path):
    pybamm=pytest.importorskip('pybamm')
    from user_tools.workbench.sample_forward import run_sample_forward
    from battery_sim.models.pybamm_factory import load_parameter_values
    import numpy as np
    p=load_parameter_values('Ecker2015_graphite_halfcell')
    x=np.linspace(.001,.999,150);v=np.array([float(p['Positive electrode OCP [V]'](xx).evaluate()) for xx in x])
    ocp=tmp_path/'ocp.csv';np.savetxt(ocp,np.c_[x,v],delimiter=',',header='stoichiometry,voltage_V',comments='')
    packet=build_sample(fixture(),{'electrode_id':'E','cell_id':'C','ocp_job_id':'test'})
    r=run_sample_forward({'sample_packet':packet,'ocp_path':str(ocp),'duration_s':100},tmp_path/'forward')
    assert r['current_A']==pytest.approx(.0001)
    assert r['modeled_charge_Ah']==pytest.approx(.0001*100/3600)
    assert not r['independent_validation_passed'] and 'Positive particle diffusivity [m2.s-1]' in r['applied_keys']
    assert r['final_mean_stoichiometry']>r['initial_mean_stoichiometry']
    active_volume=2e-4*50e-6*packet['parameters']['active_volume_fraction']['value']
    expected_dx=.0001*100/(96485.33212*active_volume*30000)
    assert r['final_mean_stoichiometry']-r['initial_mean_stoichiometry']==pytest.approx(expected_dx,rel=1e-4)
    packet['parameters']['current_mA']['value']=-.1
    reverse=run_sample_forward({'sample_packet':packet,'ocp_path':str(ocp),'duration_s':100},tmp_path/'reverse')
    assert reverse['final_mean_stoichiometry']<reverse['initial_mean_stoichiometry']
