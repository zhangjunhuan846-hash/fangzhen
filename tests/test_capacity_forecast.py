import base64
import csv
import io
import json

import pytest

from user_tools.workbench.capacity_forecast import forecast, parse_cycles
from user_tools.workbench.server import Application


def test_source_folder_only_opens_a_registered_local_source(tmp_path):
    from user_tools.workbench.capacity_forecast import source_folder

    folder = tmp_path / 'data/public/sodium_ion/example'
    folder.mkdir(parents=True)
    (folder / 'manifest.json').write_text('{"id":"example"}', encoding='utf8')
    assert source_folder(tmp_path, 'example') == folder.resolve()
    for name in ('..', '../example', '/example', 'example/manifest.json', 'missing'):
        with pytest.raises(ValueError):
            source_folder(tmp_path, name)


def test_only_prefix_is_visible_to_model_and_sparse_cycles_are_preserved():
    source = b'cell_id,cycle,capacity_Ah\nA,5,2\nA,1,3\nA,8,1\nA,16,0.5\nB,1,10\n'
    cells = parse_cycles(source)
    a = forecast(cells, 'A', 'linear', 5, 2)
    cells['A'][8], cells['A'][16] = 20., 12.
    b = forecast(cells, 'A', 'linear', 5, 2)
    assert [p[0] for p in a['points']] == [1, 5, 8, 16, 17, 18]
    assert [p[3] for p in a['points']] == [p[3] for p in b['points']]
    assert a['metrics'] != b['metrics']
    assert a['metrics']['baseline_mae_Ah'] == 1.25
    assert a['points'][-1][2] is None


def test_all_observations_can_be_used_for_unscored_extrapolation():
    result = forecast({'A': {0: 3., 1: 2., 2: 1.}}, 'A', 'last', 2, 2)
    assert result['metrics'] is None and result['holdout_points'] == 0
    assert result['points'][-1] == (4, 'future', None, 1., 1.)


def test_rolling_intervals_use_only_prior_errors_at_each_forecast_lead():
    cells = {'A': {c: 200 - c for c in range(41)}}
    result = forecast(cells, 'A', 'last', 30, 8, 90)
    rows = {p[0]: p for p in result['points']}
    assert rows[30][5:] == (None, None, None)
    assert rows[31][5:] == (169, 171, 24)
    assert rows[46][5:] == (154, 186, 9)
    assert rows[47][5:] == (None, None, 8)
    interval = result['interval']
    assert (interval['holdout_covered'], interval['holdout_bounded'], interval['future_bounded']) == (10, 10, 6)
    assert interval['empirical_coverage'] == 1 and interval['mean_width_Ah'] == 11
    cells['A'].update({c: 0 for c in range(31, 41)})
    changed = forecast(cells, 'A', 'last', 30, 15, 90)
    assert [row[3:] for row in changed['points'][:49]] == [row[3:] for row in result['points']]
    assert changed['interval']['empirical_coverage'] == 0


def test_irregular_measurements_use_true_cycle_offsets_from_last_training_observation():
    cells = {'A': {c: 10 for c in [*range(0, 201, 10), 205, 210, 220]}}
    result = forecast(cells, 'A', 'last', 203, 0, 90)
    assert result['observed_through'] == 200
    assert [(r[0], r[5], r[7]) for r in result['points'][-3:]] == [(205, None, 0), (210, 10, 16), (220, 10, 15)]
    assert result['interval']['holdout_bounded'] == 2
    assert result['interval']['empirical_coverage'] == 1


@pytest.mark.parametrize(('level', 'minimum'), [(80, 4), (90, 9), (95, 19)])
def test_future_only_intervals_report_historical_support_without_a_coverage_score(level, minimum):
    cells = {'A': {c: 40 - c for c in range(41)}}
    r = forecast(cells, 'A', 'last', 40, 2, str(level))
    assert r['points'][-1][5:7] == (0, 2)
    assert r['interval']['min_origins_per_lead'] == minimum
    assert r['interval']['future_bounded'] == 2
    assert r['interval']['empirical_coverage'] is None and r['interval']['mean_width_Ah'] is None


@pytest.mark.parametrize('level', [0, 85, True, '0.9'])
def test_invalid_interval_levels_are_rejected(level):
    with pytest.raises(ValueError, match='区间水平'):
        forecast({'A': {0: 3, 1: 2, 2: 1}}, 'A', 'last', 2, 1, level)


def test_public_numpy_polynomial_runs_on_training_prefix():
    numpy = pytest.importorskip('numpy')
    cells = {'A': {0: 1., 1: .99, 2: .96, 3: .91, 4: .84}}
    output = forecast(cells, 'A', 'numpy-polynomial', 2, 1)
    assert output['algorithm_version'] == 'numpy ' + numpy.__version__
    assert output['metrics']['mae_Ah'] < 1e-12
    assert output['points'][-1][3] == pytest.approx(.75)


