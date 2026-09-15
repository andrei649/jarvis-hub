"""Bounded full retained-catalog traversal; cursors never authorize file access."""
import json

from agents.core import media_library
from agents.core.media_catalog import MediaCatalog


def catalog(root, count=220):
    cache = root / 'media' / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / 'clip.pdf'
    path.write_bytes(b'%PDF-1.4\n%%EOF')
    rows = [{'id': f'md-{i:012x}', 'kind': 'image', 'path': str(path), 'prompt': 'old needle' if i == 0 else 'recent', 'created_at': i} for i in range(count)]
    (root / 'media' / 'catalog.json').write_text(json.dumps(rows))
    return rows


def test_search_continues_past_empty_page_with_bounded_header_work(tmp_path, monkeypatch):
    catalog(tmp_path)
    load, read = MediaCatalog._load_rows, media_library._read_bytes
    loads, headers = [], []
    def counted_load(self, **kw):
        loads.append(1)
        return load(self, **kw)
    def counted_read(*args, **kw):
        headers.append(args[1])
        return read(*args, **kw)
    monkeypatch.setattr(MediaCatalog, '_load_rows', counted_load)
    monkeypatch.setattr(media_library, '_read_bytes', counted_read)
    first = media_library.gallery_page(tmp_path, generated=True, q='needle')
    assert first['items'] == []
    assert first['page']['scanned'] == 200
    assert first['page']['catalog_total'] == 220
    assert first['page']['has_more']
    assert len(loads) == 1 and len(headers) == 200 and sum(headers) <= 200 * 4096
    second = media_library.gallery_page(tmp_path, generated=True, q='needle', cursor=first['page']['next_cursor'])
    assert [row['id'] for row in second['items']] == ['md-000000000000']
    assert second['page']['scanned'] == 20
    assert not second['page']['has_more']


def test_keyset_survives_deleted_boundary_and_excludes_newer_append(tmp_path):
    rows = catalog(tmp_path, 8)
    first = media_library.gallery_page(tmp_path, generated=True, limit=3)
    remaining = [r for r in rows if r['id'] != first['items'][-1]['id']]
    remaining.append(dict(rows[0], id='md-ffffffffffff', created_at=99))
    (tmp_path / 'media' / 'catalog.json').write_text(json.dumps(remaining))
    seen = [r['id'] for r in first['items']]
    cursor = first['page']['next_cursor']
    while cursor:
        result = media_library.gallery_page(tmp_path, generated=True, limit=3, cursor=cursor)
        seen.extend(r['id'] for r in result['items'])
        cursor = result['page']['next_cursor']
    assert seen == [r['id'] for r in reversed(rows)]


def encode(payload):
    import base64
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')


def decode(token):
    import base64
    return json.loads(base64.urlsafe_b64decode(token + '=' * (-len(token) % 4)))


def test_equal_timestamp_mixed_sources_have_repeatable_complete_order(tmp_path):
    from agents.core.artifact_store import BinaryArtifactStore
    rows = catalog(tmp_path, 5)
    for row in rows:
        row['created_at'] = 1
    (tmp_path / 'media' / 'catalog.json').write_text(json.dumps(rows))
    attachment = BinaryArtifactStore(tmp_path).put(b'%PDF-1.7\nsmall document\n%%EOF', now=1)
    seen, cursor = [], None
    while True:
        page = media_library.gallery_page(tmp_path, generated=True, attached=True, limit=2, cursor=cursor)
        seen.extend(row['id'] for row in page['items'])
        cursor = page['page']['next_cursor']
        if not cursor:
            break
    assert seen == [row['id'] for row in reversed(rows)] + [attachment['id']]


import pytest


@pytest.mark.parametrize('change', [
    lambda p: dict(p, v=True), lambda p: dict(p, extra=1),
    lambda p: dict(p, upper=[True, 'generated', 'md-000000000003']),
    lambda p: dict(p, upper=[float('nan'), 'generated', 'md-000000000003']),
    lambda p: dict(p, upper=[float('inf'), 'generated', 'md-000000000003']),
    lambda p: dict(p, upper=['3', 'generated', 'md-000000000003']),
    lambda p: dict(p, upper=[3, 'unknown', 'md-000000000003']),
    lambda p: dict(p, upper=[3, 'attachment', 'md-000000000003']),
    lambda p: dict(p, after=[99, 'generated', 'md-000000000003']),
    lambda p: dict(p, after=[1, 'generated', '../../private']),
    lambda p: dict(p, after={}),
])
def test_invalid_cursor_rejected_before_catalog_or_file_reads(tmp_path, monkeypatch, change):
    catalog(tmp_path, 4)
    token = media_library.gallery_page(tmp_path, generated=True, limit=1)['page']['next_cursor']
    monkeypatch.setattr(media_library, 'catalog_snapshot', lambda root: pytest.fail('invalid cursor read catalog'))
    with pytest.raises(ValueError, match='invalid_gallery_cursor'):
        media_library.gallery_page(tmp_path, generated=True, cursor=encode(change(decode(token))))


