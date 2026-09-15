import pytest

from agents.core.artifact_store import BinaryArtifactStore, resolve_blob
from agents.core.media_catalog import MediaCatalog
from tests.test_binary_artifact_store import PDF


def test_gallery_unifies_safe_cache_and_attachments_without_paths(tmp_path):
    from agents.core.media_library import gallery
    cache = tmp_path / 'media' / 'cache'
    cache.mkdir(parents=True)
    (cache / 'clip.pdf').write_bytes(PDF)
    catalog = MediaCatalog(tmp_path / 'media' / 'catalog.json')
    item = catalog.add(now=1, kind='image', prompt='cached report', path=str(cache / 'clip.pdf'))
    outside = tmp_path / 'secret.pdf'
    outside.write_bytes(PDF)
    bad = catalog.add(now=1, kind='image', prompt='outside', path=str(outside))
    attachment = BinaryArtifactStore(tmp_path).put(PDF)
    rows = gallery(tmp_path, generated=True, attached=True)
    assert {r['id'] for r in rows} == {item['id'], bad['id'], attachment['id']}
    assert all('path' not in row for row in rows)
    assert next(r for r in rows if r['id']==bad['id'])['available'] is False
    assert resolve_blob(item['id'], tmp_path)[1] == PDF
    with pytest.raises(ValueError):
        resolve_blob(bad['id'], tmp_path)


def test_portable_export_includes_generated_cache_bytes(tmp_path):
    import base64
    import json

    from agents.core.data_export import export_data
    cache = tmp_path / 'media' / 'cache'
    cache.mkdir(parents=True)
    (cache / 'test.pdf').write_bytes(PDF)
    item = MediaCatalog(tmp_path / 'media' / 'catalog.json').add(kind='image', prompt='cached', path=str(cache / 'test.pdf'), now=1)
    document = json.loads(__import__('pathlib').Path(export_data(str(tmp_path))['export']).read_text())
    exported = document['generated_media']['items'][0]
    assert exported['id'] == item['id']
    assert base64.b64decode(exported['base64']) == PDF
    assert 'path' not in exported


def test_catalog_parent_traversal_refused(tmp_path):
    cache = tmp_path / 'media' / 'cache'
    cache.mkdir(parents=True)
    (tmp_path / 'secret.pdf').write_bytes(PDF)
    row = MediaCatalog(tmp_path / 'media' / 'catalog.json').add(kind='image', prompt='outside', path=str(cache / '..' / '..' / 'secret.pdf'), now=1)
    with pytest.raises(ValueError):
        resolve_blob(row['id'], tmp_path)


def _catalog_fixture(root, count=8):
    import json
    cache = root / 'media' / 'cache'
    cache.mkdir(parents=True)
    path = cache / 'clip.pdf'
    path.write_bytes(PDF)
    rows = [{'id': f'md-{i:012x}', 'kind': 'image', 'path': str(path), 'prompt': 'cached'} for i in range(count)]
    (root / 'media' / 'catalog.json').write_text(json.dumps(rows))
    return rows


@pytest.mark.parametrize('operation', ['gallery', 'export_generated'])
def test_operation_reads_catalog_once_regardless_of_item_count(tmp_path, monkeypatch, operation):
    from agents.core import media_library
    _catalog_fixture(tmp_path, 220)
    original = MediaCatalog._load_rows
    reads = []
    def load(self, **kwargs):
        reads.append(1)
        return original(self, **kwargs)
    monkeypatch.setattr(MediaCatalog, '_load_rows', load)
    if operation == 'gallery':
        assert len(media_library.gallery(tmp_path, generated=True)) == 200
    else:
        assert len(media_library.export_generated(tmp_path)['items']) == 220
    assert len(reads) == 1


def test_gallery_defers_full_content_validation_to_delivery(tmp_path, monkeypatch):
    from agents.core import media_library
    rows = _catalog_fixture(tmp_path)
    def no_full_validation(data):
        raise AssertionError('listing must not decode full blobs')
    monkeypatch.setattr(media_library, 'sniff', no_full_validation)
    listed = media_library.gallery(tmp_path, generated=True)
    assert len(listed) == len(rows)
    assert all(row['validation'] == 'on_download' for row in listed)


def test_incomplete_legacy_rows_do_not_break_gallery_or_export(tmp_path):
    import json

    from agents.core.media_library import export_generated, gallery
    rows = _catalog_fixture(tmp_path, 1)
    path = tmp_path / 'media' / 'catalog.json'
    path.write_text(json.dumps([*rows, {'prompt':'missing fields'}, {'id':'md-eeeeeeeeeeee','path':rows[0]['path']}]))
    listed = gallery(tmp_path, generated=True)
    assert [row['id'] for row in listed] == [rows[0]['id']]
    exported = export_generated(tmp_path)
    assert len(exported['items']) == 1
    assert exported['invalid_count'] == 2
    assert exported['complete'] is False


def test_catalog_route_does_not_run_disk_work_on_event_loop(tmp_path, monkeypatch):
    import asyncio

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agents.core import media_library
    from agents.core.routers._deps import user_guard
    from agents.core.routers.multimodal import router
    _catalog_fixture(tmp_path, 1)
    monkeypatch.setenv('JARVIS_HOME', str(tmp_path))
    monkeypatch.setenv('JARVIS_MEDIA_CATALOG', '1')
    original = media_library.gallery_page
    checked = []
    def disk_work(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            checked.append(False)
        except RuntimeError:
            checked.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(media_library, 'gallery_page', disk_work)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[user_guard] = lambda: None
    with TestClient(app) as client:
        assert client.get('/api/media/catalog').status_code == 200
    assert checked == [True]


def test_gallery_header_work_is_bounded_and_corrupt_png_still_refused(tmp_path, monkeypatch):
    from pathlib import Path

    from agents.core import media_library
    rows = _catalog_fixture(tmp_path, 220)
    Path(rows[0]['path']).write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 100000)
    original = media_library._read_bytes
    sizes = []
    def measured(path, limit, **kwargs):
        data, size = original(path, limit, **kwargs)
        sizes.append(len(data))
        return data, size
    monkeypatch.setattr(media_library, '_read_bytes', measured)
    listed = media_library.gallery(tmp_path, generated=True)
    assert len(listed) == 200
    assert sum(sizes) <= 200 * 4096
    assert all(row['validation'] == 'on_download' for row in listed)
    with pytest.raises(ValueError):
        media_library.read_catalog_blob(rows[0]['id'], tmp_path)


def test_snapshot_does_not_bypass_later_symlink_checks(tmp_path):
    from pathlib import Path

    from agents.core.media_library import catalog_snapshot, read_catalog_blob
    rows = _catalog_fixture(tmp_path, 1)
    records, _ = catalog_snapshot(tmp_path)
    path = Path(rows[0]['path'])
    path.unlink()
    secret = tmp_path / 'private.pdf'
    secret.write_bytes(PDF)
    path.symlink_to(secret)
    with pytest.raises(ValueError):
        read_catalog_blob(rows[0]['id'], tmp_path, records=records)
