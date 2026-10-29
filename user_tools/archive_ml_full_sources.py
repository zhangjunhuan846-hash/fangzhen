"""Download full source archives without installing or executing upstream code."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import io
import json
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data/external/ml_full_sources_20261013'
GITHUB = ['PriorLabs/TabPFN', 'emdgroup/baybe', 'emdgroup/baybe-paper',
          'lpapenme/understanding-hdbo-code', 'LeoIV/sample-from-high-dim-GP',
          'QianJaneXie/PandoraBayesOpt', 'atinary-technologies/chem-MFBO',
          'MilesCranmer/PySR', 'ppdebreuck/modnet', 'dmbeaglehole/xRFM',
          'yandex-research/tabm', 'autogluon/tabarena', 'AI4ChemS/FABO',
          'usnistgov/AFL-agent', 'MolecularMaterials/AL-HTE-Electrolyte',
          'jeremy-goldwasser/feature-rankings', 'lrcfmd/LEAF']
GITLAB = ['sissopp_developers/sissopp', 'akhilsnair/workflow_sisso']
PDFS = ['s41586-024-08328-6.pdf', 's43588-025-00822-9.pdf', 'papenmeier25a.pdf',
        's41524-025-01596-4.pdf', 'goldwasser25a.pdf',
        'NeurIPS-2025-tabarena-a-living-benchmark-for-machine-learning-on-tabular-data-Paper-Datasets_and_Benchmarks_Track.pdf']

def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'fangzhen-readonly-archive'})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read(150_000_001)
    if len(data) > 150_000_000:
        raise ValueError('source archive exceeds 150 MB; requires selective download')
    return data

def archive(item):
    host, repo = item
    url = 'https://' + host + '/' + repo
    key = repo.replace('/', '__')
    target = DEST / key
    metadata = target / 'FANGZHEN_UPSTREAM.json'
    if metadata.exists():
        saved = json.loads(metadata.read_text(encoding='utf-8'))
        if not saved.get('revision_verified'):
            with zipfile.ZipFile(DEST / (key + '.zip')) as zipped:
                commit = zipped.comment.decode('ascii', errors='ignore').strip()
            if len(commit) == 40 and all(c in '0123456789abcdef' for c in commit):
                saved.update(commit=commit, revision_verified=True, revision_source='archive_comment')
                metadata.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
        return saved
    entry = {'repository': repo, 'url': url, 'status': 'failed',
             'scope': 'complete source archive; excludes Git history, submodules, LFS payloads, weights and externally linked datasets'}
    sha = None
    try:
        result = subprocess.run(['git', 'ls-remote', url + '.git', 'HEAD'],
                                capture_output=True, text=True, timeout=20)
        if result.returncode == 0 and result.stdout:
            sha = result.stdout.split()[0]
    except Exception:
        pass
    ref = sha or 'HEAD'
    address = ('https://codeload.github.com/' + repo + '/zip/' + ref if host == 'github.com'
               else url + '/-/archive/' + ref + '/' + repo.split('/')[-1] + '-' + ref + '.zip')
    try:
        data = download(address)
        archive_sha = hashlib.sha256(data).hexdigest()
        with zipfile.ZipFile(io.BytesIO(data)) as source:
            archive_commit = source.comment.decode('ascii', errors='ignore').strip()
            if not sha and len(archive_commit) == 40 and all(c in '0123456789abcdef' for c in archive_commit):
                sha = archive_commit
            if sum(info.file_size for info in source.infolist()) > 650_000_000:
                raise ValueError('expanded archive exceeds 650 MB')
            entries = []
            for info in source.infolist():
                parts = Path(info.filename).parts
                if len(parts) <= 1:
                    continue
                relative = Path(*parts[1:])
                path = (target / relative).resolve()
                if not path.is_relative_to(target.resolve()) or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError('unsafe archive path or symlink')
                entries.append((info, path))
            target.mkdir(parents=True, exist_ok=True)
            for info, path in entries:
                if info.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(source.read(info))
        (DEST / (key + '.zip')).write_bytes(data)
        entry.update(status='archived', commit=sha, ref=ref,
                     revision_source='git_remote_or_archive_comment',
                     revision_verified=bool(sha), archive_sha256=archive_sha,
                     archive_bytes=len(data), files=sum(not i.is_dir() for i, _ in entries),
                     local_path=str(target), archive_url=address,
                     license_files=[str(p.relative_to(target)) for p in target.rglob('*')
                                    if p.is_file() and p.name.lower().startswith(('license', 'copying'))][:30])
        metadata.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as error:
        entry['reason'] = str(error)
    print(repo, entry['status'], entry.get('files', 0), flush=True)
    return entry

def main():
    DEST.mkdir(parents=True, exist_ok=True)
    papers = ROOT / 'papers/descriptor_methods_20261013'
    papers.mkdir(parents=True, exist_ok=True)
    records = []
    for name in PDFS:
        original = Path('C:/Users/24330/Downloads') / name
        destination = papers / name
        shutil.copy2(original, destination)
        records.append({'name': name, 'path': str(destination), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
    (papers / 'manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    tasks = [('github.com', r) for r in GITHUB] + [('gitlab.com', r) for r in GITLAB]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(archive, tasks))
    (DEST / 'manifest.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'archived': sum(r['status'] == 'archived' for r in results), 'total': len(results)}))

if __name__ == '__main__':
    main()
