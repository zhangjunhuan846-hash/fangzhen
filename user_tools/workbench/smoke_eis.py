"""Real Windows HTTP -> WSL EIS -> downloadable evidence smoke, isolated data."""
import argparse
import base64
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import time
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('data', type=Path, help='Use an isolated workbench --data directory.')
    args = parser.parse_args()
    session = json.loads((args.data / 'session.json').read_text(encoding='utf-8'))
    token = parse_qs(urlsplit(session['url']).fragment)['token'][0]
    base = f'http://127.0.0.1:{session["port"]}/api/'

    def request(path, body=None, binary=False):
        req = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'X-Workbench-Token': token, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=30) as response:
            return response.read() if binary else json.load(response)

    workspace = request('create', {'name': 'EIS软件验收 · 合成RC谱'})
    handle = io.StringIO()
    writer = csv.writer(handle)
    writer.writerow(['frequency_Hz', 'Z_real_ohm', 'Z_imag_ohm'])
    for i in range(81):
        f = 10 ** (-4 + i / 10)
        z = .012 + .055 / (1 + 2j * math.pi * f * .055 * 120)
        writer.writerow([f, z.real, z.imag])
    raw = handle.getvalue().encode()
    job = request('job', {'workspace': workspace['id'], 'mode': 'eis_fit',
                         'content': base64.b64encode(raw).decode(),
                         'eis_config': {'frequency_unit': 'Hz', 'impedance_unit': 'ohm', 'circuit': '1rc'}})
    for _ in range(120):
        current = next(j for j in request('jobs') if j['id'] == job['id'])
        if current['status'] not in ('queued', 'running'):
            break
        time.sleep(1)
    assert current['status'] == 'completed', current
    result = current['result']
    assert result['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['rmse_complex_ohm'] < 1e-7
    assert result['lin_kk']['status'] == 'within_tolerance'
    assert abs(result['parameters'][0]['value'] - .012) < 1e-6
    exports = {}
    for kind in ('eis_fit', 'eis_parameters', 'eis_result'):
        exported = request(f'download?id={job["id"]}&kind={kind}', binary=True)
        assert exported
        exports[kind] = hashlib.sha256(exported).hexdigest()
    original = args.data / 'jobs' / job['id'] / 'source.csv'
    assert original.read_bytes() == raw
    proof = {'entry_version': session['entry_version'], 'evidence_type': 'synthetic_software_acceptance',
             'job_id': job['id'], 'workspace': workspace['id'], 'http_wsl_job': 'passed',
             'original_input_preserved': True, 'download_sha256': exports,
             'rmse_complex_ohm': result['rmse_complex_ohm'], 'lin_kk': result['lin_kk'],
             'parameters': result['parameters'], 'runtime_versions': result['runtime_versions']}
    (args.data / 'eis_verification.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
