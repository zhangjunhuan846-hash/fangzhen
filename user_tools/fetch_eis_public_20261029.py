"""Fetch original, checksum-verified EIS files from the publishers' APIs."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import json
import requests

ROOT = Path('data/external/eis_public_20261029')


def fetch(item):
    dest, url, expected = item
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == expected:
        return str(dest)
    response = requests.get(url, timeout=90)
    response.raise_for_status()
    data = response.content
    if expected and hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f'SHA256 mismatch: {dest}')
    dest.write_bytes(data)
    return str(dest)


def main():
    jobs = []
    index = []
    for temp, folder in [(5, '68a87e75ecfe80c80caffd5a'), (25, '68a87e7e8df186f945affbab'), (40, '68a87e858ea096956ebcf549')]:
        url = f'https://api.osf.io/v2/nodes/9ceav/files/osfstorage/{folder}/?page%5Bsize%5D=100'
        response = requests.get(url, timeout=30); response.raise_for_status()
        for entry in response.json()['data']:
            a = entry['attributes']
            if a['kind'] != 'file' or not a['name'].endswith('.xlsx'):
                continue
            digest = a['extra']['hashes']['sha256']
            dest = ROOT / 'stanford' / str(temp) / a['name']
            jobs.append((dest, entry['links']['download'], digest))
            index.append({'path': str(dest), 'url': entry['links']['download'], 'sha256': digest})
    response = requests.get('https://zenodo.org/api/records/15422339', timeout=30); response.raise_for_status()
    for entry in response.json()['files']:
        if not (entry['key'].startswith('ID') and entry['key'].endswith('.csv')):
            continue
        # Zenodo supplies MD5 in its metadata. Record it and verify separately.
        dest = ROOT / 'zenodo_54' / entry['key']
        jobs.append((dest, entry['links']['self'], None))
        index.append({'path': str(dest), 'url': entry['links']['self'], 'md5': entry['checksum'].split(':')[-1]})
    failures = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {pool.submit(fetch, job): job for job in jobs}
        for future in as_completed(future_map):
            try: future.result()
            except Exception as exc: failures.append({'path': str(future_map[future][0]), 'error': str(exc)})
    for entry in index:
        path = Path(entry['path'])
        if path.exists():
            data = path.read_bytes()
            entry['local_sha256'] = hashlib.sha256(data).hexdigest()
            if 'md5' in entry and hashlib.md5(data).hexdigest() != entry['md5']:
                failures.append({'path': str(path), 'error': 'MD5 mismatch'})
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'manifest.json').write_text(json.dumps({'files': index, 'failures': failures}, indent=2), encoding='utf-8')
    print(f'Files listed: {len(index)}; failures: {len(failures)}')
    for failure in failures[:10]: print(failure)


if __name__ == '__main__': main()
