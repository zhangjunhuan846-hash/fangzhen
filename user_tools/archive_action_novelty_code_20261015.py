"""Read-only author-repository receipts for the scoped novelty check."""
import datetime
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT=Path('outputs/analysis/action_novelty_20261015')


def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Research prior-art check; urllib'})
    with urllib.request.urlopen(req,timeout=25) as response: return response.read()


def main():
    out=ROOT/'author_code';out.mkdir(exist_ok=False);rows=[]
    for repo in ['SchroDeCat/rMFBO','huangdaolang/amortized-decision-aware-bed']:
        row={'repo':repo,'executed':False,'scope':'Repository metadata and README only; no reproduction claim'}
        try:
            meta=json.loads(get('https://api.github.com/repos/'+repo))
            branch=meta['default_branch']
            commit=json.loads(get(f'https://api.github.com/repos/{repo}/commits/{branch}'))['sha']
            raw=get(f'https://raw.githubusercontent.com/{repo}/{commit}/README.md')
            path=out/(repo.replace('/','__')+'__README.md');path.write_bytes(raw)
            row.update(status='saved',commit=commit,readme=str(path),sha256=hashlib.sha256(raw).hexdigest(),
                       license=(meta.get('license') or {}).get('spdx_id'),
                       url=f'https://github.com/{repo}/tree/{commit}')
        except Exception as exc: row.update(status='unavailable',error=f'{type(exc).__name__}: {exc}')
        rows.append(row)
    result={'recorded_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'repositories':rows}
    (out/'index.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
