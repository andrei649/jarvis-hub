import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

PDF = b'%PDF-1.7\nsmall document\n%%EOF'

@pytest.fixture
def client(tmp_path, monkeypatch):
    from agents.core.routers._deps import user_guard
    from agents.core.routers.artifact_store import router
    monkeypatch.setenv('JARVIS_HOME', str(tmp_path))
    monkeypatch.setenv('JARVIS_BINARY_ARTIFACTS', '1')
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[user_guard] = lambda: None
    return TestClient(app)


def test_upload_delivery_delete(client):
    result = client.post('/api/artifacts', files={'file': ('spoof.png', PDF, 'image/png')})
    assert result.status_code == 201
    row = result.json()
    assert row['mime'] == 'application/pdf'
    assert 'path' not in row
    response = client.get('/api/artifacts/' + row['id'] + '/blob')
    assert response.content == PDF
    assert response.headers['content-disposition'].startswith('attachment;')
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert client.post('/api/artifacts/' + row['id'] + '/pin?pinned=true').json()['pinned']
    assert client.delete('/api/artifacts/' + row['id']).status_code == 200
    assert client.get('/api/artifacts/' + row['id'] + '/blob').status_code == 404


def test_every_route_authenticates(client):
    from agents.core.routers._deps import user_guard
    def denied():
        raise HTTPException(401)
    client.app.dependency_overrides[user_guard] = denied
    for method, path in [('get', '/api/artifacts'), ('post', '/api/artifacts'), ('get', '/api/artifacts/abc/blob'), ('delete', '/api/artifacts/abc'), ('post', '/api/artifacts/abc/pin')]:
        assert getattr(client, method)(path).status_code == 401


def test_default_off_and_spoof(client, monkeypatch):
    assert client.post('/api/artifacts', files={'file': ('bad.png', b'<svg/>', 'image/png')}).status_code == 415
    monkeypatch.delenv('JARVIS_BINARY_ARTIFACTS')
    assert client.get('/api/artifacts').json()['enabled'] is False
    assert client.post('/api/artifacts', files={'file': ('a.pdf', PDF)}).status_code == 409


def test_gallery_export_contains_bytes_and_hash_without_paths(client):
    import hashlib
    import io
    import json
    import zipfile
    row = client.post('/api/artifacts', files={'file': ('a.pdf', PDF)}).json()
    response = client.post('/api/media/export', json={'ids':[row['id']]})
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['items'][0]['sha256'] == hashlib.sha256(PDF).hexdigest()
        assert 'path' not in manifest['items'][0]
        assert archive.read('media/' + row['id']) == PDF


def test_selected_media_export_uses_one_snapshot_off_event_loop(client, monkeypatch):
    import asyncio
    import os
    from pathlib import Path

    from agents.core import media_library
    from agents.core.media_catalog import MediaCatalog
    from tests.test_media_library import _catalog_fixture

    rows = _catalog_fixture(Path(os.environ['JARVIS_HOME']), 20)
    monkeypatch.setenv('JARVIS_MEDIA_CATALOG', '1')
    original_load = MediaCatalog._load_rows
    original_read = media_library.read_catalog_blob
    loads, outside_loop = [], []
    def load(self, **kwargs):
        loads.append(1)
        return original_load(self, **kwargs)
    def read(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            outside_loop.append(False)
        except RuntimeError:
            outside_loop.append(True)
        return original_read(*args, **kwargs)
    monkeypatch.setattr(MediaCatalog, '_load_rows', load)
    monkeypatch.setattr(media_library, 'read_catalog_blob', read)
    assert client.post('/api/media/export', json={'ids':[row['id'] for row in rows]}).status_code == 200
    assert loads == [1]
    assert outside_loop == [True] * len(rows)
