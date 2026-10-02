"""Owner-only Nous account lifecycle and the real Nerva command tree."""

import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.cli import nerva
from agents.core.routers import oauth

PREFIX = '/api/oauth/nous'
PUBLIC = {'profile': 'default', 'authenticated': False, 'usable': False, 'has_refresh_token': False}


@pytest.fixture
def surface(monkeypatch):
    calls = []

    class Service:
        def status(self, profile='default'):
            calls.append(('status', profile))
            return {**PUBLIC, 'profile': profile}

        def start_login(self, profile='default'):
            calls.append(('login', profile))
            return {'login_id': 'flow-123', 'user_code': 'ABCD',
                    'verification_uri': 'https://portal.nousresearch.com/device',
                    'verification_uri_complete': 'https://portal.nousresearch.com/device?code=ABCD',
                    'expires_in': 600, 'interval': 1}

        def poll_login(self, profile, login_id):
            calls.append(('poll', profile, login_id))
            return {'state': 'complete'}

        def logout(self, profile='default'):
            calls.append(('logout', profile))
            return {**PUBLIC, 'profile': profile}

    service = Service()
    monkeypatch.setattr(oauth, '_nous_service', lambda: service, raising=False)
    monkeypatch.setattr(web.app, 'dependency_overrides', {})
    monkeypatch.setattr(web, '_admin_configured', lambda: True)
    monkeypatch.setattr(web, '_admin_credential_ok', lambda token: token == 'owner-test')
    client = TestClient(web.app, headers={'X-Admin-Token': 'owner-test'})
    return SimpleNamespace(client=client, calls=calls, service=service)


@pytest.mark.parametrize('verb,path,body', [
    ('GET', '/status', None), ('POST', '/login', {}),
    ('POST', '/poll', {'login_id': 'flow-123'}), ('POST', '/logout', {}),
])
def test_owner_routes_require_admin_before_calling_service(surface, verb, path, body):
    response = surface.client.request(verb, PREFIX + path, json=body,
                                      headers={'X-Admin-Token': '', 'X-User-Token': 'user-only'})
    assert response.status_code == 401
    assert not surface.calls


@pytest.mark.parametrize('verb,path,body,expected', [
    ('GET', '/status?profile=work', None, ('status', 'work')),
    ('POST', '/login', {'profile': 'work'}, ('login', 'work')),
    ('POST', '/poll', {'profile': 'work', 'login_id': 'flow-123'}, ('poll', 'work', 'flow-123')),
    ('POST', '/logout', {'profile': 'work'}, ('logout', 'work')),
])
def test_owner_route_dispatch_is_nocache(surface, verb, path, body, expected):
    response = surface.client.request(verb, PREFIX + path, json=body)
    assert response.status_code == 200, response.text
    assert 'no-store' in response.headers['cache-control']
    assert surface.calls == [expected]


@pytest.mark.parametrize('profile', ['../other', 'bad name', '', 'x'*65, '\n'])
def test_bad_profile_cannot_reach_store(surface, profile):
    assert surface.client.post(PREFIX + '/login', json={'profile': profile}).status_code == 422
    assert surface.client.get(PREFIX + '/status', params={'profile': profile}).status_code == 422
    assert not surface.calls


def test_unknown_sensitive_fields_are_rejected(surface):
    assert surface.client.post(PREFIX + '/login', json={'refresh_token': 'should-not-be-input'}).status_code == 422
    assert not surface.calls


def test_unexpected_service_failure_has_no_private_diagnostic(surface):
    def broken(profile):
        raise RuntimeError('private refresh credential')
    surface.service.status = broken
    response = surface.client.get(PREFIX + '/status')
    assert response.status_code == 503
    assert 'private' not in response.text and 'refresh credential' not in response.text


class Routed:
    def __init__(self, client):
        self.client = client

    def get(self, path):
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def post(self, path, body=None, *, timeout=None):
        response = self.client.post(path, json=body)
        response.raise_for_status()
        return response.json()


def run(argv, hub):
    out, err = io.StringIO(), io.StringIO()
    context = nerva.Context(environ={}, out=out, err=err, client_factory=lambda env: hub)
    return nerva.main(['auth', 'nous', *argv], context=context), out.getvalue(), err.getvalue()


def test_cli_status_and_logout_use_owner_routes(surface):
    code, output, _ = run(['status', '--profile', 'work', '--json'], Routed(surface.client))
    assert code == 0 and '"profile": "work"' in output
    assert run(['logout', '--profile', 'work'], Routed(surface.client))[0] == 0
    assert surface.calls == [('status', 'work'), ('logout', 'work')]


