import json
import pytest
from user_tools.workbench.battery_agent import normalize, validate_proposal, explore
from user_tools.workbench.server import Application


def test_locked_parameters_bounds_and_remote_consent():
    with pytest.raises(ValueError):
        normalize({'bounds': {'thickness': [-1, 1]}})
    with pytest.raises(ValueError):
        normalize({'bounds': {'diffusivity': [1, 2]}})
    with pytest.raises(ValueError):
        normalize({'strategy': 'llm'})
    with pytest.raises(ValueError):
        normalize({'budget': 3.5})
    with pytest.raises(ValueError):
        validate_proposal({'diffusivity': float('nan')}, {'diffusivity': [-1, 1]})


def test_failed_candidate_cannot_win_and_memory_budget(tmp_path):
    def evaluate(values, out):
        z = values['diffusivity']
        if z > 0:
            raise ValueError('partial curve')
        return {'rmse_mV': 5 + z}
    result = explore({'bounds': {'diffusivity': [-1, 1]}, 'budget': 4}, evaluate, tmp_path)
    assert result['simulations_used'] == 4
    assert result['history'][1]['status'] == 'failed'
    assert result['best']['log_multipliers']['diffusivity'] < 0
    assert result['improvement_mV'] > 0
    assert json.loads((tmp_path/'memory.json').read_text(encoding='utf-8')) == result['history']


def test_llm_invalid_and_repeated_proposals_stop_without_silent_fallback(tmp_path):
    config = {'strategy': 'llm', 'accept_llm': True, 'budget': 4, 'bounds': {'diffusivity': [-1, 1]}}
    evaluate = lambda values, out: {'rmse_mV': 4}
    result = explore(config, evaluate, tmp_path/'invalid', lambda h, b: ({'diffusivity': 2}, 'invalid'))
    assert result['stop_reason'] == 'proposal_rejected' and result['simulations_used'] == 1
    result = explore(config, evaluate, tmp_path/'repeat', lambda h, b: ({'diffusivity': 0}, 'repeat'))
    assert result['stop_reason'] == 'repeated_proposal' and result['simulations_used'] == 1


def test_all_failed_exploration_has_no_fabricated_best(tmp_path):
    def fail(*args):
        raise RuntimeError('solver failure')
    result = explore({'budget': 3}, fail, tmp_path)
    assert result['best'] is None and result['rmse_mV'] is None
    assert result['independent_validation'] == 'not_performed'


def test_job_integration_keeps_inputs_and_snapshot(tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr(threading.Thread, 'start', lambda self: None)
    app = Application(tmp_path)
    workspace = app.store.list()[0]
    job = app.start_job({'workspace': workspace['id'], 'mode': 'battery_agent', 'agent_config': {'budget': 3}})
    folder = tmp_path/'jobs'/job['id']
    assert json.loads((folder/'config.json').read_text())['agent_config']['case'] == 'graphite'
    assert (folder/'workspace_snapshot.json').exists()
    with pytest.raises(ValueError, match='API'):
        app.start_job({'workspace': workspace['id'], 'mode': 'battery_agent',
                       'agent_config': {'strategy': 'llm', 'accept_llm': True}})


def test_real_llm_request_contract_and_credentials_not_archived(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from user_tools.workbench.battery_agent import llm_proposer
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            answer = {'choices': [{'message': {'content': json.dumps({'log_multipliers': {'diffusivity': -.5}, 'reason': 'test evidence'})}}]}
            self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(answer).encode())
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    config_path = tmp_path/'private.json'
    config_path.write_text(json.dumps({'base_url': f'http://127.0.0.1:{server.server_port}/v1',
                                       'model': 'test', 'api_key': 'private-test-token'}))
    try:
        proposer, metadata = llm_proposer(config_path)
        result = explore({'strategy': 'llm', 'accept_llm': True, 'budget': 3, 'bounds': {'diffusivity': [-1, 1]}},
                         lambda v, p: {'rmse_mV': 10 + v['diffusivity']}, tmp_path/'run', proposer)
        assert result['simulations_used'] == 2 and result['stop_reason'] == 'repeated_proposal'
        assert 'private-test-token' not in json.dumps(requests) + json.dumps(metadata) + json.dumps(result)
        assert requests[0]['messages'][1]['content']
    finally:
        server.shutdown(); server.server_close()


def test_worker_rejects_short_curves_on_fixed_window(tmp_path, monkeypatch):
    np = pytest.importorskip('numpy')
    pd = pytest.importorskip('pandas')
    pytest.importorskip('pybamm')
    from user_tools.workbench.battery_agent_worker import run_agent
    import battery_sim.registry as registry
    import battery_sim.models.pybamm_factory as factory
    import battery_sim.simulation.baseline as baseline
    import governance.dataset_roles as roles
    frame = pd.DataFrame({'time_s': np.arange(10.), 'current_A': np.ones(10), 'voltage_V': np.ones(10)})
    class Adapter:
        def load_processed_discharge(self, *args):
            return frame
    monkeypatch.setattr(registry, 'get_dataset', lambda *args: Adapter())
    monkeypatch.setattr(factory, 'load_parameter_values', lambda *args: {'Positive particle diffusivity [m2.s-1]': 1.})
    monkeypatch.setattr(factory, 'resolve_model_options', lambda *args: {})
    monkeypatch.setattr(roles, 'assert_calibration_allowed', lambda *args, **kw: [])
    monkeypatch.setattr(baseline, '_filter_and_downsample', lambda t, i, v: (t, i, v))
    def replay(frame, model, parameter_set, options, overrides, sources):
        short = overrides['Positive particle diffusivity [m2.s-1]'] > 1.01
        n = 3 if short else 10
        # Truncated candidate has perfect local error; must still be rejected.
        return {'_t_common': np.arange(float(n)), '_V_sim_common': np.ones(n) * (1. if short else 1.1),
                'coverage_fraction': .2 if short else 1.}
    monkeypatch.setattr(baseline, '_run_one_replay', replay)
    result = run_agent({'model': 'SPM', 'agent_config': {'budget': 3, 'bounds': {'diffusivity': [-1, 1]}}}, tmp_path)
    assert result['history'][1]['status'] == 'failed'
    assert result['best']['rmse_mV'] == pytest.approx(100.)
    assert len({r['comparison_points'] for r in result['history'] if r['status'] == 'ok'}) == 1
    assert result['all_candidates_use_same_comparison_points']
