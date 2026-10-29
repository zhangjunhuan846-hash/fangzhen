"""Archive selected upstream text files for read-only implementation review."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data/external/ml_reference_review_20261013'
REPOS = ['PriorLabs/TabPFN', 'emdgroup/baybe', 'lpapenme/understanding-hdbo-code',
         'QianJaneXie/PandoraBayesOpt', 'atinary-technologies/chem-MFBO',
         'MilesCranmer/PySR', 'ppdebreuck/modnet', 'dmbeaglehole/xRFM',
         'yandex-research/tabm', 'autogluon/tabarena', 'AI4ChemS/FABO',
         'usnistgov/AFL-agent', 'MolecularMaterials/AL-HTE-Electrolyte']

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'fangzhen-source-review'})
    with urllib.request.urlopen(req, timeout=25) as response:
        data = response.read(4_000_001)
    if len(data) > 4_000_000:
        raise ValueError('reference file exceeds size limit')
    return data

def main():
    DEST.mkdir(parents=True, exist_ok=True)
    manifest = []
    for repo in REPOS:
        entry = {'repository': repo, 'url': 'https://github.com/' + repo, 'files': [],
                 'scope': 'selected text files only; not a full source audit or execution'}
        try:
            meta = json.loads(fetch('https://api.github.com/repos/' + repo))
            commit = json.loads(fetch('https://api.github.com/repos/' + repo + '/commits/' + meta['default_branch']))['sha']
            entry['commit'] = commit
            tree = json.loads(fetch('https://api.github.com/repos/' + repo + '/git/trees/' + commit + '?recursive=1'))
            paths = [r['path'] for r in tree['tree'] if r['type'] == 'blob']
            selected = [p for p in paths if '/' not in p and (p.lower().startswith(('readme', 'license')) or p in ['pyproject.toml', 'setup.py'])]
            tokens = ['feature_selection', 'acquisition', 'campaign.py', 'gaussian_process', 'gittins', 'bayesian_optimization', 'regressor.py', 'preprocessing.py', 'sr.py']
            selected += [p for p in paths if p.endswith('.py') and '/tests/' not in p and not p.startswith('tests/') and any(t in p for t in tokens)][:5]
            selected += [p for p in ['baybe/campaign.py', 'xrfm/xrfm.py', 'xrfm/rfm_src/recursive_feature_machine.py', 'ALGORITHM.md'] if p in paths]
            local = DEST / repo.replace('/', '__')
            for path in dict.fromkeys(selected):
                try:
                    data = fetch('https://raw.githubusercontent.com/' + repo + '/' + commit + '/' + path)
                    target = local / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    entry['files'].append({'path': path, 'sha256': hashlib.sha256(data).hexdigest()})
                except Exception as error:
                    entry.setdefault('file_errors', []).append({'path': path, 'error': str(error)})
            entry['status'] = 'selected_files_archived'
        except Exception as error:
            entry.update(status='unavailable', error=str(error))
            local = DEST / repo.replace('/', '__')
            if local.exists():
                entry['status'] = 'local_snapshot_commit_unverified'
                entry['files'] = [{'path': str(p.relative_to(local)).replace('\\', '/'),
                                   'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                                  for p in local.rglob('*') if p.is_file()]
            else:
                for branch in ['main', 'master']:
                    try:
                        data = fetch('https://raw.githubusercontent.com/' + repo + '/' + branch + '/README.md')
                        local.mkdir(parents=True, exist_ok=True)
                        (local / 'README.md').write_bytes(data)
                        entry.update(status='readme_only_unpinned', branch=branch,
                                     files=[{'path': 'README.md', 'sha256': hashlib.sha256(data).hexdigest()}])
                        break
                    except Exception:
                        pass
        manifest.append(entry)
        print(repo, entry['status'], len(entry['files']), flush=True)
    (DEST / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__ == '__main__':
    main()