def test_cli_login_prints_verification_and_polls_owner_route(surface, monkeypatch):
    # Login must be a reachable command, not a helper tested without its parser.
    monkeypatch.setattr('time.sleep', lambda delay: None)
    code, output, error = run(['login', '--profile', 'work'], Routed(surface.client))
    assert code == 0, error
    assert 'https://portal.nousresearch.com/device' in output and 'ABCD' in output
    assert surface.calls == [('login', 'work'), ('poll', 'work', 'flow-123')]


def test_cli_invalid_profile_refuses_before_hub():
    code, _, _ = run(['status', '--profile', '../other'], None)
    assert code == 2


def test_real_cli_device_flow_encrypts_credentials_and_logout_invalidates_them(surface, monkeypatch, tmp_path):
    import base64
    import json

    import httpx

    from agents.core.llm import nous_auth
    from agents.core.llm.nous_credentials import NousAuthStore

    now = [1_800_000_000.0]
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b'=').decode()
    access = part({'alg': 'HS256'}) + '.' + part({'scope': 'inference:invoke', 'exp': now[0] + 3600}) + '.signature'
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.path.endswith('/device/code'):
            return httpx.Response(200, json={
                'device_code': 'synthetic-private-device-grant', 'user_code': 'TEST-CODE',
                'verification_uri': 'https://portal.nousresearch.com/device',
                'verification_uri_complete': 'https://portal.nousresearch.com/device?code=TEST-CODE',
                'expires_in': 600, 'interval': 5})
        return httpx.Response(200, json={'access_token': access,
            'refresh_token': 'synthetic-private-refresh-grant', 'scope': 'inference:invoke', 'expires_in': 3600})
    monkeypatch.setattr(nous_auth, '_transport_factory', lambda: httpx.MockTransport(respond))
    store = NousAuthStore(tmp_path / 'account.sqlite3')
    service = nous_auth.NousAuthService(store, env={'JARVIS_NOUS_CLIENT_ID': 'nerva-fixture'}, clock=lambda: now[0])
    monkeypatch.setattr(oauth, '_nous_service', lambda: service)
    monkeypatch.setattr('time.sleep', lambda delay: now.__setitem__(0, now[0] + delay))
    hub = Routed(surface.client)
    assert run(['status'], hub)[0] == 0 and not store.path.exists()
    code, output, error = run(['login', '--profile', 'work'], hub)
    assert code == 0, error
    assert 'TEST-CODE' in output and len(calls) == 2
    assert service.prepare_credentials('work').api_key == access
    code, status, _ = run(['status', '--profile', 'work', '--json'], hub)
    assert code == 0 and '"usable": true' in status
    for secret in (access, 'synthetic-private-device-grant', 'synthetic-private-refresh-grant'):
        assert secret not in output + error + status
        assert all(secret.encode() not in path.read_bytes() for path in tmp_path.iterdir() if path.is_file())
    assert run(['logout', '--profile', 'work'], hub)[0] == 0
    assert store.read('work') == {} and len(calls) == 2


def test_cli_status_projects_only_safe_public_fields():
    class Hub:
        def get(self, path):
            return {**PUBLIC, 'access_token': 'private-unexpected-value'}
    code, output, _ = run(['status', '--json'], Hub())
    assert code == 0 and 'private-unexpected-value' not in output and 'access_token' not in output


def test_cli_denied_or_expired_login_is_not_success(monkeypatch):
    monkeypatch.setattr('time.sleep', lambda delay: None)
    class Hub:
        def post(self, path, body=None, *, timeout=None):
            if path.endswith('/poll'):
                return {'state': 'expired'}
            return {'login_id': 'flow', 'user_code': 'TEST', 'verification_uri': 'https://portal.nousresearch.com/device',
                    'interval': 1, 'expires_in': 600}
    code, _, error = run(['login'], Hub())
    assert code == 1 and 'expired' in error


@pytest.mark.parametrize('uri', ['javascript:alert(1)', 'https://user:pass@example.com/', 'https://portal.nousresearch.com/\nspoof'])
def test_cli_malformed_verification_link_refuses_before_display(uri):
    class Hub:
        def post(self, path, body=None, *, timeout=None):
            return {'login_id': 'flow', 'user_code': 'TEST', 'verification_uri': uri, 'interval': 1, 'expires_in': 600}
    code, output, error = run(['login'], Hub())
    assert code == 5 and uri not in output and 'invalid' in error
