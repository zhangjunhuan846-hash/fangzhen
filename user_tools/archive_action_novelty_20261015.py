"""Archive a bounded set of primary papers for a concept-level novelty check."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import urllib.request
from pypdf import PdfReader

ROOT = Path('outputs/analysis/action_novelty_20261015')


class TextReader(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.skip += 1
        if tag in ('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'li', 'div', 'section'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.skip = max(0, self.skip-1)
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


def fetch(item, kind):
    url = item[kind]
    row = {'paper_id': item['id'], 'kind': kind, 'url': url}
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'Research primary-source archival; urllib'})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(); row['resolved_url'] = response.url
        path = ROOT/'references'/f'{item["id"]}.{kind}'
        if kind == 'pdf':
            if not raw.startswith(b'%PDF'): raise ValueError('Response is not a PDF; no challenge page saved as paper')
            reader = PdfReader(io.BytesIO(raw)); row['pages'] = len(reader.pages)
            text = '\n\n'.join(f'--- PDF page {i+1} ---\n'+(p.extract_text() or '') for i,p in enumerate(reader.pages))
        else:
            parser = TextReader(); parser.feed(raw.decode('utf-8'))
            text = '\n'.join(x.strip() for x in ''.join(parser.parts).splitlines() if x.strip())
            if 'arXiv' not in text: raise ValueError('Not recognized as arXiv full text')
        path.write_bytes(raw)
        (path.with_suffix('.'+kind+'.txt')).write_text(text, encoding='utf-8')
        row.update(status='saved', file=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    except Exception as exc:
        row.update(status='unavailable', error=f'{type(exc).__name__}: {exc}')
    return row


def main():
    items=json.loads((ROOT/'sources_requested.json').read_text(encoding='utf-8'))['sources']
    (ROOT/'references').mkdir(exist_ok=False)
    rows=[]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures=[pool.submit(fetch,item,kind) for item in items for kind in ('pdf','html') if kind in item]
        for future in as_completed(futures):
            row=future.result(); rows.append(row)
            print(json.dumps({k:v for k,v in row.items() if k in ('paper_id','kind','status','pages','error')},ensure_ascii=True),flush=True)
    output={'recorded_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'sources':items,'retrievals':sorted(rows,key=lambda r:(r['paper_id'],r['kind'])),
            'limits':'Primary-source archive, not a systematic-review completeness guarantee. PDFs/code are not executed.'}
    (ROOT/'references/index.json').write_text(json.dumps(output,indent=2),encoding='utf-8')


if __name__=='__main__': main()
