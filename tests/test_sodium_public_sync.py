import hashlib
import re
import zlib

import pytest

from user_tools import sync_sodium_data as sync


def test_old_version_in_local_cache_falls_back_to_publisher(tmp_path, monkeypatch):
    mirror, cache = tmp_path / 'mirror', tmp_path / 'cache'
    cache.mkdir()
    original = cache / 'sample.csv'
    original.write_bytes(b'old')
    payload = b'new'
    item = sync.file_item('sample.csv', 'https://example.org/file', len(payload),
                          'sha256:' + hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(sync, 'http_fetch', lambda record, temp, headers, offset: temp.write_bytes(payload))
    result = sync.fetch(mirror, {'type':'files', 'local':str(cache)}, item, {})
    assert result['status'] == 'verified' and (mirror / 'sample.csv').read_bytes() == payload
    assert original.read_bytes() == b'old'


def test_publisher_zip_member_crc_and_local_sha256(tmp_path):
    file = tmp_path / 'member.csv'
    file.write_bytes(b'capacity')
    crc = zlib.crc32(file.read_bytes())
    item = dict(path=file.name, size=8, checksum=f'crc32:{crc:08x}')
    assert sync.verify(file, item) == hashlib.sha256(b'capacity').hexdigest()
    file.write_bytes(b'capacity'[::-1])
    with pytest.raises(ValueError, match='Checksum'):
        sync.verify(file, item)


def test_tum_https_promotes_rsync_stage_and_reuses_identical_publisher_files(tmp_path, monkeypatch):
    payload = b'published sodium cell data'
    checksum = 'sha512:' + hashlib.sha512(payload).hexdigest()
    items = [sync.file_item(name, 'https://example.org/' + name, len(payload), checksum)
             for name in ('all/cell.txt', 'good/cell.txt')]
    staged = tmp_path / '.rsync/all/cell.txt'
    staged.parent.mkdir(parents=True)
    staged.write_bytes(payload)
    other_part = tmp_path / 'good/cell.txt.part'
    other_part.parent.mkdir()
    other_part.write_bytes(payload[:3])
    monkeypatch.setattr(sync, 'http_fetch', lambda *args: pytest.fail('Verified staged file should be reused'))
    sync.sync_tum_web(tmp_path, {'type': 'tum'}, items, 2, lambda: None)
    assert all(a['status'] == 'verified' and (tmp_path / a['path']).read_bytes() == payload for a in items)
    assert not staged.exists() and not other_part.exists()


@pytest.mark.parametrize('prefix', [0, 5, 8, 13, 33])
def test_resume_ranges_preserves_existing_prefix_and_parts(tmp_path, monkeypatch, prefix):
    data = bytes(range(33))
    temp = tmp_path / 'sample.zip.part'
    temp.write_bytes(data[:prefix])
    monkeypatch.setattr(sync, 'RANGE_BYTES', 8)
    monkeypatch.setattr(sync, 'REQUEST_BYTES', 4)
    if prefix < 33:
        parts = temp.with_suffix('.chunks')
        parts.mkdir()
        (parts / '24').write_bytes(data[24:27])

    class RangeResponse:
        status_code = 206

        def __init__(self, first, end):
            self.payload = data[first:end + 1]
            self.headers = {'Content-Range': f'bytes {first}-{end}/{len(data)}'}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            yield self.payload

    def get(self, url, *, headers, **options):
        match = re.fullmatch(r'bytes=(\d+)-(\d+)', headers['Range'])
        first, end = map(int, match.groups())
        assert first >= prefix and not 24 <= first < 27 and end - first < 4
        return RangeResponse(first, end)

    monkeypatch.setattr(sync.requests.Session, 'get', get)
    sync.fetch_ranges(dict(size=len(data), url='https://example.org/file'), temp)
    assert temp.read_bytes() == data
    assert not temp.with_suffix('.chunks').exists()
