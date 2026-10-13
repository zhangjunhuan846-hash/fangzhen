"""Isolated API smoke test with explicit synthetic descriptor data."""
import argparse
import base64
import csv
import io
import json
from pathlib import Path
import time
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, urlopen

def main():
    p = argparse.ArgumentParser(); p.add_argument('data', type=Path); a = p.parse_args()
    session = json.loads((a.data/'session.json').read_text(encoding='utf-8'))
    token = parse_qs(urlsplit(session['url']).fragment)['token'][0]
    def api(path, data=None):
        req = Request('http://127.0.0.1:%s/api/%s' % (session['port'], path),
                      data=json.dumps(data).encode() if data is not None else None,
                      headers={'X-Workbench-Token': token, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=30) as response:
            return json.load(response)
    def wait(job):
        for _ in range(90):
            j = next(r for r in api('jobs') if r['id'] == job['id'])
            if j['status'] not in ['queued', 'running']:
                if j['status'] != 'completed':
                    raise AssertionError((j, api('joblog?id=' + j['id'])))
                return j
            time.sleep(1)
        raise TimeoutError('ML worker did not finish')
    workspace = api('create', {'name': '合成描述符软件验收'})
    stream = io.StringIO(); writer = csv.writer(stream)
    writer.writerow(['record_id', 'group_id', 'batch_id', 'temperature_C', 'concentration', 'true_density_g_cm3', 'capacity'])
    for i in range(24):
        writer.writerow(['sample'+str(i), 'condition'+str(i), 'A', 500+20*i, 1+(i%4)*.25, 2.1+.002*i, 250+.12*20*i-3*(1+(i%4)*.25)])
    raw = base64.b64encode(stream.getvalue().encode()).decode()
    config = {'target': 'capacity', 'purpose': 'process', 'features': ['temperature_C', 'concentration'],
              'roles': {'temperature_C': 'process', 'concentration': 'process'}, 'selector': 'spearman', 'top_k': 2,
              'validation': 'group', 'noise_fraction': .05}
    preview = api('mlpreview', {'workspace': workspace['id'], 'config': config, 'content': raw})
    assert len(preview['rows']) == 24
    model = wait(api('job', {'workspace': workspace['id'], 'mode': 'ml_train', 'content': raw, 'ml_config': config}))
    assert len(model['result']['comparisons']) == 6 and len(model['result']['oof']) == 24
    candidates = base64.b64encode(b'record_id,batch_id,temperature_C,concentration\nnew,A,710,1.2\nother,A,850,1.4\n').decode()
    predicted = wait(api('job', {'workspace': workspace['id'], 'mode': 'ml_predict', 'parent': model['id'], 'content': candidates}))
    recommended = wait(api('job', {'workspace': workspace['id'], 'mode': 'ml_recommend', 'parent': model['id'], 'content': candidates}))
    assert len(predicted['result']['predictions']) == 2 and recommended['result']['selected']
    tables = workspace['tables']
    for i in range(12):
        tables['处理工艺'].append({'sample_id': 'sample'+str(i), 'batch_id': 'A', 'method': 'heat', 'temperature_C': 500+20*i})
        tables['表征'].append({'sample_id': 'sample'+str(i), 'true_density_g_cm3': 2.1+.002*i, 'bet_m2_g': 10-.2*i})
    workspace = api('save', {'id': workspace['id'], 'revision': workspace['revision'], 'tables': tables})
    joined = api('mlpreview', {'workspace': workspace['id'], 'config': {'target': '表征.true_density_g_cm3'}})
    assert len(joined['rows']) == 12
    report = {'scope': 'synthetic software validation, not recovered graphite experiments',
              'workspace': workspace['id'], 'model_job': model['id'], 'prediction_job': predicted['id'],
              'recommendation_job': recommended['id'], 'comparisons': 'passed', 'csv_preview': 'passed',
              'workspace_join': 'passed', 'saved_model_predict': 'passed', 'candidate_recommend': 'passed'}
    (a.data/'ml_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (a.data/'合成建模数据.csv').write_text(stream.getvalue(), encoding='utf-8-sig')
    print(json.dumps(report, ensure_ascii=False))

if __name__ == '__main__':
    main()
