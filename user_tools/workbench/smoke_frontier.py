"""Packaged desktop -> actual WSL backends -> reviewable public-cell artifacts."""
import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.parse import parse_qs,urlsplit
from urllib.request import Request,urlopen

from user_tools.workbench.engineering_contracts import defaults


def main():
    parser=argparse.ArgumentParser();parser.add_argument('data',type=Path);parser.add_argument('--evidence',type=Path,required=True);parser.add_argument('--name',default='Panasonic PF公开电芯 · v0.3.13最终验证');args=parser.parse_args()
    session=json.loads((args.data/'session.json').read_text(encoding='utf-8'))
    token=parse_qs(urlsplit(session['url']).fragment)['token'][0]
    base=f'http://127.0.0.1:{session["port"]}/api/'
    def api(path,body=None,binary=False):
        request=Request(base+path,data=json.dumps(body).encode() if body is not None else None,
                        headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
        with urlopen(request,timeout=45) as response:return response.read() if binary else json.load(response)
    workspace=api('create',{'name':args.name})
    assert len(api('engineering_catalog'))==15
    proof=[]
    def execute(c,raw=None,mode='engineering',**extra):
        payload={'workspace':workspace['id'],'mode':mode,**extra}
        if mode=='engineering':payload['engineering_config']=c
        if raw is not None:payload['content']=base64.b64encode(raw).decode()
        j=api('job',payload);deadline=time.monotonic()+600
        while time.monotonic()<deadline:
            current=next(jj for jj in api('jobs') if jj['id']==j['id'])
            if current['status'] not in ['queued','running']:break
            time.sleep(.7)
        if current['status']!='completed':raise AssertionError({'job':current,'log':api('joblog?id='+j['id'])})
        result=current['result'];downloads={}
        kinds=['engineering_result','engineering_config','engineering_csv'] if mode=='engineering' else ['eis_result','eis_parameters','eis_fit']
        if mode=='engineering':
            kinds+= {'frontier':['engineering_frontier'],'batterylife':['engineering_life_split','engineering_life_checkpoint'],
                     'commercial_validation':['engineering_commercial','engineering_commercial_metrics','engineering_frozen','engineering_control_config']}.get(c['action'],[])
            assert result['hardware_connected'] is False and result['material_validation'] is False
        for kind in kinds:
            value=api('download?id='+j['id']+'&kind='+kind,binary=True);assert value
            downloads[kind]=hashlib.sha256(value).hexdigest()
        proof.append(dict(job_id=j['id'],mode=mode,action=result.get('action'),algorithm=result.get('algorithm'),
                  metrics=result.get('metrics'),downloads=downloads,runtime_versions=result.get('runtime_versions')))
        print(mode,result.get('title',result.get('action','EIS')),j['id'],'passed',flush=True)
        args.evidence.parent.mkdir(parents=True,exist_ok=True)
        args.evidence.write_text(json.dumps(dict(entry_version=session['entry_version'],workspace=workspace['id'],tasks=proof),ensure_ascii=False,indent=2),encoding='utf-8')
        return current
    # The three optimizer interface checks are explicitly synthetic; measured validation is separate.
    for algorithm in ['mobo_osd','rmfbo','camo']:
        c=defaults('frontier');c['algorithm']=algorithm;execute(c)
    for arch in ['CPMLP','CPTransformer']:
        c=defaults('batterylife');c['architecture']=arch;execute(c)
    commercial=execute(defaults('commercial_validation'))
    control=json.loads(api('download?id='+commercial['id']+'&kind=engineering_control_config',binary=True))
    mpc=execute(control)
    c=defaults('can');c.update(data_origin='public',source='同方案Panasonic PF MPC仿真遥测')
    execute(c,telemetry_parent=mpc['id'])
    # Instrument export has a generic [EIS] unit header. mOhm is recorded as a
    # scale assumption inferred from the ~20 reading and HPPC; no hardware calibration claim.
    path=Path('data/public/panasonic_pf_v1/25degC/EIS/3541_EIS00001.csv')
    lines=path.read_text(encoding='utf-8-sig').splitlines();start=next(i for i,l in enumerate(lines) if l.startswith('Time Stamp;'))
    records=list(csv.reader(lines[start:],delimiter=';'));header=records[0]
    text=io.StringIO();w=csv.writer(text);w.writerow(['frequency_Hz','Z_real_ohm','Z_imag_ohm'])
    for row in records[2:]:
        if len(row)<len(header)-1 or not row[header.index('ActFreq')]:continue
        w.writerow([float(row[header.index('ActFreq')]),float(row[header.index('Zreal1')])/1000,float(row[header.index('Zimg1')])/1000])
    eis=execute(None,text.getvalue().encode(),mode='eis_fit',eis_config={'frequency_unit':'Hz','impedance_unit':'ohm','circuit':'2rc','kk_mode':'automatic'})
    Path(args.evidence.parent/'eis_conversion_audit.json').write_text(json.dumps(dict(original_path=str(path),
         original_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),converted_csv_sha256=hashlib.sha256(text.getvalue().encode()).hexdigest(),
         scale_assumption='Digatron Zreal1/Zimg1 interpreted as mOhm; publisher unit row is generic [EIS]; confirmation still needed',
         eis_job=eis['id'],connected_to_earlier_drive_calibration=False),indent=2),encoding='utf-8')
    print('Completed desktop tasks:',len(proof),flush=True)


if __name__=='__main__':main()
