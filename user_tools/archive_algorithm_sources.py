"""Read-only GitHub source snapshots. No upstream scripts are executed."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
import zipfile
import io

REPOS=[('hallemans_2025','https://github.com/Battery-Intelligence-Lab/Hallemans-2025-JES.git',None),
       ('basq','https://github.com/ma921/BASQ.git',None),
       ('botorch','https://github.com/meta-pytorch/botorch.git',None),
       ('be_cbo','https://github.com/yunshengtian/BE-CBO.git',None),
       ('imfbo','https://github.com/QianLab/iMFBO.git',None),
       ('sc_cp','https://github.com/larsvanderlaan/selfcalibratingconformal.git',None),
       ('boed_pyro','https://github.com/ae-foster/pyro.git','vboed-reproduce')]


def main():
    root=Path(__file__).resolve().parents[1]/'data/external/algorithm_sources_20261013';root.mkdir(parents=True,exist_ok=True)
    def fetch(item):
        key,url,branch=item;dest=root/key
        required={'hallemans_2025':'Fig10_EIS_Fitting_LGM50LT.py','basq':'BASQ/_basq.py','botorch':'botorch/acquisition/multi_objective/monte_carlo.py',
                  'be_cbo':'algorithms/becbo/becbo.py','imfbo':'acquisition_function.py','sc_cp':'selfcalibratingconformal/regression.py','boed_pyro':'pyro/contrib/oed/eig.py'}[key]
        if not (dest/required).exists():
            cmd=['git','clone','--depth','1','--filter=blob:none']
            if branch:cmd+=['--branch',branch]
            if dest.exists():result=subprocess.CompletedProcess(cmd,1,b'',b'partial checkout preserved')
            else:
                try:result=subprocess.run(cmd+[url,str(dest)],capture_output=True,timeout=40)
                except subprocess.TimeoutExpired:result=subprocess.CompletedProcess(cmd,1,b'',b'clone timed out')
            if result.returncode:
                owner_repo=url.split('github.com/')[1].removesuffix('.git')
                try:
                    def request(address):return urllib.request.urlopen(urllib.request.Request(address,headers={'User-Agent':'fangzhen-paper-study'}),timeout=45)
                    try:sha=subprocess.check_output(['git','-C',str(dest),'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL,timeout=5).strip()
                    except Exception:
                        with request('https://api.github.com/repos/'+owner_repo+'/commits/'+(branch or 'HEAD')) as response:sha=json.load(response)['sha']
                    archive_url='https://codeload.github.com/'+owner_repo+'/zip/'+sha
                    with request(archive_url) as response:raw=response.read(60_000_001)
                    if len(raw)>60_000_000:raise ValueError('source archive exceeds60MB')
                    with zipfile.ZipFile(io.BytesIO(raw)) as zipped:
                        if sum(e.file_size for e in zipped.infolist())>300_000_000:raise ValueError('expanded archive exceeds300MB')
                        if dest.exists():dest=root/(key+'_pinned')
                        dest.mkdir(parents=True,exist_ok=True)
                        for entry in zipped.infolist():
                            relative=Path(*Path(entry.filename).parts[1:]);target=(dest/relative).resolve()
                            if not target.is_relative_to(dest.resolve()) or ((entry.external_attr>>16)&0o170000)==0o120000:raise ValueError('unsafe archive entry')
                            if entry.is_dir():target.mkdir(parents=True,exist_ok=True)
                            else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(zipped.read(entry))
                    (root/(key+'.zip')).write_bytes(raw)
                    (dest/'UPSTREAM_SNAPSHOT.json').write_text(json.dumps({'commit':sha,'url':archive_url,'sha256':hashlib.sha256(raw).hexdigest()}),encoding='utf-8')
                except Exception as exc:return {'id':key,'url':url,'status':'failed','reason':str(exc)}
        if (dest/'UPSTREAM_SNAPSHOT.json').exists():sha=json.loads((dest/'UPSTREAM_SNAPSHOT.json').read_text(encoding='utf-8'))['commit']
        else:sha=subprocess.check_output(['git','-C',str(dest),'rev-parse','HEAD'],text=True).strip()
        paths=[p for p in dest.glob('*') if p.is_file() and ('licen' in p.name.lower() or p.name.lower().startswith('readme') or p.name in ['requirements.txt','pyproject.toml','setup.py'])]
        return {'id':key,'url':url,'commit':sha,'status':'archived','path':str(dest),
                'metadata_files':[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]}
    with ThreadPoolExecutor(max_workers=3) as pool:records=list(pool.map(fetch,REPOS))
    (root/'source_manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:r[k] for k in ['id','status']} for r in records]))


if __name__=='__main__':main()
