"""Mirror versioned public cell and pack datasets into data/public/sodium_ion."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import csv
from datetime import datetime
from ftplib import FTP, all_errors as ftp_errors
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import threading
import time
from tempfile import NamedTemporaryFile, SpooledTemporaryFile
from urllib.parse import quote, urljoin, unquote, urlsplit
from xml.etree import ElementTree
import zipfile
import zlib

import requests

PROJECT = Path(__file__).resolve().parents[1]
LIBRARY = PROJECT / 'data/public/sodium_ion'
SOURCES = PROJECT / 'configs/sodium_public_sources.json'
_connection = threading.local()
TRANSFER_ERRORS = (requests.RequestException, ValueError, zipfile.BadZipFile) + ftp_errors
_public_sessions = {}
RANGE_BYTES = 32 * 1024 ** 2
REQUEST_BYTES = 8 * 1024 ** 2


class RangeUnavailable(Exception):
    """A public download server only serves the complete response."""


@contextmanager
def source_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.sync.lock').open('a+b') as guard:
        if not guard.tell():
            guard.write(b'0')
            guard.flush()
        guard.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True  # Closing the handle releases the lock, including after a process exit.


def tum_ftp(share):
    if getattr(_connection, 'share', None) != share:
        ftp = FTP('dataserv.ub.tum.de', timeout=90, encoding='utf-8')
        ftp.login(share, share)  # Public read-only login printed on the mediaTUM record.
        ftp.voidcmd('TYPE I')
        _connection.ftp, _connection.share = ftp, share
    return _connection.ftp


def tum_files(source, web=False):
    share = 'm' + source['record']
    if web:
        base = f'https://dataserv.ub.tum.de/public.php/dav/files/{share}/'
        listing = requests.request('PROPFIND', base, headers={'Depth': '1'}, timeout=(15, 60))
        if listing.status_code in (401, 403, 405):
            items = tum_files(source)
            for item in items:
                item['url'] = base + quote(item['path'])
            return items
        listing.raise_for_status()
        names = [unquote(urlsplit(node.text).path) for node in ElementTree.fromstring(listing.content).iter('{DAV:}href')]
        filename = next(PurePosixPath(n).name for n in names if n.endswith(('.sha512', '.sha3-512')))
        response = requests.get(base + quote(filename), timeout=(15, 90))
        response.raise_for_status()
        raw = response.content
    else:
        ftp = tum_ftp(share)
        filename = next(n for n in ftp.nlst() if n.endswith(('.sha512', '.sha3-512')))
        raw = bytearray()
        ftp.retrbinary('RETR ' + filename, raw.extend)
        base = f'ftp://{share}@dataserv.ub.tum.de/'
    items = []
    alg = 'sha3_512' if filename.endswith('sha3-512') else 'sha512'
    for line in raw.decode('utf-8-sig').splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.lstrip('*').replace('\\', '/')
        items.append(file_item(name, base + quote(name), checksum=alg + ':' + digest))
    items.append(file_item(filename, base + quote(filename), len(raw), 'sha256:' + hashlib.sha256(raw).hexdigest()))
    return items


def ftp_fetch(url, tmp):
    u = urlsplit(url)
    ftp = tum_ftp(u.username)
    name = unquote(u.path.lstrip('/'))
    try:
        ftp.voidcmd('TYPE I')
        total = ftp.size(name)
        offset = tmp.stat().st_size if tmp.exists() else 0
        if total and offset == total:
            return
        if total is not None and offset > total:
            offset = 0
        with tmp.open('ab' if offset else 'wb') as f:
            ftp.retrbinary('RETR ' + name, f.write, blocksize=256 * 1024, rest=offset or None)
    except ftp_errors:
        ftp.close()
        _connection.share = None
        raise


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def write_index(root, sources):
    """Summarize verified payloads separately from publisher records and partial transfers."""
    root.mkdir(parents=True, exist_ok=True)
    summaries, files, unique = [], [], {}
    labels = dict(complete='已校验', partial='部分取得', running='下载中', paused='已暂停，可续传', unavailable='暂不可得', pending='待下载')
    timestamp = datetime.now().astimezone().isoformat(timespec='seconds')
    for spec in sources:
        path = root / spec['id'] / 'manifest.json'
        info = json.loads(path.read_text(encoding='utf8')) if path.exists() else spec
        assets = info.get('assets', [])
        verified = [f for f in assets if f.get('status') == 'verified']
        for item in verified:
            unique[item['sha256']] = item['bytes']
        summaries.append((spec['id'], info.get('title', spec['id']), info['kind'],
                          labels[info.get('status', 'pending')], len(verified), len(assets),
                          sum(f['bytes'] for f in verified), info.get('license') or spec.get('license') or '', info.get('url', ''),
                          spec.get('selection', info.get('selection', '')), info.get('error', ''), timestamp))
        for f in assets:
            files.append((spec['id'], f['path'], f.get('status', 'pending'), f.get('bytes', ''),
                          f.get('size') or '', f.get('checksum') or '', f.get('sha256', ''),
                          spec['id'] + '/' + f['path'], f['url'], f.get('archive_member', ''), f.get('error', '')))
    tables = [
        ('下载目录.csv', ('来源ID','数据来源','实验类型','状态','已校验文件','在收集范围内的文件',
                       '已校验字节','许可','发布页','选择说明','原因','统计时间'), summaries),
        ('文件清单.csv', ('来源ID','文件','状态','已校验字节','发布者字节','发布者校验','本地SHA256',
                       '库内相对路径','原始下载地址','发布压缩包内路径','错误'), files),
    ]
    for name, columns, rows in tables:
        with NamedTemporaryFile('w', dir=root, encoding='utf-8-sig', newline='', delete=False) as out:
            writer = csv.writer(out)
            writer.writerow(columns)
            writer.writerows(rows)
        os.replace(out.name, root / name)
    return dict(sources=len(summaries), complete=sum(r[3] == '已校验' for r in summaries),
                verified_files=sum(r[4] for r in summaries), unique_files=len(unique),
                unique_bytes=sum(unique.values()), indexed_at=timestamp)


def get_json(url, **params):
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=(12, 45))
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def file_item(path, url, size=None, checksum=None, archive_member=None):
    path = PurePosixPath(path)
    if path.is_absolute() or '..' in path.parts or any(re.search(r'[\\:*?"<>|]', part) for part in path.parts):
        raise ValueError(f'Invalid source filename: {path}')
    item = dict(path=str(path), url=url, size=size, checksum=checksum)
    if archive_member:
        item['archive_member'] = archive_member
    return item


def mendeley(source):
    record, version = source['record'], source['version']
    api = f'https://data.mendeley.com/public-api/datasets/{record}'
    meta = get_json(api, version=version)
    source.update(url=f'https://data.mendeley.com/datasets/{record}/{version}',
                  title=meta['name'], license=meta['data_licence']['short_name'])
    folders = get_json(f'{api}/folders/{version}')
    by_id = {f['id']: f for f in folders}
    items = []
    for folder_id in ['root', *by_id]:
        parents = []
        current = folder_id
        while current in by_id:
            parents.insert(0, by_id[current]['name'])
            current = by_id[current].get('parent_id')
        offset = 0
        while True:
            rows = get_json(f'{api}/files', folder_id=folder_id, version=version,
                            **{'$start': offset, '$limit': 100})
            if not isinstance(rows, list):
                raise ValueError(f'Could not enumerate Mendeley folder {folder_id}')
            for row in rows:
                d = row['content_details']
                items.append(file_item('/'.join([*parents, row['filename']]), d['download_url'],
                                       d['size'], 'sha256:' + d['sha256_hash']))
            if len(rows) < 100:
                break
            offset += len(rows)
    return items


def public_links(base, selector):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge' if os.name == 'nt' else None)
        page = browser.new_page()
        page.goto(base, wait_until='domcontentloaded')
        page.locator(selector).first.wait_for(timeout=35000)
        links = page.locator('a[href]').evaluate_all('(links) => links.map(a => [a.textContent.trim(), a.href])')
        opts = dict(headers={'User-Agent': page.evaluate('navigator.userAgent')},
                    cookies={c['name']: c['value'] for c in page.context.cookies(base)})
        browser.close()
    return links, opts


def list_source(s, tum_https=False):
    kind = s['type']
    if kind == 'access':
        raise ValueError(s['reason'])
    if kind == 'rwth':
        base = f"https://publications.rwth-aachen.de/record/{s['record']}/files/"
        s['url'] = 'https://doi.org/' + s['doi']
        links, opts = public_links(base, 'a[href*=".zip"]')
        items = []
        for name in s['public_files']:
            url = next(href for label, href in links if label == name)
            with requests.get(url, headers={**opts['headers'], 'Range': 'bytes=0-0'},
                              cookies=opts['cookies'], stream=True, timeout=30) as response:
                response.raise_for_status()
                size = int(response.headers['Content-Range'].split('/')[-1])
            _public_sessions[url] = opts
            items.append(file_item(name, url, size))
        return items
    if kind == 'nlr':
        links, opts = public_links(s['url'], 'a[href*="cell-sibs"]')
        published = {href for _, href in links}
        items = [file_item(**f) for f in s['files']]
        for item in items:
            if item['url'] not in published:
                raise ValueError('发布方已调整 NLR 数据文件链接，请核对版本。')
            _public_sessions[item['url']] = opts
        return items
    if kind == 'zenodo':
        s['url'] = f"https://zenodo.org/records/{s['record']}"
        meta = get_json(f"https://zenodo.org/api/records/{s['record']}")
        m = meta['metadata']
        s.update(title=m['title'], license=m.get('license', {}).get('id'), doi=meta.get('doi'))
        if m.get('access_right') not in ('open', None) or not meta.get('files'):
            raise ValueError('发布者的文件访问状态为 ' + str(m.get('access_right')))
        return [file_item(f['key'], f['links']['self'], f['size'], f['checksum']) for f in meta['files']]
    if kind == 'mendeley':
        return mendeley(s)
    if kind == 'figshare':
        meta = get_json(f"https://api.figshare.com/v2/articles/{s['record']}/versions/{s['version']}")
        s.update(url=meta['url_public_html'], title=re.sub(r'<[^>]+>', '', meta['title']),
                 license=meta['license']['name'], doi=meta['doi'])
        return [file_item(f['name'], f.get('downloadUrl') or f['download_url'], f['size'], 'md5:' + f['computed_md5'])
                for f in meta['files']]
    if kind == 'hf':
        repo, ref, folder = s['repo'], s['revision'], s.get('folder', '')
        base = f'https://huggingface.co/datasets/{repo}'
        s.update(url=f'{base}/tree/{ref}/{folder}')
        api = f'https://huggingface.co/api/datasets/{repo}/tree/{ref}'
        if folder:
            api += '/' + folder
        api += '?recursive=true&limit=1000'
        items = []
        while api:
            response = requests.get(api, timeout=(12, 45))
            response.raise_for_status()
            for f in response.json():
                if f['type'] == 'directory':
                    continue
                if f['type'] != 'file':
                    raise ValueError('Unknown repository entry type')
                name = PurePosixPath(f['path']).relative_to(folder)
                checksum = 'sha256:' + f['lfs']['oid'] if f.get('lfs') else 'git:' + f['oid']
                items.append(file_item(name, f"{base}/resolve/{ref}/{quote(f['path'])}", f['size'], checksum))
            api = response.links.get('next', {}).get('url')
        return items
    if kind == 'github':
        repo, ref = s['repo'], s['revision']
        s['url'] = f'https://github.com/{repo}/tree/{ref}'
        tree = get_json(f'https://api.github.com/repos/{repo}/git/trees/{ref}', recursive=1)
        if tree.get('truncated'):
            raise ValueError('Incomplete Git file tree')
        items = []
        for blob in tree['tree']:
            if blob['type'] != 'blob' or blob['path'].startswith('.'):
                continue
            name, size = blob['path'], blob['size']
            url = f'https://raw.githubusercontent.com/{repo}/{ref}/{quote(name)}'
            checksum = 'git:' + blob['sha']
            if size < 250:
                data = requests.get(url, timeout=30)
                data.raise_for_status()
                match = re.search(rb'oid sha256:(\w{64})\s+size (\d+)', data.content)
                if match:
                    size = int(match[2])
                    checksum = 'sha256:' + match[1].decode()
                    url = f'https://media.githubusercontent.com/media/{repo}/{ref}/{quote(name)}'
            items.append(file_item(name, url, size, checksum))
        return items
    if kind in ('tum', 'berlin'):
        s['url'] = 'https://doi.org/' + s['doi']
        meta = get_json('https://api.datacite.org/dois/' + s['doi'])['data']['attributes']
        s['title'] = meta['titles'][0]['title']
        s['license'] = ', '.join(r.get('rightsUri') or r.get('rights', '') for r in meta['rightsList'])
        if kind == 'tum':
            return tum_files(s, web=tum_https)
        from bs4 import BeautifulSoup
        page = requests.get(meta['url'], timeout=30)
        page.raise_for_status()
        soup = BeautifulSoup(page.content, 'html.parser')
        items = []
        for link in soup.select('a[href*="/bitstreams/"][href$="/download"]'):
            identifier = link['href'].split('/')[-2]
            bitstream = get_json('https://api-depositonce.tu-berlin.de/server/api/core/bitstreams/' + identifier)
            digest = bitstream['checkSum']
            items.append(file_item(bitstream['name'], urljoin(page.url, link['href']), bitstream['sizeBytes'],
                                   digest['checkSumAlgorithm'].lower() + ':' + digest['value']))
        return items
    if kind == 'files':
        return [file_item(**f) for f in s['files']]
    raise ValueError(f'Unknown source type: {kind}')


def verify(path, item):
    expected = item.get('checksum')
    if item.get('size') is not None and path.stat().st_size != item['size']:
        raise ValueError('File size differs from publisher')
    sha = hashlib.sha256()
    extra = None
    crc = 0
    if expected:
        alg, wanted = expected.split(':', 1)
        if alg != 'crc32':
            extra = sha if alg == 'sha256' else hashlib.new('sha1' if alg == 'git' else alg)
        if alg == 'git':
            extra.update(f'blob {path.stat().st_size}\0'.encode())
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            sha.update(chunk)
            if expected and alg == 'crc32':
                crc = zlib.crc32(chunk, crc)
            if extra is not None and extra is not sha:
                extra.update(chunk)
    if expected and (f'{crc:08x}' if alg == 'crc32' else extra.hexdigest()) != wanted:
        raise ValueError('Checksum differs from publisher')
    if not expected and item['path'].lower().endswith(('.zip', '.xlsx')):
        with zipfile.ZipFile(path) as archive:
            if not archive.namelist() or archive.testzip() is not None:
                raise ValueError('Incomplete archive or invalid CRC')
    return sha.hexdigest()


def fetch(destination, source, item, previous):
    path = destination / item['path']
    path.parent.mkdir(parents=True, exist_ok=True)
    checksum = item.get('checksum')
    tmp = path.with_name(path.name + '.part')
    if path.is_file() and (checksum or previous.get('sha256')):
        cached = dict(item, checksum=checksum or 'sha256:' + previous['sha256'])
        try:
            digest = verify(path, cached)
            tmp.unlink(missing_ok=True)
            return dict(item, sha256=digest, bytes=path.stat().st_size, status='verified')
        except (ValueError, zipfile.BadZipFile):
            pass  # Replace a damaged mirror file only after checking the replacement.
    original = source.get('reuse', {}).get(item['path'])
    if not original and source.get('local'):
        original = str(Path(source['local']) / item['path'])
    if original and checksum and (PROJECT / original).is_file():
        other = PROJECT / original
        try:
            digest = verify(other, item)
        except (ValueError, zipfile.BadZipFile):
            pass  # The existing copy may correspond to another publisher version.
        else:
            if not tmp.exists() or not tmp.samefile(other):
                tmp.unlink(missing_ok=True)
                try:
                    os.link(other, tmp)
                except OSError:
                    shutil.copyfile(other, tmp)
            os.replace(tmp, path)
            return dict(item, sha256=digest, bytes=path.stat().st_size, status='verified')
    stalled = 0
    while stalled < 4:
        before = tmp.stat().st_size if tmp.exists() else 0
        try:
            offset = tmp.stat().st_size if tmp.exists() and (checksum or item.get('size')) else 0
            if item.get('size') is not None and offset > item['size']:
                tmp.unlink()
                offset = 0
            if item.get('size') is None or offset != item['size'] or offset == 0:
                headers = {'Accept-Encoding': 'gzip' if source['type'] == 'tum' and not offset else 'identity'}
                if offset:
                    headers['Range'] = f'bytes={offset}-'
                if item.get('archive_member'):
                    fetch_archive_member(item, tmp)
                elif item['url'].startswith('ftp://'):
                    ftp_fetch(item['url'], tmp)
                else:
                    if source['type'] in ('rwth', 'zenodo', 'mendeley') and (item.get('size') or 0) >= 64 * 1024 ** 2:
                        try:
                            fetch_ranges(item, tmp)
                        except RangeUnavailable:
                            http_fetch(item, tmp, headers, offset)
                    else:
                        http_fetch(item, tmp, headers, offset)
            digest = verify(tmp, item)
            os.replace(tmp, path)
            return dict(item, sha256=digest, bytes=path.stat().st_size, status='verified')
        except TRANSFER_ERRORS as exc:
            if isinstance(exc, (ValueError, zipfile.BadZipFile)) and tmp.is_file():
                tmp.unlink()
            after = tmp.stat().st_size if tmp.exists() else 0
            stalled = 0 if after > before else stalled + 1
            if stalled >= 4:
                raise
            time.sleep(1 + 2 ** stalled)


def fetch_archive_member(item, tmp):
    from remotezip import RemoteZip, RemoteZipError

    def extract(archive):
        entry = archive.getinfo(item['archive_member'])
        if entry.file_size != item['size']:
            raise ValueError('Archive member size differs from publisher')
        with archive.open(entry) as src, tmp.open('wb') as out:
            shutil.copyfileobj(src, out, 1024 * 1024)

    opts = _public_sessions.get(item['url'], {})
    try:
        with RemoteZip(item['url'], timeout=(16, 110), **opts) as archive:
            extract(archive)
    except RemoteZipError:
        with requests.get(item['url'], stream=True, timeout=(16, 110), **opts) as response:
            response.raise_for_status()
            with SpooledTemporaryFile(max_size=8 * 1024 ** 2) as temp:
                for chunk in response.iter_content(512 * 1024):
                    temp.write(chunk)
                with zipfile.ZipFile(temp) as archive:
                    extract(archive)


def http_fetch(item, tmp, headers, offset):
    opts = _public_sessions.get(item['url'], {})
    if not hasattr(_connection, 'http'):
        _connection.http = requests.Session()
    with _connection.http.get(item['url'], headers={**opts.get('headers', {}), **headers},
                              cookies=opts.get('cookies'), stream=True, timeout=(16, 110)) as response:
        response.raise_for_status()
        if 'html' in response.headers.get('content-type', '').lower() and not item['path'].endswith(('.html', '.htm')):
            raise ValueError('发布页返回 HTML，尚未取得数据文件')
        if response.status_code == 206:
            if not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                raise ValueError('Invalid Content-Range')
        else:
            offset = 0
        with tmp.open('ab' if offset else 'wb') as stream:
            for chunk in response.iter_content(512 * 1024):
                stream.write(chunk)


def fetch_ranges(item, tmp):
    """Download the publisher's fixed-size archive in independently resumable ranges."""
    size, block = item['size'], RANGE_BYTES
    prefix = tmp.stat().st_size if tmp.exists() else 0
    if prefix == size:
        return
    folder = tmp.with_suffix('.chunks')
    folder.mkdir(exist_ok=True)
    opts = _public_sessions.get(item['url'], {})
    def chunk(start):
        if not hasattr(_connection, 'http'):
            _connection.http = requests.Session()
        end = min(start + block, size) - 1
        dest = folder / str(start)
        if start < prefix and not dest.exists():
            with tmp.open('rb') as prior:
                prior.seek(start)
                dest.write_bytes(prior.read(prefix - start))
        stalled = 0
        while True:
            offset = dest.stat().st_size if dest.exists() else 0
            if offset == end - start + 1:
                return dest
            if offset > end - start + 1:
                dest.unlink()
                offset = 0
            first = start + offset
            last = min(end, first + REQUEST_BYTES - 1)
            headers = {**opts.get('headers', {}), 'Accept-Encoding': 'identity', 'Range': f'bytes={first}-{last}'}
            try:
                with _connection.http.get(item['url'], headers=headers, cookies=opts.get('cookies'),
                                          stream=True, timeout=(16, 110)) as r:
                    r.raise_for_status()
                    if r.status_code == 200:
                        raise RangeUnavailable()
                    if r.status_code != 206 or r.headers.get('Content-Range') != f'bytes {first}-{last}/{size}':
                        raise ValueError('Publisher did not return the requested byte range')
                    with dest.open('ab') as out:
                        for data in r.iter_content(512 * 1024):
                            out.write(data)
                if dest.stat().st_size != last - start + 1:
                    raise OSError('Incomplete range')
                stalled = 0
            except (requests.RequestException, OSError):
                stalled = 0 if dest.exists() and dest.stat().st_size > offset else stalled + 1
                if stalled >= 4:
                    raise
                time.sleep(1 + 2 ** stalled)
    starts = range(prefix // block * block, size, block)
    with ThreadPoolExecutor(max_workers=8 if size >= 1024 ** 3 else 6) as workers:
        chunks = list(workers.map(chunk, starts))
    with tmp.open('ab') as out:
        for start, path in zip(starts, chunks):
            with path.open('rb') as part:
                part.seek(max(0, prefix - start))
                shutil.copyfileobj(part, out, 1024 * 1024)
    for path in folder.iterdir():
        if path.name.isdecimal():
            path.unlink()
    folder.rmdir()


def fetch_bundle(folder, source, items):
    """Expand Mendeley's compressed transport and verify the individual publisher hashes."""
    url = f"https://data.mendeley.com/public-api/zip/{source['record']}/download/{source['version']}"
    archive = folder / '.publisher-download.zip'
    if not archive.exists():
        with requests.get(url, headers={'Range': 'bytes=0-0'}, stream=True, timeout=45) as r:
            r.raise_for_status()
            size = int(r.headers['Content-Range'].split('/')[-1] if r.status_code == 206 else r.headers['Content-Length'])
        tmp = archive.with_suffix('.part')
        for attempt in range(4):
            try:
                item = file_item('publisher.zip', url, size)
                try:
                    fetch_ranges(item, tmp)
                except RangeUnavailable:
                    http_fetch(item, tmp, {'Accept-Encoding': 'identity'}, 0)
                    if tmp.stat().st_size != size:
                        raise OSError('Incomplete download archive')
                break
            except TRANSFER_ERRORS:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        os.replace(tmp, archive)
    with zipfile.ZipFile(archive) as z:
        names = {name.partition('/')[2]: name for name in z.namelist() if not name.endswith('/')}
        for item in items:
            name = names[item['path']]
            path = folder / item['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            stage = path.with_name(path.name + '.from-zip')
            with z.open(name) as compressed, stage.open('wb') as output:
                shutil.copyfileobj(compressed, output, 1024 * 1024)
            digest = verify(stage, item)
            os.replace(stage, path)
            path.with_name(path.name + '.part').unlink(missing_ok=True)
            item.update(sha256=digest, bytes=path.stat().st_size, status='verified')
    archive.unlink()


def rsync_tum(folder, source, items, workers, checkpoint):
    """Use mediaTUM's public compressed rsync service. All files still pass publisher verification."""
    share = 'm' + source['record']
    prefix = ['wsl.exe', '-d', 'Ubuntu', '--'] if os.name == 'nt' else []
    cmd = [*prefix, 'env', 'RSYNC_PASSWORD=' + share, 'rsync', '--contimeout=25', '--timeout=120']
    url = f'rsync://{share}@dataserv.ub.tum.de/{share}/'
    listing = subprocess.run([*cmd, '-r', '--list-only', url], capture_output=True, check=True, timeout=180)
    sizes = {}
    for line in listing.stdout.decode('utf-8').splitlines():
        match = re.match(r'^-\S+\s+([\d,]+)\s+\d{4}/\d+/\d+\s+\d+:\d+:\d+\s+(.*)$', line)
        if match:
            sizes[match[2]] = int(match[1].replace(',', ''))
    staged = folder / '.rsync'
    staged.mkdir(exist_ok=True)
    groups, group, weight = [], [], 0
    for item in items:
        name = item['path']
        item['size'] = sizes[name]
        final = folder / name
        if final.exists() and final.stat().st_size == item['size']:
            try:
                digest = verify(final, item)
                item.update(bytes=final.stat().st_size, sha256=digest, status='verified')
                continue
            except ValueError:
                pass
        dest = staged / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = final.with_name(final.name + '.part')
        if partial.is_file() and not dest.exists():
            partial.replace(dest)
        if group and (weight + item['size'] > 96 * 1024 ** 2 or len(group) >= 100):
            groups.append(group)
            group, weight = [], 0
        group.append(item)
        weight += item['size']
    if group:
        groups.append(group)
    checkpoint()

    def download(batch):
        filelist = b''.join(f['path'].encode('utf-8') + b'\0' for f in batch)
        # Each batch has disjoint paths. Interrupted rsync writes stay in the staging tree.
        args = [*cmd, '-rz', '--compress-level=5', '--partial', '--append-verify',
                '--from0', '--files-from=-', url, './.rsync/']
        for attempt in range(4):
            result = subprocess.run(args, input=filelist, cwd=folder, capture_output=True)
            if result.returncode == 0:
                break
            if attempt == 3:
                raise OSError('mediaTUM rsync: ' + result.stderr.decode('utf-8', errors='replace')[-350:])
            time.sleep(3 * (attempt + 1))
        for item in batch:
            name = item['path']
            src, final = staged / name, folder / name
            try:
                digest = verify(src, item)
            except ValueError:
                src.unlink(missing_ok=True)
                raise
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, final)
            item.update(sha256=digest, bytes=final.stat().st_size, status='verified')

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download, batch): batch for batch in groups}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                for item in futures[future]:
                    if item.get('status') != 'verified':
                        item.update(status='failed', error=str(exc))
            checkpoint()


