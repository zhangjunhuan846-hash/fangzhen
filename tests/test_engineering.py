"""Optional integration acceptance: independent oracles and leakage guards."""
import csv
import hashlib
import io
import json
import math
from pathlib import Path

import pytest

from user_tools.workbench.engineering_contracts import ACTIONS, defaults, normalize
from user_tools.workbench.engineering_service import bridge_eis, runtime_for
from user_tools.workbench.engineering_worker import run


ROOT = Path(__file__).resolve().parents[1]


def raw_csv(rows):
    stream = io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return stream.getvalue().encode()


@pytest.mark.parametrize('action', list(ACTIONS))
def test_demo_is_explicit_and_contract_finite(action):
    config = normalize(defaults(action))
    assert config['data_origin'] == ('public' if action in ['batterylife','commercial_validation','commercial_adaptive','eis_audit','calb_validation','crosscell_validation','tesla_refined','stanford_frozen','eis_hppc_ablation'] else 'synthetic')
    if action not in ['batterylife','commercial_validation','commercial_adaptive','eis_audit','calb_validation','crosscell_validation','tesla_refined','safety_bench','stanford_frozen','eis_hppc_ablation']:
        assert config['cell']['capacity_Ah'] == 5
    else:
        assert 'cell' not in config
    config['seed'] = float('nan')
    with pytest.raises(ValueError): normalize(config)


def test_real_runs_require_complete_source_and_reject_silent_demo_cell():
    c=defaults('mpc');c['data_origin']='user'
    with pytest.raises(ValueError,match='source'):normalize(c)
    c['source']='cell datasheet'
    with pytest.raises(ValueError,match='实际电芯'):normalize(c)
    c['cell']['cell_id']='measured-cell-A';c['cell'].pop('capacity_Ah')
    with pytest.raises(ValueError,match='完整'):normalize(c)


def test_unused_csv_and_device_transport_are_rejected():
    for action in ['mpc','pack']:
        with pytest.raises(ValueError,match='不读取CSV'):normalize(defaults(action),b'a\n1\n2\n')
    c=defaults('can');c['interface']='socketcan'
    with pytest.raises(ValueError,match='虚拟CAN'):normalize(c)


def test_eis_bridge_has_operating_window_same_cell_and_artifact_trace():
    c=defaults('ecm_bms');c.update(same_cell_eis_confirmed=True,eis_operating_soc=.8,eis_operating_temperature_C=25)
    result={'kind':'eis_fit','engine':'impedance.py','parameters':[{'name':k,'value':v} for k,v in [('R0',.01),('R1',.02),('C1',500)]]}
    changed=bridge_eis(c,result,'parent',b'original result')
    assert changed['cell']['R_ohm']==[.02]
    assert changed['eis_parameter_source']['result_sha256']==hashlib.sha256(b'original result').hexdigest()
    assert c['cell']['R_ohm']==[.025]  # caller's declared parameters preserved
    c['eis_operating_soc']=.3
    with pytest.raises(ValueError,match='初始SOC'):bridge_eis(c,result,'parent',b'')
    c['same_cell_eis_confirmed']=False
    with pytest.raises(ValueError,match='同一电芯'):bridge_eis(c,result,'parent',b'')


def test_all_engineering_files_registered():
    text=(ROOT/'MODULES.yaml').read_text(encoding='utf-8')
    for p in (ROOT/'user_tools/workbench').glob('engineering*.py'):
        assert p.relative_to(ROOT).as_posix() in text
    assert 'test_engineering.py' in text


def test_runtime_split_does_not_send_legacy_packages_to_core():
    if not (ROOT/'data/engineering_runtime.local.json').exists(): pytest.skip('optional runtimes not installed')
    assert '/pack/bin/python' in runtime_for(ROOT,'pack')
    assert '/batteryml_legacy/bin/python' in runtime_for(ROOT,'batteryml')
    assert '/engineering/bin/python' in runtime_for(ROOT,'mpc')


def test_source_mutation_is_rejected_before_numerical_backend(tmp_path):
    path=tmp_path/'input.csv';path.write_bytes(b'a\n1\n2\n')
    with pytest.raises(ValueError,match='发生变化'):
        run({'engineering_config':defaults('cycler'),'source_path':str(path),'source_sha256':'0'*64},tmp_path/'out')


