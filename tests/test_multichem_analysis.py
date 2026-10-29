import base64
import json
import math
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

from user_tools.workbench.multichem_analysis import run
from user_tools.workbench.server import Application, Handler


def test_arrhenius_recovers_activation_energy():
    ea = 31000
    raw = 'temperature_C,value\n' + ''.join(
        f'{t},{math.exp(7-ea/(8.314462618*(t+273.15)))}\n' for t in (5, 25, 45, 60))
    result = run('arrhenius', raw.encode(), {'quantity':'conductivity'})
    assert result['activation_energy_kJ_mol'] == pytest.approx(31, abs=1e-8)
    assert result['fit']['r2'] == pytest.approx(1)


def test_alignment_does_not_extrapolate_and_rejects_unsorted():
    raw = b'stream,time_s,value\nelectrochemistry,0,1\nelectrochemistry,1,2\nelectrochemistry,2,3\nsignal,0,10\nsignal,1,20\n'
    result = run('align',raw,{'offset_s':1})
    assert [p['time_s'] for p in result['points']] == [1,2]
    assert [p['signal'] for p in result['points']] == [10,20]
    with pytest.raises(ValueError,match='严格递增'):
        run('align',raw.replace(b'signal,1,20',b'signal,0,20'),{})


def test_partial_charge_coulomb_count_and_sign_guard():
    raw=b'time_s,current_A,voltage_V\n0,1,3\n360,1,3.1\n'
    result=run('partial_charge',raw,{'charge_sign':'positive','initial_soc':.4,'capacity_Ah':1})
    assert result['charge_Ah']==pytest.approx(.1)
    assert result['soc_coulomb_count']==pytest.approx(.5)
    with pytest.raises(ValueError,match='反向电流'):
        run('partial_charge',raw,{'charge_sign':'negative'})


def test_hysteresis_temperature_interpolation_and_out_of_range():
    curve=[{'soc':s,'temperature_C':t,'charge_V':3+s+.01*t+.1,'discharge_V':3+s+.01*t-.1,'R0_ohm':.02}
           for t in (0,40) for s in (0,1)]
    config={'capacity_Ah':1,'initial_soc':.5,'hysteresis_rate':30,'ocv_table':curve}
    raw=b'time_s,current_A,temperature_C\n0,1,20\n360,1,20\n'
    result=run('hysteresis',raw,config)
    assert result['points'][0]['voltage_V']==pytest.approx(3.68)
    assert result['points'][1]['soc']==pytest.approx(.4)
    assert result['points'][1]['hysteresis']<0
    with pytest.raises(ValueError,match='超出参数表'):
        run('hysteresis',raw.replace(b',20',b',50'),config)


def test_rc_branch_and_online_update_use_prior_prediction():
    curve=[{'soc':s,'temperature_C':t,'charge_V':3,'discharge_V':3,'R0_ohm':.02}
           for t in (0,40) for s in (0,1)]
    config={'capacity_Ah':1,'initial_soc':.5,'hysteresis_rate':10,'ocv_table':curve,
            'rc_branches':[{'R_ohm':.01,'C_F':100}],
            'rls':{'forgetting_factor':1,'initial_covariance':1,'max_delta_ohm':.01}}
    raw=b'time_s,current_A,temperature_C,voltage_V\n0,1,20,2.97\n1,1,20,2.96\n'
    points=run('hysteresis',raw,config)['points']
    assert points[0]['voltage_V']==pytest.approx(2.98)
    assert points[0]['R0_delta_after_update_ohm']>0
    assert points[1]['R0_ohm_used']>points[0]['R0_ohm_used']
    with pytest.raises(ValueError,match='每行实测'):
        run('hysteresis',raw.replace(b'2.96',b''),config)


def test_quality_marks_time_backtrack_without_repair():
    raw=b'time_s,voltage_V,current_A\n0,3,1\n1,3.1,1\n0.5,3.2,1\n2,3.3,1\n'
    report=run('quality',raw,{})
    assert report['segments']==2 and not report['qc_pass']
    assert any('时间回跳' in i['reason'] for i in report['issues'])


def test_hardcarbon_and_electrolyte_do_not_impute():
    raw=b'record_id,group_id,batch_id,d002_nm\na,p1,b1,0.38\nb,p2,b2,\n'
    assert run('hardcarbon',raw,{})['missing']['d002_nm']==1
    assert run('hardcarbon',raw,{})['groups']==2
    formulas=b'record_id,salt,salt_mol_L,solvent_fraction\na,NaPF6,1,0.5\nb,NaPF6,1,1.5\n'
    assert run('electrolyte',formulas,{})['invalid_records']==['b']


def test_hardcarbon_sized_table_passes_existing_ml_adapter():
    from user_tools.workbench.ml_data import csv_dataset
    rows='record_id,group_id,batch_id,d002_nm,ice\n'+''.join(
        f'r{i},paper{i//5},batch{i//5},0.38,0.8\n' for i in range(565))
    dataset=csv_dataset(rows.encode(),{'target':'ice'})
    assert len(dataset['rows'])==565 and len({r['group_id'] for r in dataset['rows']})==113


def test_cv_reports_observed_extrema():
    raw=b'curve,potential_V,current_A\na,0.1,-0.2\na,0.3,0.4\n'
    result=run('cv',raw,{})['curves'][0]
    assert result['max_potential_V']==.3 and result['min_current_A']==-.2


def test_authenticated_api_saves_source_and_analysis(tmp_path):
    app=Application(tmp_path);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.app=app
    threading.Thread(target=server.serve_forever,daemon=True).start()
    raw=b'temperature_C,value\n5,1\n25,2\n45,3\n'
    try:
        payload={'workspace':app.store.list()[0]['id'],'kind':'arrhenius','content':base64.b64encode(raw).decode(),'config':{}}
        req=Request(f'http://127.0.0.1:{server.server_port}/api/multichem',data=json.dumps(payload).encode(),headers={'X-Workbench-Token':app.token,'Content-Type':'application/json'})
        response=json.loads(urlopen(req).read());folder=tmp_path/'jobs'/response['job']['id']
        assert (folder/'source.csv').read_bytes()==raw
        assert json.loads((folder/'multichem.json').read_text(encoding='utf8'))['kind']=='arrhenius'
        assert app.store.job(response['job']['id'])['workspace']==payload['workspace']
    finally:
        server.shutdown();server.server_close()