def sync_tum_web(folder, source, items, workers, checkpoint):
    """Resume individual mediaTUM files over HTTPS, including partial rsync transfers."""
    groups = {}
    for item in items:
        groups.setdefault(item['checksum'], []).append(item)

    def paths(item):
        target = folder / item['path']
        return target, target.with_name(target.name + '.part'), folder / '.rsync' / item['path']

    def retained(item):
        return max((p.stat().st_size for p in paths(item) if p.is_file()), default=0)

    def download(group):
        group.sort(key=retained, reverse=True)
        first = group[0]
        final, part, staged = paths(first)
        final.parent.mkdir(parents=True, exist_ok=True)
        if staged.is_file() and (not part.exists() or staged.stat().st_size > part.stat().st_size):
            os.replace(staged, part)
        first.update(fetch(folder, source, first, first))
        staged.unlink(missing_ok=True)
        for item in group[1:]:
            local = dict(source, reuse={item['path']: str(final.resolve())})
            item.update(fetch(folder, local, item, item))
            paths(item)[2].unlink(missing_ok=True)

    def priority(group):
        best = max(retained(item) for item in group)
        return (best > 0 and best == group[0].get('size'), best > 0)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(download, group): group for group in sorted(groups.values(), key=priority, reverse=True)}
        last = time.monotonic()
        for count, future in enumerate(as_completed(jobs), 1):
            try:
                future.result()
            except Exception as exc:
                for item in jobs[future]:
                    if item.get('status') != 'verified':
                        item.update(status='failed', error=str(exc).split('?')[0][:400])
            if count % 30 == 0 or time.monotonic() - last >= 25:
                checkpoint()
                last = time.monotonic()


