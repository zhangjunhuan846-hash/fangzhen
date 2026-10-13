"""Integration smoke test for v0.3.4; only run with an isolated --data directory."""
import base64
import json
from pathlib import Path
import time
from urllib.request import Request,urlopen
from urllib.parse import urlsplit,parse_qs


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('data',type=Path);args=parser.parse_args()
    session=json.loads((args.data/'session.json').read_text(encoding='utf-8'))
    token=parse_qs(urlsplit(session['url']).fragment)['token'][0];base=f'http://127.0.0.1:{session["port"]}/api/'
    def api(path,data=None,binary=False):
        req=Request(base+path,data=json.dumps(data).encode() if data is not None else None,
                    headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
        with urlopen(req,timeout=30) as response:return response.read() if binary else json.load(response)
    boot=api('bootstrap');tables={t['sheet']:[] for t in boot['schema']['tables']}
    tables['原料']=[{'batch_id':'TEST','source':'合成软件测试'}]
    tables['处理工艺']=[{'sample_id':'S','batch_id':'TEST'}]
    tables['极片']=[{'electrode_id':'E','sample_id':'S','area_cm2':2,'coating_mass_mg':10,'thickness_um':50,
                  'graphite_fraction':.9,'conductive_fraction':.05,'binder_fraction':.05,
                  'conductive_true_density_g_cm3':2,'binder_true_density_g_cm3':1.8}]
    tables['表征']=[{'sample_id':'S','true_density_g_cm3':2.2,'effective_radius_um':5,'radius_basis':'合成测试'}]
    tables['半电池']=[{'cell_id':'C','sample_id':'S','electrode_id':'E','current_mA':.1,'temperature_C':25,
                      'separator_thickness_um':25,'separator_porosity':.5,'electrolyte_concentration_mol_L':1,
                      'voltage_lower_V':.01,'voltage_upper_V':1.5}]
    tables['仿真输入']=[{'model_input_id':'M','sample_id':'S','initial_x0':.5,'c_max_mol_m3':30000,'ds_m2_s':1e-14,'i0_A_m2':1}]
    w=api('importjson',{'backup':{'name':'v034合成软件验收（非真实材料）','tables':tables}})
    original=b'time_s,Voltage(mV),Current(mA)\n0,200,.1\n1,201,.1\n'
    cleaned=api('preprocess',{'workspace':w['id'],'content':base64.b64encode(original).decode(),'filename':'synthetic.csv'})
    assert cleaned['result']['qc_pass'] and b'time_s,voltage_V,current_A' in api('download?id='+cleaned['id'],binary=True)
    ocp=api('ocp',{'workspace':w['id'],'content':base64.b64encode(b'stoichiometry,voltage_V\n.001,.8\n.5,.2\n.999,.08\n').decode(),'filename':'合成OCP.csv'})
    config={'kind':'sample','electrode_id':'E','cell_id':'C','ocp_job_id':ocp['id']}
    packet=api('analyze',{'workspace':w['id'],'config':config})
    assert packet['result']['candidate_complete'] and not packet['result']['physics_validation_passed']
    env=api('environment');assert env['physics_available']
    job=api('job',{'workspace':w['id'],'mode':'sample_forward','model':'SPM','sample_config':config,'accept_reference':True,'duration_s':100})
    for _ in range(60):
        current=next(j for j in api('jobs') if j['id']==job['id'])
        if current['status'] not in ['running','queued']:break
        time.sleep(1)
    assert current['status']=='completed',current
    assert current['curves'] and current['result']['current_A']==.0001 and not current['result']['independent_validation_passed']
    candidate_raw=b'candidate_id,x1,x2,capacity,ice,status\nA,0,0,300,.90,completed\nB,1,0,320,.89,completed\nC,0,1,310,.93,completed\nD,.5,.5,,,candidate\nE,1,1,,,pending\n'
    candidate=api('job',{'workspace':w['id'],'mode':'candidate_multi','model':'SPM','content':base64.b64encode(candidate_raw).decode(),
                        'same_batch':True,'noise':[5,.005],'reference':[0,0],'minimum':[0,.88]})
    for _ in range(60):
        candidate_current=next(j for j in api('jobs') if j['id']==candidate['id'])
        if candidate_current['status'] not in ['running','queued']:break
        time.sleep(1)
    assert candidate_current['status']=='completed' and candidate_current['result']['selected']['candidate_id']=='D',candidate_current
    report=api('report?id='+w['id'],binary=True);assert b'<svg' in report
    (args.data/'科研报告测试.html').write_bytes(report)
    proof={'packaged_api':'passed','preprocess':'passed','sample_parameters':'passed','sample_spm_actual_solve':'passed',
           'report':'passed','candidate_multi':'passed','environment':env,'workspace':w['id'],'job':job['id']}
    (args.data/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':main()
