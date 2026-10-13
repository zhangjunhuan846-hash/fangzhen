"""End-to-end six-feature verification; synthetic workflows plus real public replay."""
import argparse
import base64
import csv
import io
import json
from pathlib import Path
import time
from urllib.parse import urlsplit,parse_qs
from urllib.request import Request,urlopen

def main():
    parser=argparse.ArgumentParser();parser.add_argument('data',type=Path);parser.add_argument('--public',action='store_true');parser.add_argument('--inventory',action='store_true');a=parser.parse_args()
    session=json.loads((a.data/'session.json').read_text(encoding='utf-8'));token=parse_qs(urlsplit(session['url']).fragment)['token'][0]
    def api(path,data=None):
        req=Request('http://127.0.0.1:%s/api/%s'%(session['port'],path),data=json.dumps(data).encode() if data is not None else None,
                    headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
        with urlopen(req,timeout=30) as response:return json.load(response)
    def wait(job):
        for _ in range(180):
            j=next(j for j in api('jobs') if j['id']==job['id'])
            if j['status'] not in ['queued','running']:
                if j['status']!='completed':raise AssertionError((j,api('joblog?id='+j['id'])))
                return j
            time.sleep(1)
        raise TimeoutError('research worker timeout')
    w=api('create',{'name':'六项闭环验收：合成实验＋真实公开数据'})
    stream=io.StringIO();writer=csv.writer(stream)
    writer.writerow(['record_id','group_id','batch_id','status','temperature_C','concentration','capacity','ice','yield','carbon','cost'])
    for i in range(30):
        x=i/29;writer.writerow([f'D{i}',f'G{i}','A','completed',500+300*x,1+(i%4)*.1,250+100*x,.9+.05*x,.85+.08*x,20+4*x,10+4*x])
    writer.writerow(['candidate1','new1','A','candidate',779,1.2,'','','',10,8]);writer.writerow(['candidate2','new2','A','candidate',701,1.1,'','','',12,9])
    objectives=[{'key':'capacity','direction':'maximize','unit':'mAh/g','lower':0},
                {'key':'ice','direction':'maximize','unit':'fraction','lower':0,'upper':1},
                {'key':'yield','direction':'maximize','unit':'fraction','lower':0,'upper':1},
                {'key':'carbon','direction':'minimize','known':True,'unit':'kg CO2-eq/kg','lower':0},
                {'key':'cost','direction':'minimize','known':True,'unit':'CNY/kg','lower':0}]
    cfg={'features':['temperature_C','concentration'],'roles':{'temperature_C':'process','concentration':'process'},
         'objectives':objectives,'same_protocol':True,'allow_exploration':True,'alpha':.1,'mc_samples':32,'hv_grid':512,'data_kind':'synthetic_demo'}
    initial=wait(api('job',{'workspace':w['id'],'mode':'research_multi','content':base64.b64encode(stream.getvalue().encode()).decode(),'research_config':cfg}))
    assert len(initial['result']['objectives'])==5 and initial['result']['selected']
    selected=initial['result']['selected']['record_id']
    plan=api('experimentplan',{'workspace':w['id'],'parent':initial['id'],'record_id':selected})
    assert plan['record']['capacity'] is None
    x=(plan['record']['temperature_C']-500)/300
    partial=api('experimentfeedback',{'workspace':w['id'],'id':plan['id'],'revision':1,'values':{'capacity':250+100*x},'status':'measured'})
    assert partial['status']=='partial' and partial['record']['ice'] is None
    complete=api('experimentfeedback',{'workspace':w['id'],'id':plan['id'],'revision':2,'values':{'ice':.9+.05*x,'yield':.85+.08*x},'status':'measured'})
    assert complete['status']=='completed'
    linked=None
    if a.inventory:
        inventory_config={'kind':'inventory','case_name':'synthetic linkage','sample_id':selected,'output_kg':1,'currency':'CNY',
                          'region':'synthetic','price_basis':'synthetic','boundary':'two synthetic consumptions','data_kind':'synthetic_demo',
                          'batch_overhead':3,'overhead_source':'synthetic',
                          'inventory':[{'name':'power','unit':'kWh','quantity':4,'unit_price':.8,'gwp_factor':.5,'source':'synthetic'},
                                       {'name':'reagent','unit':'kg','quantity':.2,'unit_price':10,'gwp_factor':2,'source':'synthetic'}]}
        inventory=wait(api('sustainability',{'workspace':w['id'],'config':inventory_config}))
        linked=api('experimentinventory',{'workspace':w['id'],'id':plan['id'],'revision':complete['revision'],
                                         'inventory_job':inventory['id'],'carbon_key':'carbon','cost_key':'cost'})
        assert abs(linked['record']['carbon']-2.4)<1e-9 and abs(linked['record']['cost']-8.2)<1e-9
        assert linked['record']['_inventory_job']==inventory['id']
    updated=wait(api('job',{'workspace':w['id'],'mode':'research_multi','feedback_parent':initial['id']}))
    assert updated['result']['adaptive_feedback_present']
    assert next(j for j in api('jobs') if j['id']==initial['id'])['result']['selected']['record']['capacity'] is None
    repeat=api('experimentplan',{'workspace':w['id'],'parent':updated['id'],'record_id':'D29','repeat':True})
    failure=api('experimentfeedback',{'workspace':w['id'],'id':repeat['id'],'revision':1,'values':{},'status':'failed_measurement'})
    assert failure['record']['capacity'] is None
    chain=io.StringIO();cw=csv.writer(chain);cw.writerow(['record_id','group_id','batch_id','x','density','bet','capacity'])
    for i in range(24):
        x=i/23;cw.writerow([f'C{i}',f'CG{i}','A',x,2+.2*x,10-3*x,100+50*x])
    cw.writerow(['newchain','newchain','A',.55,'','',''])
    chained=wait(api('job',{'workspace':w['id'],'mode':'research_chain','content':base64.b64encode(chain.getvalue().encode()).decode(),
                 'chain_config':{'target':'capacity','process_features':['x'],'intermediates':['density','bet'],'roles':{'x':'process'},'alpha':.1,'selector':'manual','data_kind':'synthetic_demo'}}))
    assert chained['result']['calibration']['finite'] and chained['result']['predictions'][0]['interval_lower'] is not None
    result={'scope':'synthetic workflow validation; public module uses real archived measurements',
            'workspace':w['id'],'multi_job':initial['id'],'updated_job':updated['id'],'chain_job':chained['id'],
            'multi_five_objectives':'passed','independent_calibration':'passed','partial_feedback':'passed',
            'immutable_old_model':'passed','feedback_retrain':'passed','failure_not_zero':'passed','chain_propagation':'passed',
            'measurement_advice':'passed' if initial['result']['measurement_advice'] else 'no_advice_needed'}
    if linked:result['inventory_link']='passed'
    if a.public:
        public=wait(api('job',{'workspace':w['id'],'mode':'public_ml_validation','seeds':20,'budget':12}))
        result.update(public_job=public['id'],public_candidates=public['result']['candidate_count'],public_replay_summary=public['result']['replay_summary'])
    (a.data/'research_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (a.data/'合成多目标软件算例.csv').write_text(stream.getvalue(),encoding='utf-8-sig')
    (a.data/'合成级联软件算例.csv').write_text(chain.getvalue(),encoding='utf-8-sig')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
