"""Exercise the packaged public comparison and its HTML/CSV exports."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

root = Path(__file__).resolve().parents[2]
exe = root / 'outputs/fangzhen_workbench_eis_hppc_20261029/FangzhenResearch/FangzhenResearch.exe'
with tempfile.TemporaryDirectory(prefix='eis_hppc_workstation_') as data:
    proc = subprocess.Popen([str(exe), '--data', data, '--project', str(root), '--no-browser'],
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        session = Path(data) / 'session.json'
        for _ in range(200):
            if session.exists(): break
            if proc.poll() is not None: raise RuntimeError('application exited')
            time.sleep(.1)
        x = json.loads(session.read_text(encoding='utf8'))
        token = parse_qs(urlsplit(x['url']).fragment)['token'][0]
        base = f'http://127.0.0.1:{x["port"]}/api/'
        def request(endpoint, body=None, raw=False):
            req = Request(base + endpoint, data=json.dumps(body).encode() if body is not None else None,
                          headers={'X-Workbench-Token':token, 'Content-Type':'application/json'})
            with urlopen(req, timeout=60) as r:
                return r.read() if raw else json.load(r)
        workspace = request('create', {'name':'CALB 回顾性对照'})['id']
        entries = {e['action']:e for e in request('engineering_catalog')}
        assert entries['eis_hppc_ablation']['configured']
        job = request('job', {'workspace':workspace, 'mode':'engineering',
                              'engineering_config':entries['eis_hppc_ablation']['defaults']})
        for _ in range(600):
            found = {j['id']:j for j in request('jobs')}[job['id']]
            if found['status'] == 'failed': raise AssertionError(request('joblog?id=' + job['id']))
            if found['status'] == 'completed': break
            time.sleep(.5)
        else: raise TimeoutError('comparison did not finish')
        assert len(found['result']['comparisons']) == 6
        assert 'hppc_only_open_loop_rmse_mV' in found['result']['metrics']
        for kind, marker in [('eis_hppc_report', b'<!doctype html>'),
                             ('eis_hppc_traces', b'measured_voltage_V'),
                             ('eis_hppc_models', b'node_fits')]:
            content = request('download?id=' + job['id'] + '&kind=' + kind, raw=True)
            assert marker in content, kind
        print('PASS: packaged workstation -> CALB worker -> comparison + HTML/CSV/model exports')
    finally:
        proc.terminate()
        proc.wait(timeout=10)
