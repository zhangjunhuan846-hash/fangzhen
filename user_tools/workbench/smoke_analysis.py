"""Smoke test a packaged server using an explicitly isolated test directory."""
import json
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlsplit,parse_qs


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('data',type=Path);args=parser.parse_args()
    session=json.loads((args.data/'session.json').read_text(encoding='utf-8'))
    token=parse_qs(urlsplit(session['url']).fragment)['token'][0];base=f'http://127.0.0.1:{session["port"]}/api/'
    def api(path,data=None):
        req=Request(base+path,data=json.dumps(data).encode() if data is not None else None,
                    headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
        with urlopen(req,timeout=30) as response:return json.load(response)
    boot=api('bootstrap');tables={t['sheet']:[] for t in boot['schema']['tables']}
    tables['原料']=[{'batch_id':'TEST','source':'合成界面测试'}]
    tables['处理工艺']=[{'sample_id':s,'batch_id':'TEST'} for s in ['A','B','C']]
    tables['半电池']=[{'cell_id':s+'-1','sample_id':s,'c_rate':1,'cycle':5,'capacity':q,
                       'first_lithiation':100,'first_delithiation':ice*100,'temperature_C':25}
                       for s,q,ice in [('A',310,.95),('B',330,.9),('C',300,.9)]]
    w=api('importjson',{'backup':{'name':'合成分析测试（非真实材料）','tables':tables}})
    p=api('analyze',{'workspace':w['id'],'config':{'kind':'pareto','c_rate':1,'cycle':5}})
    assert p['result']['front_count']==2
    c=api('analyze',{'workspace':w['id'],'config':{'kind':'capability','values':[98,100,102],'lsl':90}})
    assert abs(c['result']['index_estimate']-10/6)<1e-12
    # The new analysis record must survive subsequent reads.
    assert any(j['id']==p['id'] for j in api('jobs'))
    proof={'packaged_api':'passed','pareto_front':2,'capability':'passed','backup_restore':'passed','workspace':w['id']}
    (args.data/'verification.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    print(json.dumps(proof))


if __name__=='__main__':main()
