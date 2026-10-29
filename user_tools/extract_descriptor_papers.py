"""Extract page-indexed text from the six archived user papers."""
from pathlib import Path
import json
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/descriptor_paper_study_20261013'

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'papers/descriptor_methods_20261013/manifest.json').read_text(encoding='utf-8'))
    for item in manifest:
        reader = PdfReader(item['path'])
        pages = [{'page': i + 1, 'text': page.extract_text() or ''} for i, page in enumerate(reader.pages)]
        name = Path(item['name']).stem
        (OUT / (name + '.pages.json')).write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding='utf-8')
        (OUT / (name + '.txt')).write_text('\n\n'.join('=== PDF PAGE %s ===\n%s' % (p['page'], p['text']) for p in pages), encoding='utf-8')
        item.update(pages=len(pages), text_characters=sum(len(p['text']) for p in pages))
        print(name, len(pages), item['text_characters'], flush=True)
    (OUT / 'paper_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__ == '__main__':
    main()
