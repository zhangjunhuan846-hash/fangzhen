"""Smoke test the packaged server through HTTP and its WSL tools."""
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen


def main():
    root=Path(__file__).resolve().parents[2]
    exe=root/'outputs/fangzhen_workbench_research_20261029_final/FangzhenResearch/FangzhenResearch.exe'
    with tempfile.TemporaryDirectory(prefix='battery_research_smoke_') as data:
        process=subprocess.Popen([str(exe),'--data',data,'--project',str(root),'--no-browser'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            session_file=Path(data)/'session.json'
            for _ in range(150):
                if session_file.exists():break
                if process.poll() is not None:raise RuntimeError('workbench exited')
                time.sleep(.1)
            session=json.loads(session_file.read_text(encoding='utf8'))
            token=parse_qs(urlsplit(session['url']).fragment)['token'][0]
            base=f'http://127.0.0.1:{session["port"]}/api/'
            def request(path,body):
                req=Request(base+path,data=json.dumps(body).encode(),headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
                with urlopen(req,timeout=180) as response:return json.load(response)
            workspace=request('create',{'name':'临时软件验证'})['id']
            def run(kind,raw,config,parent=None):
                return request('multichem',{'workspace':workspace,'kind':kind,'filename':'example.csv',
                    'content':base64.b64encode(raw.encode()).decode(),'config':config,'parent':parent})
            plan=run('helao_plan','experiment_name,temperature_C\ncarbonize,900\n',{})
            assert plan['result']['sequence']['planned_experiments'][0]['experiment_params']['temperature_C']==900
            ax=run('ax_recommend','x,y\n1,1\n2,4\n3,6\n4,8\n5,9\n6,10\n',
                   {'parameters':[{'name':'x','bounds':[0,10]}],'objectives':[{'name':'y'}]})
            assert ax['result']['generator']=='BoTorch'
            audit='role,group_id,predicted,observed,x\n'+''.join(f'{role},{role}{i},{.7+i*.001},{.72+i*.002},{i/12}\n' for role in ['reference','calibration','test'] for i in range(12))
            result=run('uncertainty_audit',audit,{'feature_columns':['x']})
            assert set(result['result']['methods'])=={'rsa_cp','kmm_cp','split_cp'}
            header='doi,mapping_found,ice,carbonization_temperature_C,d002_nm,id_ig,ssa_m2_g,electrolyte_type,current_density_mA_g\n'
            train=header+''.join(f'paper{i//2},True,{.7+i*.005},{800+i*10},{.35+i*.001},1.1,{10+i},1,20\n' for i in range(20))
            job=run('hardcarbon_train',train,{'algorithms':['mean','ridge']})
            raw='record_id,carbonization_temperature_C,d002_nm,id_ig,ssa_m2_g,electrolyte_type,current_density_mA_g\na,900,0.38,1.1,10,1,20\n'
            explained=run('hardcarbon_shap',raw,{},job['job']['id'])
            assert explained['result']['backend']=='SHAP permutation'
            print('packaged HTTP → WSL: HELAO, Ax BoTorch, RSA/KMM and SHAP passed')
        finally:
            process.terminate();process.wait(timeout=10)


if __name__=='__main__':main()