def test_thevenin_step_matches_independent_rc_oracle(tmp_path):
    pytest.importorskip('thevenin');pytest.importorskip('sox')
    from user_tools.workbench.engineering_bms import run_bms
    c=defaults('ecm_bms');c.update(voltage_noise_V=1e-6,current_noise_A=0,current_bias_A=0)
    data=raw_csv([{'time_s':t,'current_A':1} for t in [0,10,20,30,40,50]])
    r=run_bms(c,tmp_path,data)
    rows=list(csv.DictReader((tmp_path/'engineering.csv').open(encoding='utf-8-sig')))
    for row in rows:
        t=float(row['time_s']);soc=.8-t/(3600*5)
        ocv=3.95+(soc-.8)  # independent slope in the .5--.8 OCV segment
        polarization=.025*(1-math.exp(-t/(.025*1500)))
        assert float(row['model_soc'])==pytest.approx(soc,abs=1e-8)
        assert float(row['model_voltage_V'])==pytest.approx(ocv-.012-polarization,abs=2e-6)
    assert r['material_validation'] is False
    assert 'source_sha256' not in r


def test_sox_recovers_from_biased_initial_soc_without_reference_input(tmp_path):
    pytest.importorskip('thevenin');pytest.importorskip('sox')
    from user_tools.workbench.engineering_bms import run_bms
    c=defaults('ecm_bms');c['steps']=30
    r=run_bms(c,tmp_path)
    assert r['metrics']['cc_rmse_soc']>.14
    assert r['metrics']['ekf_rmse_soc']<.03
    assert r['metrics']['ukf_rmse_soc']<.03
    rows=list(csv.DictReader((tmp_path/'engineering.csv').open(encoding='utf-8-sig')))
    assert all(float(row['soc_ekf_std'])>0 and float(row['soc_ukf_std'])>0 for row in rows)


def test_real_voltage_has_no_invented_soc_ground_truth(tmp_path):
    pytest.importorskip('thevenin');pytest.importorskip('sox')
    from user_tools.workbench.engineering_bms import run_bms
    c=defaults('ecm_bms');c.update(data_origin='user',source='test fixture');c['cell']['cell_id']='fixture-cell'
    raw=raw_csv([{'time_s':t,'current_A':0,'voltage_V':3.95} for t in range(0,60,10)])
    r=run_bms(normalize(c,raw),tmp_path,raw)
    assert not any('rmse_soc' in k for k in r['metrics'])
    assert r['evidence_type']=='user_engineering_analysis'


def joint_spectra(change_test=1):
    rows=[]
    for soc,role in [(.2,'train'),(.8,'train'),(.5,'test')]:
        for i in range(24):
            f=10**(-3+7*i/23);res=.025*math.exp(.8*(soc-.5));z=.012+res/(1+2j*math.pi*f*res*1500)
            if role=='test':z*=change_test
            rows.append({'soc':soc,'frequency_Hz':f,'Z_real_ohm':z.real,'Z_imag_ohm':z.imag,'role':role})
    return raw_csv(rows)


def test_joint_eis_recovers_shared_parameters_and_never_fits_holdout(tmp_path):
    pytest.importorskip('pybop')
    from user_tools.workbench.engineering_identification import run_joint_eis
    first=run_joint_eis(defaults('eis_joint'),tmp_path/'a',joint_spectra())
    second=run_joint_eis(defaults('eis_joint'),tmp_path/'b',joint_spectra(2))
    assert first['fitted_inputs']==second['fitted_inputs']
    assert first['metrics']['test_rmse_complex_ohm']<1e-5
    assert second['metrics']['test_rmse_complex_ohm']>.01
    center=next(p for p in first['parameters'] if p['soc']==.5)
    assert center['R0_ohm']==pytest.approx(.012,rel=.01)
    assert center['R1_ohm']==pytest.approx(.025,rel=.01)
    assert center['C1_F']==pytest.approx(1500,rel=.01)


def test_bo_rejects_future_labels_and_pending_duplicates():
    pytest.importorskip('numpy')
    from user_tools.workbench.engineering_optimize import dataset
    c=defaults('optimize')
    complete,candidates,_=dataset(c,None)
    rows=[{'candidate_id':r['candidate_id'],'x1':r['x'][0],'x2':r['x'][1],
           'objective1':r.get('y',['',''])[0],'objective2':r.get('y',['',''])[1],
           'status':'completed' if 'y' in r else 'candidate'} for r in complete+candidates]
    rows[-1]['objective1']=123
    with pytest.raises(ValueError,match='泄漏'):dataset(c,raw_csv(rows))
    rows[-1]['objective1']='';rows[-1]['status']='pending';rows[-1]['x1']=rows[-2]['x1'];rows[-1]['x2']=rows[-2]['x2']
    with pytest.raises(ValueError,match='坐标重复'):dataset(c,raw_csv(rows))


