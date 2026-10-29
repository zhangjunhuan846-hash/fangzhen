"""Windows HTTP -> isolated WSL runtimes -> actual artifacts acceptance."""
import argparse
import base64
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from user_tools.workbench.engineering_contracts import defaults


def main():
    parser=argparse.ArgumentParser();parser.add_argument('data',type=Path);args=parser.parse_args()
    session=json.loads((args.data/'session.json').read_text(encoding='utf-8'))
    token=parse_qs(urlsplit(session['url']).fragment)['token'][0]
    base=f'http://127.0.0.1:{session["port"]}/api/'
    def api(path,body=None,binary=False):
        req=Request(base+path,data=json.dumps(body).encode() if body is not None else None,
                    headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
        with urlopen(req,timeout=30) as response:return response.read() if binary else json.load(response)
    workspace=api('create',{'name':'工程扩展软件验收 · 合成与公开生成数据'})
    assert len(api('engineering_catalog'))==15
    evidence=[]
    def execute(config,raw=None,**extra):
        payload={'workspace':workspace['id'],'mode':'engineering','engineering_config':config,**extra}
        if raw is not None:payload['content']=base64.b64encode(raw).decode()
        job=api('job',payload)
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            current=next(j for j in api('jobs') if j['id']==job['id'])
            if current['status'] not in ['queued','running']:break
            time.sleep(.5)
        if current['status']!='completed':
            raise AssertionError({'job':current,'log':api('joblog?id='+job['id'])})
        r=current['result'];assert r['material_validation'] is False and r['hardware_connected'] is False
        assert r['action']==config['action']
        downloads={}
        for kind in ['engineering_csv','engineering_result','engineering_config']:
            data=api('download?id='+job['id']+'&kind='+kind,binary=True)
            assert data;downloads[kind]=hashlib.sha256(data).hexdigest()
        if raw is not None:
            assert (args.data/'jobs'/job['id']/'source.csv').read_bytes()==raw
            assert r['source_sha256']==hashlib.sha256(raw).hexdigest()
        evidence.append({'id':job['id'],'action':r['action'],'algorithm':r.get('algorithm'),
                         'evidence_type':r['evidence_type'],'metrics':r['metrics'],'downloads':downloads,
                         'runtime_versions':r['runtime_versions']})
        print(r['action'],r.get('algorithm',''),job['id'],'passed',flush=True)
        return current
    for action in ['ecm_bms','mpc','eis_joint','pack','batteryml','faults','cycler','can']:
        c=defaults(action);c['steps']=12
        j=execute(c)
        if action=='mpc':
            assert j['result']['metrics']['fallback_count']==0
            assert j['result']['metrics']['plant_violation_count']==0
        if action=='pack':
            data=api('download?id='+j['id']+'&kind=engineering_csv',binary=True).decode('utf-8-sig')
            rows=list(csv.DictReader(io.StringIO(data)))
            assert max(abs(float(r['kcl_residual_A'])) for r in rows)<1e-6
            assert 6<float(rows[-1]['pack_voltage_V'])<8.5
    for algorithm in ['qlognehvi','hvkg','psbax','mfkg','mfmes','gibbon','qlogei','dynmeanbo','safeopt']:
        c=defaults('optimize');c['algorithm']=algorithm;execute(c)
    # End-to-end EIS -> RC bridge -> Thevenin/SOX, in the same workspace.
    text=io.StringIO();writer=csv.writer(text);writer.writerow(['frequency_Hz','Z_real_ohm','Z_imag_ohm'])
    for i in range(81):
        f=10**(-4+i/10);z=.012+.025/(1+2j*math.pi*f*.025*1500);writer.writerow([f,z.real,z.imag])
    parent=api('job',{'workspace':workspace['id'],'mode':'eis_fit','content':base64.b64encode(text.getvalue().encode()).decode(),
                      'eis_config':{'frequency_unit':'Hz','impedance_unit':'ohm','circuit':'1rc'}})
    for _ in range(120):
        parent=next(j for j in api('jobs') if j['id']==parent['id'])
        if parent['status'] not in ['queued','running']:break
        time.sleep(.5)
    assert parent['status']=='completed',parent
    c=defaults('ecm_bms');c.update(steps=12,same_cell_eis_confirmed=True,eis_operating_soc=.8,eis_operating_temperature_C=25)
    j=execute(c,eis_parent=parent['id']);assert j['result']['eis_parameter_source']['job_id']==parent['id']
    can_job=execute(defaults('can'),telemetry_parent=j['id'])
    assert can_job['result']['telemetry_parameter_source']['job_id']==j['id']
    assert can_job['result']['metrics']['frames']==13
    public=Path('data/vendor_assets/ch_fault_smoke.csv')
    if public.exists():
        c=defaults('faults');c.update(data_origin='public',source='https://github.com/CH-BatteryGen/dataset-warehouse/releases/tag/v1.0.0',dataset_kind='official_AI_generated')
        j=execute(c,public.read_bytes());assert j['result']['dataset_kind']=='official_AI_generated'
    proof={'entry_version':session['entry_version'],'workspace':workspace['id'],'tasks':evidence,
           'eis_parent':parent['id'],'http_wsl_downloads':'passed','hardware_connected':False,'material_validation':False}
    (args.data/'engineering_verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Verified engineering tasks:',len(evidence))


if __name__=='__main__':main()