def test_installed_forecaster_is_discovered_and_receives_only_observations_before_cutoff(tmp_path, monkeypatch):
    dist = tmp_path / 'curve_demo-1.0.dist-info'
    dist.mkdir()
    (dist / 'METADATA').write_text('Metadata-Version: 2.1\nName: curve-demo\nVersion: 1.0\n')
    (dist / 'entry_points.txt').write_text('[fangzhen.capacity_forecasters]\nexample = curve_demo:predict\n')
    (tmp_path / 'curve_demo.py').write_text(
        'def predict(cycles, capacities, targets):\n'
        '    assert cycles == (1, 2) and capacities == (3.0, 2.8)\n'
        '    return [2.7 for cycle in targets]\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    r = forecast({'A': {1: 3., 2: 2.8, 3: 2.6}}, 'A', 'curve-demo/example', 2, 1)
    assert r['algorithm_version'] == '1.0' and r['metrics']['mae_Ah'] == pytest.approx(.1)


@pytest.mark.parametrize('tail', ['A,1,2', 'A,-1,4', 'A,3,nan', 'A,2,-1', ',2,4'])
def test_invalid_or_duplicate_measurements_are_rejected(tail):
    with pytest.raises(ValueError):
        parse_cycles(('cell_id,cycle,capacity_Ah\nA,1,3\n' + tail).encode())


@pytest.mark.parametrize('interval_level', [None, 90])
def test_uploaded_run_is_reproducible_from_downloadable_inputs(tmp_path, interval_level):
    app = Application(tmp_path / 'store', tmp_path)
    wid = app.store.list()[0]['id']
    raw = b'cell_id,cycle,capacity_Ah\nC,1,3\nC,3,2.8\nC,5,2.6\n'
    packet = app.capacity_forecast(dict(workspace=wid, content=base64.b64encode(raw).decode(),
                                        filename='cell.csv', cell='C', algorithm='linear', cutoff=3, horizon=1,
                                        interval_level=interval_level))
    job = app.store.job(packet['job']['id'])
    directory = app.data / 'jobs' / job['id']
    assert job['workspace'] == wid and (directory / 'capacity_input.csv').read_bytes() == raw
    saved = json.loads((directory / 'capacity.json').read_text('utf8'))
    assert saved['source']['id'] == 'upload'
    rows = list(csv.DictReader(io.StringIO((directory / 'capacity.csv').read_text('utf-8-sig'))))
    assert rows[-2]['phase'] == 'holdout' and float(rows[-2]['predicted_Ah']) == pytest.approx(2.6)
    assert rows[-1]['measured_Ah'] == '' and rows[-1]['phase'] == 'future'
    if interval_level:
        assert job['result']['interval_level'] == 90 and saved['interval']['empirical_coverage'] is None
        assert rows[-1]['lower_Ah'] == rows[-1]['upper_Ah'] == '' and rows[-1]['calibration_count'] == '0'
    else:
        assert 'interval' not in saved and 'lower_Ah' not in rows[-1]


def test_input_summary_preserves_sparse_observations_and_zero_values():
    from user_tools.workbench.capacity_forecast import cells_info
    summary=cells_info({'C':{8:0.,1:3.,3:2.8}})[0]
    assert summary['cycles']==[1,3,8]
    assert summary['nonconsecutive_intervals']==2
    assert summary['first_capacity_Ah']==3 and summary['last_capacity_Ah']==0
    assert summary['zero_capacity_count']==1 and summary['default_cutoff']==3


def test_saved_capacity_input_reuse_keeps_original_result_and_records_parent(tmp_path):
    app=Application(tmp_path/'data',tmp_path)
    workspace=app.store.list()[0]['id']
    raw=b'cell_id,cycle,capacity_Ah\nC,1,3\nC,2,2.9\nC,3,2.8\nC,4,2.7\nC,5,2.6\n'
    first=app.capacity_forecast({'workspace':workspace,'content':base64.b64encode(raw).decode(),
                                 'filename':'measured.csv','cell':'C','algorithm':'linear','cutoff':3,'horizon':2})
    parent=first['job']['id']
    original=(app.data/'jobs'/parent/'capacity.json').read_bytes()
    second=app.capacity_forecast({'workspace':workspace,'source_job':parent,'cell':'C',
                                  'algorithm':'sqrt','cutoff':4,'horizon':3})
    assert second['job']['id']!=parent
    assert second['result']['input_sha256']==first['result']['input_sha256']
    assert second['result']['source']['title']=='measured.csv'
    assert second['result']['source']['parent_job']==parent
    assert (app.data/'jobs'/parent/'capacity.json').read_bytes()==original
    assert app.store.job(parent)==first['job']
    context=app.job_context(second['job']['id'])
    assert context['parents']==[{'id':parent,'title':'capacity_forecast'}]
    assert context['snapshot_available']
    assert len(app.store.jobs())==2


def test_saved_capacity_input_rejects_other_projects_conflicting_sources_and_tampering(tmp_path):
    app=Application(tmp_path/'data',tmp_path)
    workspace=app.store.list()[0]['id']
    raw=b'cell_id,cycle,capacity_Ah\nC,1,3\nC,2,2.9\nC,3,2.8\n'
    first=app.capacity_forecast({'workspace':workspace,'content':base64.b64encode(raw).decode(),
                                 'cell':'C','algorithm':'linear','cutoff':2,'horizon':1})
    payload={'workspace':workspace,'source_job':first['job']['id'],'cell':'C',
             'algorithm':'linear','cutoff':2,'horizon':1}
    other=app.store.create('Other project')['id']
    with pytest.raises(ValueError,match='当前项目'):
        app.capacity_forecast({**payload,'workspace':other})
    with pytest.raises(ValueError,match='只能选择一项'):
        app.capacity_forecast({**payload,'dataset':'another-source'})
    (app.data/'jobs'/first['job']['id']/'capacity_input.csv').write_bytes(raw+b'C,4,2.7\n')
    with pytest.raises(ValueError,match='校验值不一致'):
        app.capacity_forecast(payload)
    assert len(app.store.jobs())==1