def sync(source, root, workers, use_rsync=False, use_https=False):
    folder = root / source['id']
    with source_lock(folder) as acquired:
        if not acquired:
            print(source['id'], 'already syncing', flush=True)
            return 'running'
        return sync_source(source, folder, workers, use_rsync, use_https)


def sync_source(source, folder, workers, use_rsync, use_https=False):
    manifest = folder / 'manifest.json'
    report = dict(source, status='pending', assets=[])
    prior = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    try:
        tum_https = use_https and source['type'] == 'tum'
        cached_list = tum_https and prior.get('assets') and prior.get('publisher_files') and all(
            prior.get(k) == source.get(k) for k in ['record', 'include', 'exclude'])
        if cached_list and all(a.get('checksum') for a in prior['assets']):
            base = f"https://dataserv.ub.tum.de/public.php/dav/files/m{source['record']}/"
            files = [file_item(a['path'], base + quote(a['path']), a.get('size'), a['checksum']) for a in prior['assets']]
            report.update({k: prior[k] for k in ('title','license','url','doi') if k in prior})
            publisher_count = prior['publisher_files']
        else:
            files = list_source(report, tum_https=tum_https)
            publisher_count = len(files)
        selected = [f for f in files if re.search(source.get('include', ''), f['path'])
                    and not (source.get('exclude') and re.search(source['exclude'], f['path']))]
        if not selected or len({f['path'].casefold() for f in selected}) != len(selected):
            raise ValueError('Empty or ambiguous file list')
        old = {f['path']: f for f in prior.get('assets', [])}
        report.update(status='running', publisher_files=publisher_count, assets=selected)
        write_json(manifest, report)
        print(source['id'], len(selected), 'files', flush=True)
        if tum_https:
            sync_tum_web(folder, source, selected, workers, lambda: write_json(manifest, report))
        elif use_rsync and source['type'] == 'tum':
            rsync_tum(folder.resolve(), source, selected, workers, lambda: write_json(manifest, report))
        elif source.get('bundle') and not all((folder / f['path']).is_file() for f in selected):
            fetch_bundle(folder, source, selected)
        else:
            sync_files(folder, source, selected, old, workers, lambda: write_json(manifest, report))
        report['status'] = 'complete' if all(f.get('status') == 'verified' for f in selected) else 'partial'
    except Exception as exc:
        report.update(status='partial' if report['assets'] else 'unavailable', error=str(exc).split('?')[0][:400])
        if not report['assets'] and prior.get('assets'):
            report['assets'] = prior['assets']
    write_json(manifest, report)
    print(source['id'], report['status'], report.get('error', ''), flush=True)
    return report['status']


