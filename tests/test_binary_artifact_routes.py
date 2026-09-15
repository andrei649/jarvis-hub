import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

PDF = b'%PDF-1.7\nsmall document\n%%EOF'

@pytest.fixture
def client(tmp_path, monkeypatch):
    from agents.core.routers.artifact_store import router
    from agents.core.routers._deps import user_guard
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
