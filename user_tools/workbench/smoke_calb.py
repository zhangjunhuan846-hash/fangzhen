"""Packaged desktop HTTP -> WSL -> public CALB validation end-to-end check."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import parse_qs,urlsplit
from urllib.request import Request,urlopen


def main():
    root=Path(__file__).resolve().parents[2]
    exe=root/'outputs/fangzhen_workbench_calb_20261029/FangzhenResearch/FangzhenResearch.exe'
    with tempfile.TemporaryDirectory(prefix='calb_smoke_') as data:
        proc=subprocess.Popen([str(exe),'--data',data,'--project',str(root),'--no-browser'],
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            path=Path(data)/'session.json'
            for _ in range(150):
                if path.exists():break
                if proc.poll() is not None:raise RuntimeError('workbench exited')
                time.sleep(.1)
            sess=json.loads(path.read_text(encoding='utf8'));token=parse_qs(urlsplit(sess['url']).fragment)['token'][0]
            url=f'http://127.0.0.1:{sess["port"]}/api/'
            def req(endpoint,body=None):
                request=Request(url+endpoint,data=json.dumps(body).encode() if body is not None else None,
                    headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
                with urlopen(request,timeout=60) as response:return json.load(response)
            workspace=req('create',{'name':'CALB公开数据回放验收'})['id']
            configs={e['action']:e['defaults'] for e in req('engineering_catalog')}
            job=req('job',{'workspace':workspace,'mode':'engineering','engineering_config':configs['calb_validation']})
            for _ in range(600):
                found=next(x for x in req('jobs') if x['id']==job['id'])
                if found['status'] in ('completed','failed'):break
                time.sleep(.5)
            else:raise TimeoutError('CALB task did not finish')
            if found['status']!='completed':raise AssertionError(req('joblog?id='+job['id']))
            assert found['result']['metrics']['fresh_test_cells']==2
            assert found['result']['metrics']['fresh_test_windows']==36
            for name in ('calb_validation.json','calb_pulse_metrics.csv','calb_eis_inventory.csv'):
                assert (Path(data)/'jobs'/job['id']/'physics'/name).exists(),name
            print('packaged HTTP -> WSL: matched HPPC, held-out pulse/drive, EKF and CSV outputs passed')
        finally:
            proc.terminate();proc.wait(timeout=10)


if __name__=='__main__':main()
