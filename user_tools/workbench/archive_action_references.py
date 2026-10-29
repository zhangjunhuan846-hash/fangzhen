"""Small primary-source archive; no repository cloning or dependency installs."""
import hashlib
import json
from pathlib import Path
import urllib.request

def fetch(url):
    request=urllib.request.Request(url,headers={'User-Agent':'fangzhen-scientific-validation/1.0'})
    with urllib.request.urlopen(request,timeout=35) as response: return response.read()

def main():
    root=Path('outputs/analysis/action_study_20261015/references'); root.mkdir(parents=True,exist_ok=False)
    rows=[]
    files={
        'correlated_KG_2009.pdf':'https://optimallearning.princeton.edu/Papers/Frazier%20Powell%20Dayanik%20CorrelatedKnowledgeGradientJOC.pdf',
        'HVKG_2023.pdf':'https://proceedings.mlr.press/v202/daulton23a/daulton23a.pdf',
        'budgeted_BO_2021.pdf':'https://proceedings.neurips.cc/paper_files/paper/2021/file/a8ecbabae151abacba7dbde04f761c37-Paper.pdf',
        'budgeted_BO_2021_supplement.pdf':'https://proceedings.neurips.cc/paper_files/paper/2021/file/a8ecbabae151abacba7dbde04f761c37-Supplemental.pdf'}
    for name,url in files.items():
        try:
            data=fetch(url); (root/name).write_bytes(data)
            rows.append({'file':name,'url':url,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
        except Exception as exc: rows.append({'file':name,'url':url,'error':str(exc)})
    repo='meta-pytorch/botorch'
    try:
        metadata=fetch('https://api.github.com/repos/'+repo+'/commits/main')
        (root/'botorch_commit.json').write_bytes(metadata)
        sha=json.loads(metadata)['sha']
        for name in ['knowledge_gradient','cost_aware']:
            url=f'https://raw.githubusercontent.com/{repo}/{sha}/botorch/acquisition/{name}.py'
            data=fetch(url); path=root/(name+'.py'); path.write_bytes(data)
            rows.append({'file':path.name,'url':url,'commit':sha,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
    except Exception as exc: rows.append({'repository':repo,'error':str(exc)})
    (root/'index.json').write_text(json.dumps({'retrieved_date':'2026-10-15','sources':rows},indent=2),encoding='utf-8')
    print(json.dumps(rows,ensure_ascii=False))
if __name__=='__main__': main()
