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
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http', 'websocket'):
            prefix = scope['app'].root_path
            path = scope['path']
            if prefix:
                scope = {**scope, 'path': prefix + path}
                if 'raw_path' in scope:
                    scope['raw_path'] = prefix.encode('ascii') + scope['raw_path']
        await self.app(scope, receive, send)