def sync_files(folder, source, selected, old, workers, checkpoint):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(fetch, folder, source, f, old.get(f['path'], {})): i for i, f in enumerate(selected)}
        for count, future in enumerate(as_completed(jobs), 1):
            i = jobs[future]
            try:
                selected[i] = future.result()
            except Exception as exc:
                selected[i] = dict(selected[i], status='failed', error=str(exc).split('?')[0][:400])
            if len(selected) < 150 or count % 25 == 0:
                checkpoint()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', nargs='+', help='Sync only these source IDs')
    parser.add_argument('--root', type=Path, default=LIBRARY)
    parser.add_argument('--sources', type=Path, default=SOURCES)
    parser.add_argument('--parallel-sources', type=int, default=4)
    parser.add_argument('--workers', type=int, default=3)
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument('--tum-rsync', action='store_true', help='Use compressed rsync for mediaTUM')
    transport.add_argument('--tum-https', action='store_true', help='Use public WebDAV/HTTPS for mediaTUM, resuming local partial files')
    parser.add_argument('--index-only', action='store_true', help='Rebuild CSV catalogs from local manifests')
    args = parser.parse_args()
    all_sources = json.loads(args.sources.read_text(encoding='utf-8'))
    if args.index_only:
        print(json.dumps(write_index(args.root, all_sources), ensure_ascii=False))
        return 0
    sources = all_sources
    if args.only:
        missing = set(args.only) - {s['id'] for s in sources}
        if missing:
            parser.error('Unknown sources: ' + ', '.join(sorted(missing)))
        sources = [s for s in sources if s['id'] in args.only]
    with ThreadPoolExecutor(max_workers=args.parallel_sources) as pool:
        results = list(pool.map(lambda s: sync(s, args.root, args.workers, args.tum_rsync, args.tum_https), sources))
    write_index(args.root, all_sources)
    return int(any(status != 'complete' for status in results))


if __name__ == '__main__':
    raise SystemExit(main())
