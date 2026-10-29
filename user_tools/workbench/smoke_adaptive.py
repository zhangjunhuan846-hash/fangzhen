"""Packaged app acceptance for adaptive PF -> MPC -> virtual CAN plus EIS/SIL."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs,urlsplit
from urllib.request import Request,urlopen

from user_tools.workbench.engineering_contracts import defaults


def main():
    parser=argparse.ArgumentParser();parser.add_argument('data',type=Path);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    session=json.loads((args.data/'session.json').read_text(encoding='utf-8'));token=parse_qs(urlsplit(session['url']).fragment)['token'][0]
    base='http://127.0.0.1:'+str(session['port'])+'/api/'
    def api(path,body=None,binary=False):
        req=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
        with urlopen(req,timeout=45) as r:return r.read() if binary else json.load(r)
    assert session['entry_version']=='0.3.14' and len(api('engineering_catalog'))==15
    workspace=api('create',{'name':'PF温度与老化更新 · v0.3.14最终验证'})
    inventory=api('hardware_readiness');assert inventory['hardware_connected'] is False and inventory['actuator_enabled'] is False
    (args.out/'hardware_inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    proof=dict(entry_version=session['entry_version'],workspace=workspace['id'],tasks=[],hardware_connected=False)
    def execute(config,**extra):
        job=api('job',dict(workspace=workspace['id'],mode='engineering',engineering_config=config,**extra));deadline=time.monotonic()+900
        while time.monotonic()<deadline:
            current=next(j for j in api('jobs') if j['id']==job['id'])
            if current['status'] not in ['running','queued']:break
            time.sleep(.7)
        if current['status']!='completed':raise AssertionError(dict(job=current,log=api('joblog?id='+job['id'])))
        result=current['result'];assert result['hardware_connected'] is False and result['material_validation'] is False
        downloads={};kinds=['engineering_result','engineering_csv','engineering_config']
        kinds += {'commercial_adaptive':['adaptive_model','adaptive_validation','adaptive_metrics','adaptive_control_config'],
                  'eis_audit':['eis_audit','eis_audit_metrics'],'safety_bench':['safety_cases','safety_trace','hardware_template']}.get(result['action'],[])
        for kind in kinds:
            raw=api('download?id='+job['id']+'&kind='+kind,binary=True);assert raw
            downloads[kind]=hashlib.sha256(raw).hexdigest()
        record=dict(job_id=job['id'],action=result['action'],metrics=result['metrics'],runtime_versions=result['runtime_versions'],downloads=downloads)
        proof['tasks'].append(record);(args.out/'desktop_acceptance.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
        print(result['action'],job['id'],result['metrics'],flush=True);return current
    adaptive=execute(defaults('commercial_adaptive'))
    eis=execute(defaults('eis_audit'));assert eis['result']['metrics']['unit_checks_passed']==14
    safety=execute(defaults('safety_bench'));assert safety['result']['metrics']['cases_passed']==12
    mpc=execute({'action':'mpc'},adaptive_parent=adaptive['id'])
    r=mpc['result'];assert r['adaptive_parameter_source']['job_id']==adaptive['id']
    assert r['adaptive_parameter_source']['frozen_model_sha256']==adaptive['result']['frozen_model_sha256']
    assert r['metrics']['plant_violation_count']==0 and r['metrics']['fallback_count']==0
    assert r['metrics']['final_estimated_soc']>=.8
    c=defaults('can');c.update(data_origin='public',source='same-workspace prior-cycle PF model -> MPC simulation telemetry')
    can=execute(c,telemetry_parent=mpc['id']);assert can['result']['telemetry_parameter_source']['job_id']==mpc['id']
    mpc_csv=api('download?id='+mpc['id']+'&kind=engineering_csv',binary=True).decode('utf-8-sig')
    assert can['result']['metrics']['frames']==len(list(csv.DictReader(io.StringIO(mpc_csv))))
    other=next(w for w in api('bootstrap')['workspaces'] if w['id']!=workspace['id'])
    try:api('job',dict(workspace=other['id'],mode='engineering',engineering_config={'action':'mpc'},adaptive_parent=adaptive['id']))
    except HTTPError as exc:assert exc.code==400;proof['cross_workspace_parent_rejected']=True
    else:raise AssertionError('Cross-workspace adaptive parameter source was accepted')
    (args.out/'desktop_acceptance.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Completed adaptive app acceptance:',len(proof['tasks']))


if __name__=='__main__':main()
