"""Packaged GUI server -> EIS grid -> SOC estimator smoke with synthetic spectra."""
import base64
import csv
import io
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import parse_qs,urlsplit
from urllib.request import Request,urlopen


def main():
    root=Path(__file__).resolve().parents[2]
    exe=root/'outputs/fangzhen_workbench_eis_bms_20261029/FangzhenResearch/FangzhenResearch.exe'
    with tempfile.TemporaryDirectory(prefix='eis_grid_smoke_') as data:
        process=subprocess.Popen([str(exe),'--data',data,'--project',str(root),'--no-browser'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            path=Path(data)/'session.json'
            for _ in range(150):
                if path.exists():break
                if process.poll() is not None:raise RuntimeError('workbench exited')
                time.sleep(.1)
            sess=json.loads(path.read_text(encoding='utf8'));token=parse_qs(urlsplit(sess['url']).fragment)['token'][0]
            base=f'http://127.0.0.1:{sess["port"]}/api/'
            def request(endpoint,body=None):
                req=Request(base+endpoint,data=json.dumps(body).encode() if body is not None else None,
                    headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
                with urlopen(req,timeout=60) as response:return json.load(response)
            workspace=request('create',{'name':'EIS网格回放合成验收'})['id']
            catalog=request('engineering_catalog');configs={e['action']:e['defaults'] for e in catalog}
            buffer=io.StringIO(newline='');w=csv.writer(buffer)
            w.writerow(['cell_id','spectrum_id','role','soc','temperature_C','frequency_Hz','Z_real_ohm','Z_imag_ohm'])
            for soc,role in [(.2,'train'),(.8,'train'),(.5,'test')]:
                r=.02+.01*soc
                for i in range(28):
                    f=.5*(2800**(i/27));z=.012+r/(1+2j*math.pi*f*r*1500)
                    w.writerow(['synthetic-5Ah-1RC',f's{soc}',role,soc,25,f,z.real,z.imag])
            def wait(job):
                for _ in range(180):
                    found=next(x for x in request('jobs') if x['id']==job['id'])
                    if found['status'] in ('completed','failed'):return found
                    time.sleep(.5)
                raise TimeoutError('task did not finish')
            configs['eis_grid']['interpolation']='log_invT'
            grid=wait(request('job',{'workspace':workspace,'mode':'engineering','engineering_config':configs['eis_grid'],
                'content':base64.b64encode(buffer.getvalue().encode()).decode()}))
            if grid['status']!='completed':raise AssertionError(request('joblog?id='+grid['id']))
            assert grid['result']['grid_usable_for_replay']
            cfg=configs['ecm_bms'];cfg['cell']['initial_soc']=.5;cfg['cell']['isothermal']=True;cfg['steps']=5;cfg['same_cell_eis_confirmed']=True;cfg['filter_rc_mode']='estimated_grid'
            replay=wait(request('job',{'workspace':workspace,'mode':'engineering','engineering_config':cfg,'eis_grid_parent':grid['id']}))
            if replay['status']!='completed':raise AssertionError(request('joblog?id='+replay['id']))
            assert replay['result']['eis_grid_source']['job_id']==grid['id']
            assert replay['result']['points']==6
            assert 'estimated SOC' in replay['result']['filter_model']
            print('packaged HTTP -> WSL: EIS grid, holdout gate, BMS bridge and synthetic replay passed')
        finally:
            process.terminate();process.wait(timeout=10)


if __name__=='__main__':main()
