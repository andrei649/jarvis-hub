"""H130 runtime mounting: real application responses, without starting providers."""
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'agents')]
from agents import web


@pytest.fixture
def prefixed(monkeypatch):
    monkeypatch.setattr(web.app, 'root_path', '/nerva')
    return TestClient(web.app)


@pytest.mark.parametrize('path', ['/nerva/', '/nerva/v2/chat', '/nerva/v2/console/decision-inbox'])
def test_prefixed_shell_bootstraps_before_modules(prefixed, path):
    response = prefixed.get(path.removeprefix('/nerva') or '/')
    assert response.status_code == 200
    html = response.text
    assert 'window.__NERVA_BASE_PATH__="/nerva"' in html
    assert html.index('window.__NERVA_BASE_PATH__') < html.index('type="module"')
    assert re.search(r'(src|href)="/nerva/v2/assets/', html)
    assert 'href="/nerva/manifest.webmanifest"' in html
    assert 'no-store' in response.headers['cache-control']


def test_forwarded_prefix_cannot_change_deployment(prefixed):
    response = prefixed.get('/v2/chat', headers={'X-Forwarded-Prefix': '/attacker'})
    assert 'window.__NERVA_BASE_PATH__="/nerva"' in response.text
    assert '/attacker' not in response.text


def test_prefix_manifest_worker_and_missing_asset(prefixed):
    manifest = prefixed.get('/manifest.webmanifest').json()
    assert manifest['start_url'] == manifest['scope'] == '/nerva/'
    assert manifest['icons'][0]['src'] == '/nerva/static/favicon.svg'
    assert prefixed.get('/sw-v2.js').headers['service-worker-allowed'] == '/nerva/'
    missing = prefixed.get('/v2/assets/missing.js')
    assert missing.status_code == 404
    assert 'text/html' not in missing.headers['content-type']


@pytest.mark.parametrize('path,api', [('/map', '/api/system-map'), ('/mission-control', '/api/swarm/summary')])
def test_linked_pages_receive_same_bootstrap(prefixed, path, api):
    response = prefixed.get(path)
    assert response.status_code == 200
    assert 'window.__NERVA_BASE_PATH__="/nerva"' in response.text
    assert 'fetch(window.nervaAppUrl(' in response.text
    assert api in response.text


@pytest.mark.parametrize('value', ['https://evil.test', '//evil', '/a//b', '/a/../b', '/.', '/a%2fb', '/x?y', '/x#y', '/x\\y', '/x\n'])
def test_invalid_operator_prefix_is_rejected(monkeypatch, value):
    from agents.core.web_base_path import configured_root_path
    monkeypatch.setenv('JARVIS_ROOT_PATH', value)
    with pytest.raises(ValueError, match='JARVIS_ROOT_PATH'):
        configured_root_path()


@pytest.mark.parametrize('value,expected', [('', ''), ('/', ''), ('/one/', '/one'), ('/one/two', '/one/two')])
def test_prefix_configuration_is_explicit(monkeypatch, value, expected):
    from agents.core.web_base_path import configured_root_path
    monkeypatch.setenv('JARVIS_ROOT_PATH', value)
    assert configured_root_path() == expected


def test_shell_preserves_external_urls_and_script_text():
    from agents.core.web_base_path import render_ui_html
    html = '<head><script>const external="https://x.test";</script><link href="https://x.test/icon"><script type="module" src="./assets/entry.js"></script></head>'
    result = render_ui_html(html, '/one')
    assert 'src="/one/v2/assets/entry.js"' in result
    assert 'href="https://x.test/icon"' in result
    assert 'const external="https://x.test"' in result


def test_framework_slash_redirect_keeps_prefix(prefixed):
    response = prefixed.get('/static', follow_redirects=False)
    assert response.status_code in (307, 308)
    assert response.headers['location'].endswith('/nerva/static/')


def test_static_mount_serves_actual_asset_after_proxy_strips_prefix(prefixed):
    asset = next((ROOT / 'agents/web/v2/assets').glob('index-*.js')).name
    for path in ['/v2/assets/' + asset]:
        response = prefixed.get(path.removeprefix('/nerva') or '/')
        assert response.status_code == 200
        assert response.content == (ROOT / 'agents/web/v2/assets' / asset).read_bytes()