@pytest.mark.parametrize('algorithm',['qlognehvi','hvkg','psbax','mfkg','mfmes','gibbon','qlogei','dynmeanbo','safeopt'])
def test_actual_botorch_algorithms_produce_only_unmeasured_recommendations(tmp_path,algorithm):
    pytest.importorskip('botorch')
    from user_tools.workbench.engineering_optimize import run_optimize
    c=defaults('optimize');c['algorithm']=algorithm
    r=run_optimize(c,tmp_path)
    if algorithm=='safeopt' and r['decision_status']=='stopped':
        assert r['recommendation'] is None and '停止推荐' in r['decision_reason']
        return
    assert int(r['recommendation']['candidate_id'].split('-')[1])>=10
    assert math.isfinite(r['recommendation']['acquisition'])
    assert r['material_validation'] is False
    assert r['runtime_versions']['botorch']=='0.18.1'
    if algorithm=='dynmeanbo':
        assert r['details']['expert_prior']['decay_weight']==pytest.approx(math.exp(-5))
    if algorithm=='psbax':
        assert r['recommendation']['candidate_id'] in r['details']['sampled_target_candidate_ids']
    if algorithm=='safeopt':
        assert r['recommendation']['candidate_id'] in r['details']['certified_safe_candidate_ids']


def test_pyprobe_keeps_capacity_and_converts_current_sign(tmp_path):
    pytest.importorskip('pyprobe')
    from user_tools.workbench.engineering_io import run_cycler
    run_cycler(defaults('cycler'),tmp_path)
    rows=list(csv.DictReader((tmp_path/'pyprobe_normalized.csv').open()))
    assert float(rows[0]['Current [A]'])==-1
    assert float(rows[-1]['Capacity [Ah]'])==pytest.approx(.25)


def test_fox_dbc_and_virtual_can_roundtrip_preserve_payload(tmp_path):
    pytest.importorskip('can');pytest.importorskip('cantools')
    if not (ROOT/'data/vendor/foxbms-2/tools/dbc/foxbms.dbc').is_file():pytest.skip('optional DBC checkout missing')
    from user_tools.workbench.engineering_io import run_can
    first=tmp_path/'a';second=tmp_path/'b';first.mkdir();second.mkdir()
    r=run_can(defaults('can'),first)
    rows=list(csv.DictReader((first/'engineering.csv').open(encoding='utf-8-sig')))
    replay=raw_csv([{k:rows[0][k] for k in ['time_s','can_id','data_hex']},
                    {**{k:rows[0][k] for k in ['time_s','can_id','data_hex']},'time_s':1}])
    s=run_can(defaults('can'),second,replay)
    assert r['metrics']['dbc_messages']==41
    assert s['metrics']['decoded_signals']==2*r['metrics']['decoded_signals']
    assert json.loads((first/'dbc_compatibility.json').read_text())['removed_orphan_VAL_declarations']
    assert s['hardware_connected'] is False


def test_mpc_reaches_target_without_declared_constraint_violation(tmp_path):
    pytest.importorskip('do_mpc');pytest.importorskip('thevenin');pytest.importorskip('sox')
    from user_tools.workbench.engineering_control import run_control
    r=run_control(defaults('mpc'),tmp_path)
    assert r['metrics']['plant_violation_count']==0
    assert r['metrics']['fallback_count']==0
    assert r['metrics']['max_voltage_V']<=4.2
    assert r['metrics']['max_temperature_C']<=45
    assert r['metrics']['final_estimated_soc']>=.9


def test_infeasible_mpc_records_zero_current_fallback(tmp_path):
    pytest.importorskip('do_mpc');pytest.importorskip('thevenin');pytest.importorskip('sox')
    from user_tools.workbench.engineering_control import run_control
    c=defaults('mpc');c['steps']=5;c['cell']['temperature_C']=44.5
    # Ambient temperature is already above the guarded optimizer limit (44C),
    # while still below the physical declared limit (45C): no feasible plan.
    r=run_control(c,tmp_path)
    assert r['metrics']['fallback_count']==5
    assert r['metrics']['plant_violation_count']==0
    rows=list(csv.DictReader((tmp_path/'engineering.csv').open(encoding='utf-8-sig')))
    assert all(float(row['charge_A'])==0 for row in rows)


def test_model_voltage_to_fox_dbc_millivolt_mapping(tmp_path):
    pytest.importorskip('can');pytest.importorskip('cantools')
    if not (ROOT/'data/vendor/foxbms-2/tools/dbc/foxbms.dbc').is_file():pytest.skip('optional DBC missing')
    from user_tools.workbench.engineering_io import run_can
    c=defaults('can');c['can_telemetry']=[{'time_s':0,'voltage_V':3.71234},{'time_s':10,'voltage_V':4.12345}]
    r=run_can(c,tmp_path)
    rows=list(csv.DictReader((tmp_path/'engineering.csv').open(encoding='utf-8-sig')))
    voltages=[float(row['value']) for row in rows if row['signal']=='CellVoltage_000']
    assert voltages==[3712.,4123.]
    assert all(float(row['value'])==1 for row in rows if row['signal']=='CellVoltage_001_invalidFlag')
    assert r['metrics']['frames']==2