@pytest.mark.parametrize('options', [{'q': 'changed'}, {'kind': 'video'}, {'attached': True}, {'generated': False}])
def test_cursor_filter_and_source_changes_rejected(tmp_path, options):
    catalog(tmp_path, 4)
    token = media_library.gallery_page(tmp_path, generated=True, limit=1)['page']['next_cursor']
    with pytest.raises(ValueError, match='invalid_gallery_cursor'):
        media_library.gallery_page(tmp_path, cursor=token, **({'generated': True} | options))


@pytest.mark.parametrize('token', ['x' * 1025, '@', 'e30', encode([]), encode(None)])
def test_malformed_transport_tokens_are_rejected(tmp_path, token):
    with pytest.raises(ValueError, match='invalid_gallery_cursor'):
        media_library.gallery_page(tmp_path, cursor=token)


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agents.core.routers._deps import user_guard
    from agents.core.routers.multimodal import router
    monkeypatch.setenv('JARVIS_HOME', str(tmp_path))
    monkeypatch.setenv('JARVIS_MEDIA_CATALOG', '1')
    monkeypatch.setenv('JARVIS_BINARY_ARTIFACTS', '0')
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[user_guard] = lambda: None
    return TestClient(app)


def test_route_pagination_stats_and_existing_shape(client, tmp_path):
    catalog(tmp_path)
    first = client.get('/api/media/catalog', params={'q': 'needle', 'limit': 2}).json()
    assert first['enabled'] is True and first['items'] == []
    assert first['stats'] == {'total': 0, 'cloud': 0, 'by_kind': {}}
    assert first['page']['catalog_total'] == 220
    second = client.get('/api/media/catalog', params={'q': 'needle', 'limit': 2, 'cursor': first['page']['next_cursor']}).json()
    assert second['stats'] == {'total': 1, 'cloud': 0, 'by_kind': {'image': 1}}
    assert len(second['items']) == 1 and not second['page']['has_more']
    assert all('path' not in row for row in second['items'])


@pytest.mark.parametrize('params', [{'limit': 0}, {'limit': 201}, {'q': 'x'*257}, {'kind': 'x'*33}, {'cursor': 'x'*1025}, {'cursor': 'garbage'}])
def test_route_rejects_invalid_parameters(client, params):
    assert client.get('/api/media/catalog', params=params).status_code in (400, 422)


def test_route_keeps_guard_and_default_off_contract(client, monkeypatch):
    from fastapi import HTTPException

    from agents.core.routers._deps import user_guard
    def deny():
        raise HTTPException(status_code=401)
    client.app.dependency_overrides[user_guard] = deny
    assert client.get('/api/media/catalog').status_code == 401
    client.app.dependency_overrides[user_guard] = lambda: None
    monkeypatch.setenv('JARVIS_MEDIA_CATALOG', '0')
    assert client.get('/api/media/catalog').json()['enabled'] is False


def test_mime_search_uses_bounded_header_hints_and_kind_has_empty_continuation(tmp_path):
    rows = catalog(tmp_path)
    rows[0]['kind'] = 'video'
    (tmp_path / 'media' / 'catalog.json').write_text(json.dumps(rows))
    first = media_library.gallery_page(tmp_path, generated=True, q='APPLICATION/PDF', kind='video')
    assert first['items'] == [] and first['page']['scanned'] == 200
    second = media_library.gallery_page(tmp_path, generated=True, q='application/pdf', kind='video', cursor=first['page']['next_cursor'])
    assert [r['id'] for r in second['items']] == [rows[0]['id']]
    assert second['stats']['by_kind'] == {'video': 1}


def test_retained_total_is_independent_of_matches_and_availability(tmp_path):
    rows = catalog(tmp_path, 4)
    rows[0]['path'] = '/private/unapproved.pdf'
    (tmp_path / 'media' / 'catalog.json').write_text(json.dumps(rows + [{'id': 'invalid'}]))
    page = media_library.gallery_page(tmp_path, generated=True, q='needle')
    assert page['page']['catalog_total'] == 4
    assert page['page']['invalid_count'] == 1
    assert page['stats']['total'] == 1 and page['items'][0]['available'] is False
    assert 'path' not in page['items'][0]


def test_catalog_export_rejects_more_than_200_ids_before_resolution(client, monkeypatch):
    from agents.core.routers import artifact_store
    client.app.include_router(artifact_store.router)
    monkeypatch.setattr(artifact_store, 'resolve_blob', lambda *a, **kw: pytest.fail('oversized selection resolved a file'))
    response = client.post('/api/media/export', json={'ids': [f'md-{i:012x}' for i in range(201)]})
    assert response.status_code == 422
