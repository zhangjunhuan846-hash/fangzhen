"""Packaged workstation -> WSL public cross-cell and cold-temperature checks."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import parse_qs,urlsplit
from urllib.request import Request,urlopen


def main():
    root=Path(__file__).resolve().parents[2]
    exe=root/'outputs/fangzhen_workbench_cold_20261029/FangzhenResearch/FangzhenResearch.exe'
    with tempfile.TemporaryDirectory(prefix='cold_crosscell_smoke_') as data:
        proc=subprocess.Popen([str(exe),'--data',data,'--project',str(root),'--no-browser',],
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            path=Path(data)/'session.json'
            for _ in range(150):
                if path.exists():break
                if proc.poll() is not None:raise RuntimeError('workbench exited')
                time.sleep(.1)
            session=json.loads(path.read_text(encoding='utf8'));token=parse_qs(urlsplit(session['url']).fragment)['token'][0]
            url=f'http://127.0.0.1:{session["port"]}/api/'
            def req(endpoint,body=None):
                request=Request(url+endpoint,data=json.dumps(body).encode() if body is not None else None,
                    headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
                with urlopen(request,timeout=60) as response:return json.load(response)
            workspace=req('create',{'name':'低温与跨电芯验证验收'})['id']
            entries={e['action']:e for e in req('engineering_catalog')}
            jobs=[]
            for action in ('crosscell_validation','tesla_refined'):
                assert entries[action]['configured']
                jobs.append((action,req('job',{'workspace':workspace,'mode':'engineering','engineering_config':entries[action]['defaults']})))
            pending={job['id']:action for action,job in jobs}
            for _ in range(800):
                status={x['id']:x for x in req('jobs')}
                for job_id,action in list(pending.items()):
                    found=status[job_id]
                    if found['status']=='failed':raise AssertionError(req('joblog?id='+job_id))
                    if found['status']=='completed':
                        metrics=found['result']['metrics']
                        assert (metrics['test_cells']==3 if action=='crosscell_validation' else metrics['test_cell']=='m1000')
                        file='crosscell_validation.json' if action=='crosscell_validation' else 'tesla_validation.json'
                        assert (Path(data)/'jobs'/job_id/'physics'/file).is_file()
                        print(action,'completed',flush=True);del pending[job_id]
                if not pending:break
                time.sleep(.5)
            if pending:raise TimeoutError('Public validation task did not finish')
            print('packaged HTTP -> WSL: low temperature and cross-cell validations passed')
        finally:
            proc.terminate();proc.wait(timeout=10)


if __name__=='__main__':main()
