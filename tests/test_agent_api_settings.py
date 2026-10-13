import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from user_tools.workbench.agent_api_settings import (
    public_settings, save_settings, settings_path, validate_endpoint,
)
from user_tools.workbench.server import Application, Handler


def test_config_validation_and_key_lifecycle(tmp_path):
    for url in ('http://example.com:8080/v1', 'http://localhost:99999/v1',
                'https://user:pass@example.com/v1', 'https://example.com/v1?key=secret'):
        with pytest.raises(ValueError):
            validate_endpoint(url, 'model')
    first = save_settings(tmp_path, {'base_url': 'http://127.0.0.1:11434/v1',
                                     'model': 'demo', 'api_key': 'private-token'})
    assert first == {'configured': True, 'base_url': 'http://127.0.0.1:11434/v1',
                     'model': 'demo', 'has_api_key': True}
    assert 'private-token' not in json.dumps(first)
    save_settings(tmp_path, {'base_url': 'https://example.com/v1', 'model': 'other', 'api_key': ''})
    assert json.loads(settings_path(tmp_path).read_text())['api_key'] == 'private-token'
    save_settings(tmp_path, {'base_url': 'https://example.com/v1', 'model': 'other', 'clear_key': True})
    assert public_settings(tmp_path)['has_api_key'] is False


def test_local_api_saves_without_exposing_key_and_probes_endpoint(tmp_path):
    authorization = []
    class ModelHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            authorization.append(self.headers.get('Authorization'))
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"data":[]}')
    model_server = HTTPServer(('127.0.0.1', 0), ModelHandler)
    model_thread = threading.Thread(target=model_server.serve_forever, daemon=True)
    model_thread.start()
    app = Application(tmp_path/'state', project=tmp_path)
    ui_server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); ui_server.app = app
    ui_thread = threading.Thread(target=ui_server.serve_forever, daemon=True); ui_thread.start()
    base = f'http://127.0.0.1:{ui_server.server_port}'
    headers = {'Host': f'127.0.0.1:{ui_server.server_port}', 'X-Workbench-Token': app.token,
               'Content-Type': 'application/json'}
    def request(path, payload=None, token=True):
        used = headers if token else {k:v for k,v in headers.items() if k!='X-Workbench-Token'}
        req = Request(base+path, data=json.dumps(payload).encode() if payload is not None else None,
                      headers=used)
        return json.loads(urlopen(req).read())
    try:
        with pytest.raises(HTTPError) as exc:
            request('/api/agent_llm', token=False)
        assert exc.value.code == 403
        endpoint = f'http://127.0.0.1:{model_server.server_port}/v1'
        result = request('/api/agent_llm', {'base_url': endpoint, 'model': 'demo', 'api_key': 'private-token'})
        assert result['has_api_key'] and 'private-token' not in json.dumps(result)
        assert 'private-token' not in json.dumps(request('/api/agent_llm'))
        assert request('/api/agent_llm_probe', {})['reachable'] is True
        assert authorization == ['Bearer private-token']
    finally:
        ui_server.shutdown(); ui_server.server_close()
        model_server.shutdown(); model_server.server_close()
