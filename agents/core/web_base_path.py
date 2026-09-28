"""Trusted, operator-configured public mount path for the web UI.

No forwarded headers are consulted. Configuration is fixed when the app is built;
request handlers use that app's root_path, not request-supplied URL metadata.
"""
from __future__ import annotations

import json
import re

from .env_config import env_str


def normalize_root_path(value: str) -> str:
    if value in ('', '/'):
        return ''
    path = value.removesuffix('/')
    if not re.fullmatch(r'(?:/[A-Za-z0-9_~.-]+)+', path) or any(
        segment in ('.', '..') for segment in path.split('/')[1:]
    ):
        raise ValueError('JARVIS_ROOT_PATH must be an absolute path of nonempty URL-safe segments')
    return path


def configured_root_path() -> str:
    return normalize_root_path(env_str('JARVIS_ROOT_PATH'))


def render_ui_html(html: str, prefix: str) -> str:
    """Resolve emitted entry tags and bootstrap before any module executes."""
    prefix = normalize_root_path(prefix)
    def asset(match: re.Match) -> str:
        attr, quote, path = match.groups()
        if path.startswith('./assets/'):
            path = '/v2/' + path[2:]
        elif path == './manifest.webmanifest':
            path = '/manifest.webmanifest'
        if path.startswith(('/v2/assets/', '/static/')) or path == '/manifest.webmanifest':
            path = prefix + path
        return f'{attr}={quote}{path}{quote}'
    html = re.sub(r'''(src|href)=(["'])([^"']*)\2''', asset, html)
    encoded = json.dumps(prefix).replace('<', '\\u003c')
    bootstrap = '<script>window.__NERVA_BASE_PATH__=' + encoded + ';' + (
        'window.nervaAppUrl=function(path){return window.__NERVA_BASE_PATH__+path;};</script>'
    )
    return html.replace('<head>', '<head>\n' + bootstrap, 1)


class RootPathRoutingMiddleware:
    """Give Starlette mounts/redirects a consistent public path after stripping.

    Always prepend: a logical path may itself start with the configured prefix
    (e.g. mount /v2 and logical /v2/chat). A non-stripping proxy is unsupported.

    Install first (innermost): outer policy middleware still sees the incoming
    logical path. Copy the scope so those readers cannot observe our adaptation.
    The FastAPI instance supplies root_path; no header can set it.

    The one thing handed back is the router's ``route``: the outer golden-signals
    middleware labels /metrics from ``scope["route"]`` on the scope it passed
    down, so without it every request of a mounted deployment counted as
    ``<unmatched>``. It is copied at each outgoing message — ``call_next`` returns
    at ``http.response.start`` while a streamed body may still run — and once
    more when the app returns or raises.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket') or not scope['app'].root_path:
            await self.app(scope, receive, send)
            return
        prefix = scope['app'].root_path
        inner = {**scope, 'path': prefix + scope['path']}
        if 'raw_path' in inner:
            inner['raw_path'] = prefix.encode('ascii') + inner['raw_path']

        def hand_back_route():
            if 'route' in inner:
                scope['route'] = inner['route']

        async def labelled_send(message):
            hand_back_route()
            await send(message)

        try:
            await self.app(inner, receive, labelled_send)
        finally:
            hand_back_route()
