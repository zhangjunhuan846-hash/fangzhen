"""Verify packaged UI -> public-case worker -> full trace and charts."""
import json
from pathlib import Path
import subprocess,tempfile,time
from urllib.parse import parse_qs,urlsplit
from urllib.request import Request,urlopen

def main():
    root=Path(__file__).resolve().parents[2]
    exe=root/'outputs/fangzhen_workbench_stanford_20261029_v2/FangzhenResearch/FangzhenResearch.exe'
    with tempfile.TemporaryDirectory(prefix='stanford_workstation_') as data:
        proc=subprocess.Popen([str(exe),'--data',data,'--project',str(root),'--no-browser'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            session=Path(data)/'session.json'
            for _ in range(200):
                if session.exists():break
                if proc.poll() is not None:raise RuntimeError('application exited')
                time.sleep(.1)
            x=json.loads(session.read_text(encoding='utf8'));token=parse_qs(urlsplit(x['url']).fragment)['token'][0];base=f'http://127.0.0.1:{x["port"]}/api/'
            def request(endpoint,body=None):
                req=Request(base+endpoint,data=json.dumps(body).encode() if body is not None else None,
                    headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
                with urlopen(req,timeout=60) as r:return json.load(r)
            workspace=request('create',{'name':'Stanford公开电芯验收'})['id'];entries={e['action']:e for e in request('engineering_catalog')}
            assert entries['stanford_frozen']['configured'];jobs=[]
            for case in ('W8_2','W5_1'):
                cfg=dict(entries['stanford_frozen']['defaults'],case=case)
                jobs.append((case,request('job',{'workspace':workspace,'mode':'engineering','engineering_config':cfg})))
            pending={job['id']:case for case,job in jobs}
            for _ in range(600):
                status={j['id']:j for j in request('jobs')}
                for job_id,case in list(pending.items()):
                    found=status[job_id]
                    if found['status']=='failed':raise AssertionError(request('joblog?id='+job_id))
                    if found['status']=='completed':
                        result=found['result'];assert result['details']['cell']==case[:2] and not result['details']['eis_used']
                        assert result['metrics']['动态覆盖率']==1.0
                        out=Path(data)/'jobs'/job_id/'physics';assert (out/'engineering.csv').is_file()
                        assert (out/'stanford_model.json').is_file() and (out/'stanford_selection.json').is_file()
                        ui=json.loads((out/'ui_result.json').read_text(encoding='utf8'));assert len(ui['curves'])==2
                        print(case,'RMSE',result['metrics']['动态电压RMSE_mV'],flush=True);del pending[job_id]
                if not pending:break
                time.sleep(.5)
            if pending:raise TimeoutError('case did not finish')
            print('packaged HTTP -> WSL -> trace/chart: pass',flush=True)
        finally:
            proc.terminate();proc.wait(timeout=10)
if __name__=='__main__':main()
