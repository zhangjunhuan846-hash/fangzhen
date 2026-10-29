"""Packaged HTTP -> WSL paired model, candidate and linked DFN smoke test."""
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import parse_qs,urlsplit
from urllib.request import Request,urlopen


def main():
    root=Path(__file__).resolve().parents[2]
    exe=root/'outputs/fangzhen_workbench_hardcarbon_dfn_20261029_v2/FangzhenResearch/FangzhenResearch.exe'
    with tempfile.TemporaryDirectory(prefix='hardcarbon_dfn_smoke_') as data:
        p=subprocess.Popen([str(exe),'--data',data,'--project',str(root),'--no-browser'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            session_file=Path(data)/'session.json'
            for _ in range(150):
                if session_file.exists():break
                if p.poll() is not None:raise RuntimeError('workbench exited')
                time.sleep(.1)
            session=json.loads(session_file.read_text(encoding='utf8'))
            token=parse_qs(urlsplit(session['url']).fragment)['token'][0]
            base=f'http://127.0.0.1:{session["port"]}/api/'
            def post(endpoint,body):
                req=Request(base+endpoint,data=json.dumps(body).encode(),headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
                with urlopen(req,timeout=240) as response:return json.load(response)
            workspace=post('create',{'name':'硬碳钠电临时验收'})['id']
            def run(kind,raw,config,parent=None):
                return post('multichem',{'workspace':workspace,'kind':kind,'filename':'test.csv','content':base64.b64encode(raw).decode(),'config':config,'parent':parent})
            header='doi,mapping_found,ice,reversible_capacity_mAh_g,carbonization_temperature_C,d002_nm,id_ig,ssa_m2_g,electrolyte_type,current_density_mA_g\n'
            raw=(header+''.join(f'paper{i//2},True,{.7+i*.005},{200+i},900,0.38,1.1,10,1,20\n' for i in range(20))).encode()
            training=run('hardcarbon_joint_train',raw,{'algorithms':['mean']})
            proc_header='doi,mapping_found,ice,reversible_capacity_mAh_g,carbonization_temperature_C,carbonization_time_h,heating_rate_C_min,current_density_mA_g\n'
            proc=(proc_header+''.join(f'paper{i},True,{.7+i*.01},{200+i*5},{800+i*20},2,3,20\n' for i in range(8))).encode()
            mobo=run('hardcarbon_ax_mobo',proc,{'parameters':[{'name':'carbonization_temperature_C','bounds':[700,1200]}],
                    'thresholds':{'ice':.5,'capacity_mAh_g':150}})
            assert mobo['result']['generator']=='BoTorch'
            candidates=b'record_id,carbonization_temperature_C,d002_nm,id_ig,ssa_m2_g,electrolyte_type,current_density_mA_g\na,900,0.38,1.1,10,1,20\nb,900,0.38,1.1,10,1,20\n'
            suggested=run('hardcarbon_joint_recommend',candidates,{'allow_exploratory':True},training['job']['id'])
            assert suggested['result']['pareto_enabled']
            dfn_raw=(root/'outputs/hardcarbon_dfn_validation/dfn_synthetic/input.csv').read_bytes()
            fitted=run('sodium_identify',dfn_raw,{'max_nfev':15,'candidate_id':'a'},suggested['job']['id'])
            assert fitted['result']['candidate_link']['candidate']['record_id']=='a'
            assert fitted['result']['solver_success']
            assert abs(fitted['result']['negative_diffusivity_scale']-2.)<.08
            print('packaged HTTP -> WSL: paired training, candidate link, synthetic DFN recovery passed')
        finally:
            p.terminate();p.wait(timeout=10)


if __name__=='__main__':main()
