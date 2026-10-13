"""Packaged API integration checks; isolated data only, no material claims."""
import base64
import io
import csv
import json
from pathlib import Path
import time
from urllib.parse import urlsplit,parse_qs
from urllib.request import Request,urlopen


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('data',type=Path);parser.add_argument('--mj1',type=Path);args=parser.parse_args()
    session=json.loads((args.data/'session.json').read_text(encoding='utf-8'));token=parse_qs(urlsplit(session['url']).fragment)['token'][0]
    base=f'http://127.0.0.1:{session["port"]}/api/'
    def api(path,data=None):
        req=Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
        with urlopen(req,timeout=30) as response:return json.load(response)
    def wait(job):
        for _ in range(120):
            current=next(j for j in api('jobs') if j['id']==job['id'])
            if current['status'] not in ['queued','running']:
                assert current['status']=='completed',current;return current
            time.sleep(1)
        raise RuntimeError('worker timed out')
    w=api('create',{'name':'论文方法软件验收（合成数据）'})
    spectra=api('papermethod',{'workspace':w['id'],'kind':'eis','content':base64.b64encode(b'frequency_Hz,Z_real_ohm,Z_imag_ohm\n1,.1,-.05\n10,.02,-.01\n').decode(),
                              'config':{'frequency_unit':'Hz','impedance_unit':'ohm'}})
    assert not spectra['result']['linearity_assessed'] and spectra['result']['eis_spectra']
    handle=io.StringIO();writer=csv.writer(handle);writer.writerow(['record_id','group_id','batch_id','protocol_id','role','predicted','observed'])
    for i in range(9):writer.writerow([f'c{i}',f'g{i}','A','1C','calibration',100,100+i])
    writer.writerow(['t','test','A','1C','test',100,103]);raw=base64.b64encode(handle.getvalue().encode()).decode()
    cal=api('papermethod',{'workspace':w['id'],'kind':'calibration','content':raw,'config':{'alpha':.1,'frozen_independent_model':True}})
    assert cal['result']['residual_threshold']==8
    small=api('papermethod',{'workspace':w['id'],'kind':'calibration','content':raw,'config':{'alpha':.05,'frozen_independent_model':True}})
    assert not small['result']['finite_interval'] and small['result']['empirical_test_coverage'] is None
    model=wait(api('job',{'workspace':w['id'],'mode':'eis_forward','model':'SPM','socs':[.5],'frequency_min_Hz':1,'frequency_max_Hz':1000,'frequency_points':5}))
    assert len(model['result']['eis_spectra'][0]['points'])==5
    candidates=b'candidate_id,x1,x2,capacity,ice,status\nA,0,0,300,.90,completed\nB,1,0,320,.89,completed\nC,0,1,310,.93,completed\nD,.5,.5,,,candidate\n'
    rec=wait(api('job',{'workspace':w['id'],'mode':'candidate_multi','model':'SPM','content':base64.b64encode(candidates).decode(),
                       'same_batch':True,'noise':[5,.005],'reference':[0,0],'minimum':[0,.88],'engine':'nehvi'}))
    assert rec['result']['engine']=='finite_q1_mc_nehvi' and rec['result']['selected']['candidate_id']=='D'
    proof={'eis_import':'passed','native_eis_worker':'passed','group_calibration':'passed','small_n_unbounded':'passed',
           'finite_nehvi_worker':'passed','workspace':w['id']}
    if args.mj1:
        parquet=wait(api('job',{'workspace':w['id'],'mode':'parquet_preprocess','model':'SPM','filename':args.mj1.name,'content':base64.b64encode(args.mj1.read_bytes()).decode()}))
        assert parquet['result']['valid_rows']>1_000_000 and not parquet['result']['eis_extracted']
        proof.update(mj1_parquet='passed',mj1_rows=parquet['result']['valid_rows'],mj1_qc=parquet['result']['qc_pass'],parquet_job=parquet['id'])
    (args.data/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':main()