@pytest.mark.asyncio
async def test_route_scope_adaptation_does_not_mutate_outer_policy_scope():
    from types import SimpleNamespace

    from agents.core.web_base_path import RootPathRoutingMiddleware
    received = []
    async def inner(scope, receive, send):
        received.append(scope)
    outer = {'type': 'http', 'app': SimpleNamespace(root_path='/one'),
             'path': '/api/system-map', 'raw_path': b'/api/system-map', 'root_path': '/one'}
    await RootPathRoutingMiddleware(inner)(outer, None, None)
    assert outer['path'] == '/api/system-map'
    assert outer['raw_path'] == b'/api/system-map'
    assert received[0]['path'] == '/one/api/system-map'
    assert received[0]['raw_path'] == b'/one/api/system-map'


def test_polling_cache_policy_still_sees_logical_path(prefixed):
    response = prefixed.get('/api/system-map')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('prefix,path', [('/v2','/v2/chat'), ('/api','/api/system-map')])
def test_mount_prefix_can_match_a_logical_route_segment(monkeypatch, prefix, path):
    monkeypatch.setattr(web.app, 'root_path', prefix)
    response = TestClient(web.app).get(path)
    assert response.status_code == 200
    if path.endswith('/chat'):
        assert f'window.__NERVA_BASE_PATH__="{prefix}"' in response.text
    else:
        assert 'topology' in response.json()


def test_a_mounted_deployment_keeps_the_route_label_in_the_golden_signals(prefixed):
    # The router writes scope["route"] into the scope this middleware hands it; the
    # outer golden-signals middleware reads its label from the scope it passed down.
    # Adapting a copy would count every request of a JARVIS_ROOT_PATH deployment as
    # "<unmatched>" — /metrics would show one route and no latency per endpoint.
    from agents.core.observability.http_metrics import HTTP_METRICS

    path = '/api/system-map'
    matched, unmatched = HTTP_METRICS.count('GET', path), HTTP_METRICS.count('GET', '<unmatched>')
    assert prefixed.get(path).status_code == 200
    assert HTTP_METRICS.count('GET', path) - matched == 1
    assert HTTP_METRICS.count('GET', '<unmatched>') == unmatched


def test_an_unrouted_path_under_the_mount_still_folds_into_unmatched(prefixed):
    from agents.core.observability.http_metrics import HTTP_METRICS

    unmatched = HTTP_METRICS.count('GET', '<unmatched>')
    assert prefixed.get('/api/no-such-route-xyz').status_code == 404
    assert HTTP_METRICS.count('GET', '<unmatched>') - unmatched == 1


@pytest.mark.asyncio
async def test_the_route_reaches_the_outer_scope_before_the_response_starts():
    # BaseHTTPMiddleware's call_next returns at http.response.start, while a streaming
    # body may still be running — the label must be on the outer scope by then, and a
    # handler that raises after routing must still leave it there.
    from types import SimpleNamespace

    from agents.core.web_base_path import RootPathRoutingMiddleware
    route = SimpleNamespace(path='/api/thing')
    seen = []
    outer = {'type': 'http', 'app': SimpleNamespace(root_path='/one'), 'path': '/api/thing'}

    async def inner(scope, receive, send):
        scope['route'] = route
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b''})

    async def send(message):
        seen.append((message['type'], outer.get('route')))

    await RootPathRoutingMiddleware(inner)(outer, None, send)
    assert seen[0] == ('http.response.start', route)
    assert outer['path'] == '/api/thing'

    async def raising(scope, receive, send):
        scope['route'] = route
        raise RuntimeError('handler failed after routing')

    outer = {'type': 'http', 'app': SimpleNamespace(root_path='/one'), 'path': '/api/thing'}
    with pytest.raises(RuntimeError):
        await RootPathRoutingMiddleware(raising)(outer, None, send)
    assert outer['route'] is route
