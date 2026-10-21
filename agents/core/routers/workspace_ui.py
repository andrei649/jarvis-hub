"""The Nerva Workspace web app shell: ``/workspace`` and below (spec §7 "S6", §6 "Headers").

The workspace is a separate single-page app from the HUD. Vite builds it
(``frontend/vite.workspace.config.ts``, ``base: './'``) into ``agents/web/workspace/``:
one ``workspace.html`` that references its hashed JS and CSS as ``./assets/…``, plus the
fonts the stylesheet loads relative to itself. This module serves that bundle:

* ``GET /workspace`` redirects to ``/workspace/`` (307, root-path aware), so a relative
  link inside the app always resolves under the app;
* ``GET /workspace/`` and ``GET /workspace/{path}`` answer the shell for every client
  route (the app's own router handles ``{path}``), rendered by
  :func:`render_workspace_html`: asset URLs become absolute under the deployment's root
  path, and a one-line bootstrap tells the app that root path before any module runs;
* :class:`WorkspaceAssets` serves ``agents/web/workspace/assets`` (``agents/web.py``
  mounts it at ``/workspace/assets`` before including this router, so it wins).

Why the CSP carries a hash rather than ``'unsafe-inline'``: the bundle has no inline
script of its own; the bootstrap is the only one, it is computed here, so its exact
SHA-256 is known and nothing else inline can run. Everything else — the module, the
stylesheet, the fonts, every API call — is same-origin.

While ``NERVA_WORKSPACE`` is off every path here answers a plain ``404`` page that does
not even name the product; a missing bundle answers ``503`` with the build command. Both
are read per request, so turning the flag on or rebuilding needs no restart.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.staticfiles import PathLike, StaticFiles
from starlette.types import Receive, Scope, Send

from agents.core.web_base_path import normalize_root_path
from agents.core.workspace import config

logger = logging.getLogger("nerva.workspace.ui")

#: The built bundle (``npm run build`` writes it; it is committed like ``agents/web/v2``).
BUNDLE_DIR = Path(__file__).resolve().parents[2] / "web" / "workspace"
SHELL_FILE = BUNDLE_DIR / "workspace.html"
ASSETS_DIR = BUNDLE_DIR / "assets"
#: Where ``agents/web.py`` mounts :class:`WorkspaceAssets`.
ASSETS_MOUNT = "/workspace/assets"

#: Vite names every emitted asset ``<name>-<content hash>.<ext>``, so a URL never changes
#: meaning and the browser may keep it for a year.
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"

_ASSET_REF = re.compile(r"""\b(src|href)=(["'])\./assets/([^"'<>\s]+)\2""")
_HEAD_OPEN = re.compile(r"<head(?:\s[^>]*)?>", re.IGNORECASE)

_ERROR_CSP = "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
_NOT_FOUND_HTML = (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Not Found</title>"
    "</head><body><h1>Not Found</h1></body></html>"
)
_NOT_BUILT_HTML = (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<title>Nerva Workspace is not built</title></head><body>"
    "<h1>Nerva Workspace is not built</h1>"
    "<p>Run <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code> "
    "(it writes <code>agents/web/workspace/</code>), then reload this page.</p>"
    "</body></html>"
)

router = APIRouter()


# ── rendering ────────────────────────────────────────────────────────────────────────

def bootstrap_script(prefix: str) -> str:
    """The one inline script of the shell: ``window.__NERVA_BASE_PATH__ = <root path>``.

    *prefix* is normalized first (``/`` and ``''`` mean no prefix), and ``<`` is escaped
    so no value could ever close the script element early.
    """
    encoded = json.dumps(normalize_root_path(prefix)).replace("<", "\\u003c")
    return f"<script>window.__NERVA_BASE_PATH__={encoded};</script>"


def bootstrap_hash(prefix: str) -> str:
    """The CSP source for :func:`bootstrap_script`: ``'sha256-<base64 digest>'``."""
    script = bootstrap_script(prefix)
    body = script[len("<script>"):-len("</script>")]
    digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode("ascii")
    return f"'sha256-{digest}'"


def shell_csp(prefix: str) -> str:
    """The Content-Security-Policy of the shell (spec §6), pinned to this bootstrap."""
    return (
        "default-src 'self'; "
        f"script-src 'self' {bootstrap_hash(prefix)}; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )


def render_workspace_html(html: str, prefix: str) -> str:
    """The built ``workspace.html`` made ready to serve under the root path *prefix*.

    Every ``src``/``href`` of the form ``./assets/X`` becomes ``<prefix>/workspace/assets/X``
    (absolute, so a deep client route such as ``/workspace/reports/7`` still loads them),
    and :func:`bootstrap_script` is inserted right after ``<head>`` so it runs before the
    module script. Raises ``ValueError`` when the document has no ``<head>`` (a broken
    build: serving it would start the app without its root path).
    """
    root = normalize_root_path(prefix)
    head = _HEAD_OPEN.search(html)
    if head is None:
        raise ValueError("workspace.html has no <head> element")

    def asset(match: re.Match[str]) -> str:
        attr, quote, name = match.groups()
        return f"{attr}={quote}{root}{ASSETS_MOUNT}/{name}{quote}"

    rendered = html[:head.end()] + "\n" + bootstrap_script(root) + html[head.end():]
    return _ASSET_REF.sub(asset, rendered)


# ── responses ────────────────────────────────────────────────────────────────────────

def _error_page(content: str, status: int) -> HTMLResponse:
    return HTMLResponse(content, status_code=status, headers={
        "Cache-Control": "no-store", "Content-Security-Policy": _ERROR_CSP,
        "X-Frame-Options": "DENY"})


def not_found_page() -> HTMLResponse:
    """The plain 404 every workspace UI path answers while ``NERVA_WORKSPACE`` is off."""
    return _error_page(_NOT_FOUND_HTML, 404)


def _shell(request: Request) -> Response:
    if not config.enabled():
        return not_found_page()
    try:
        source = SHELL_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _error_page(_NOT_BUILT_HTML, 503)
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("workspace shell unreadable: %s", type(exc).__name__)
        return _error_page(_NOT_BUILT_HTML, 503)
    prefix = request.app.root_path
    try:
        page = render_workspace_html(source, prefix)
    except ValueError:
        logger.warning("workspace shell has no <head>; rebuild the bundle")
        return _error_page(_NOT_BUILT_HTML, 503)
    return HTMLResponse(page, headers={
        "Cache-Control": "no-store",
        "Content-Security-Policy": shell_csp(prefix),
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin",
    })


# Sync handlers on purpose: they read a small file, which FastAPI runs off the event loop.

@router.get("/workspace", response_class=HTMLResponse)
def workspace_root(request: Request) -> Response:
    """``/workspace`` → ``/workspace/`` (307, query kept), under the root path."""
    if not config.enabled():
        return not_found_page()
    target = normalize_root_path(request.app.root_path) + "/workspace/"
    if request.url.query:
        target += "?" + request.url.query
    return RedirectResponse(target, status_code=307, headers={"Cache-Control": "no-store"})


@router.get("/workspace/", response_class=HTMLResponse)
def workspace_index(request: Request) -> Response:
    """The app shell at the app's root."""
    return _shell(request)


@router.get("/workspace/{path:path}", response_class=HTMLResponse)
def workspace_app(request: Request, path: str) -> Response:
    """The app shell for every client route; the app's own router reads ``path``."""
    return _shell(request)


# ── static assets ────────────────────────────────────────────────────────────────────

class WorkspaceAssets(StaticFiles):
    """The bundle's hashed JS, CSS and fonts, served only while the workspace is enabled.

    A disabled workspace answers the same plain 404 as its pages, so nothing under
    ``/workspace`` reveals that the product is installed. Hashed names make every
    response safe to cache for a year (:data:`IMMUTABLE_CACHE`).
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not config.enabled():
            await not_found_page()(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    def file_response(self, full_path: PathLike, stat_result: os.stat_result, scope: Scope,
                      status_code: int = 200) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = IMMUTABLE_CACHE
        return response


def assets_app() -> WorkspaceAssets | None:
    """The ASGI app ``agents/web.py`` mounts at :data:`ASSETS_MOUNT`; ``None`` without a bundle."""
    if not ASSETS_DIR.is_dir():
        return None
    return WorkspaceAssets(directory=str(ASSETS_DIR))
