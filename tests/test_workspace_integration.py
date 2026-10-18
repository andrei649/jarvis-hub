"""Nerva Workspace wired into the real hub app (spec §7 "S6", §6 "Headers"/"Rate limits", §11).

The slice suites build a bare app with ``make_app``; this file drives ``agents.web.app``
itself — the hub's middleware stack, its error handlers, its root-path adapter, its
per-IP limiter and its lifespan — to prove the integration rather than the slices:

* the SPA shell at ``/workspace/`` with its bootstrap, a CSP whose hash is exactly that
  bootstrap's, absolute asset URLs (root-path aware) and assets served with the right
  types;
* errors: workspace JSON keeps ``{"error", "message"}`` (also for an unhandled exception),
  while every hub path keeps FastAPI's default validation body and the hub's own 500;
* the hub limiter never counts workspace traffic; the scheduler follows the lifespan;
* with ``NERVA_WORKSPACE`` off, every workspace path — API, shell and assets — is a 404;
* one journey across the real app: setup, upload, a streamed cited answer, the audit.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.requests import Request

from agents import web
from agents.core.routers import workspace_ui
from agents.core.workspace import effects_api, scheduler
from agents.core.workspace import errors as ws_errors
from agents.core.workspace import identity as ws_identity
from tests._route_introspect import iter_effective_routes
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    DEFAULT_PASSWORD,
    SETUP_CODE,
    FakeEngine,
    authed,
    db,
    login,
    make_user,
    origin_of,
    seed_company,
    ws,
)
from tests.test_workspace_assistant_helpers import (
    SSE_ACCEPT,
    live_answers,
    message_row,
    new_conversation,
    parse_sse,
)

REPO = Path(__file__).resolve().parent.parent
BUNDLE = REPO / "agents" / "web" / "workspace"
_BOOTSTRAP = re.compile(r"<head>\n<script>(window\.__NERVA_BASE_PATH__=[^<]*)</script>")


def _bundle_assets() -> list[str]:
    """The ``./assets/…`` names the committed workspace.html references."""
    html = (BUNDLE / "workspace.html").read_text(encoding="utf-8")
    return re.findall(r"""(?:src|href)=["']\./assets/([^"']+)["']""", html)


def _csp_hash(script_body: str) -> str:
    digest = hashlib.sha256(script_body.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def _script_src(csp: str) -> list[str]:
    directive = next(part.strip() for part in csp.split(";") if part.strip().startswith("script-src"))
    return directive.split()[1:]


@pytest.fixture
def client(ws):
    return TestClient(web.app)


@pytest.fixture
def prefixed(ws, monkeypatch):
    """The hub deployed under ``/nerva`` (JARVIS_ROOT_PATH); requests use logical paths,
    as a stripping reverse proxy forwards them."""
    monkeypatch.setattr(web.app, "root_path", "/nerva")
    return TestClient(web.app)


pytestmark = pytest.mark.skipif(not (BUNDLE / "workspace.html").is_file(),
                                reason="the workspace bundle is not built")


# ── the shell ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/workspace/", "/workspace/assistant/12",
                                  "/workspace/admin/users", "/workspace/invite"])
def test_every_client_route_gets_the_shell_with_its_bootstrap_and_csp(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    html = response.text
    bootstrap = _BOOTSTRAP.search(html)
    assert bootstrap is not None, "the bootstrap must come right after <head>"
    assert bootstrap.group(1) == 'window.__NERVA_BASE_PATH__="";'
    assert html.index("__NERVA_BASE_PATH__") < html.index('type="module"')
    # Exactly one inline script, and the CSP allows exactly that one by its hash.
    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    assert inline == ["<script>"]
    csp = response.headers["content-security-policy"]
    assert _script_src(csp) == ["'self'", _csp_hash(bootstrap.group(1))]
    assert "'unsafe-inline'" not in " ".join(_script_src(csp))
    for directive in ("default-src 'self'", "style-src 'self' 'unsafe-inline'",
                      "img-src 'self' data: blob:", "font-src 'self'", "connect-src 'self'",
                      "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
                      "form-action 'self'"):
        assert directive in csp
    # Asset URLs are absolute, so a deep client route still loads them.
    assert "./assets/" not in html
    for name in _bundle_assets():
        assert f'"/workspace/assets/{name}"' in html


def test_bare_workspace_redirects_into_the_app_and_keeps_the_query(client):
    response = client.get("/workspace", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (307, "/workspace/")
    response = client.get("/workspace?lang=en", follow_redirects=False)
    assert response.headers["location"] == "/workspace/?lang=en"


def test_assets_are_served_with_their_types_and_cached_for_good(client):
    types = {".js": "text/javascript", ".css": "text/css"}
    names = _bundle_assets()
    assert {Path(name).suffix for name in names} >= {".js", ".css"}
    for name in names:
        response = client.get(f"/workspace/assets/{name}")
        assert response.status_code == 200, name
        assert response.headers["content-type"].startswith(types[Path(name).suffix])
        assert response.headers["cache-control"] == workspace_ui.IMMUTABLE_CACHE
        assert response.headers["x-content-type-options"] == "nosniff"
    css_name = next(name for name in names if name.endswith(".css"))
    css = client.get(f"/workspace/assets/{css_name}").text
    fonts = sorted(set(re.findall(r"url\(\"?\.?/?([^)\"]+\.woff2)\"?\)", css)))
    assert len(fonts) == 4, fonts  # Space Grotesk + JetBrains Mono, latin + latin-ext
    for font in fonts:
        response = client.get(f"/workspace/assets/{Path(font).name}")
        assert response.status_code == 200, font
        assert response.headers["content-type"] == "font/woff2"
        assert response.content[:4] == b"wOF2"


def test_a_missing_asset_is_a_plain_404_not_the_shell(client):
    response = client.get("/workspace/assets/workspace-missing.js")
    assert response.status_code == 404
    assert "text/html" not in response.headers.get("content-type", "")


def test_a_root_path_deployment_prefixes_assets_redirect_bootstrap_and_hash(prefixed):
    response = prefixed.get("/workspace/reports")
    assert response.status_code == 200
    html = response.text
    bootstrap = _BOOTSTRAP.search(html)
    assert bootstrap is not None and bootstrap.group(1) == 'window.__NERVA_BASE_PATH__="/nerva";'
    assert _script_src(response.headers["content-security-policy"]) == [
        "'self'", _csp_hash(bootstrap.group(1))]
    for name in _bundle_assets():
        assert f'"/nerva/workspace/assets/{name}"' in html
    redirect = prefixed.get("/workspace", follow_redirects=False)
    assert redirect.headers["location"] == "/nerva/workspace/"
    js = next(name for name in _bundle_assets() if name.endswith(".js"))
    assert prefixed.get(f"/workspace/assets/{js}").status_code == 200


def test_a_root_path_deployment_scopes_the_session_cookie(prefixed):
    conn = db()
    company = seed_company(conn)
    conn.close()
    response = prefixed.post("/api/workspace/login", headers={"Origin": origin_of(prefixed)},
                             json={"email": company.member_a.email, "password": DEFAULT_PASSWORD})
    assert response.status_code == 200, response.text
    cookie = response.headers["set-cookie"]
    assert "nerva_ws_session=" in cookie and "Path=/nerva/api/workspace" in cookie
    assert "httponly" in cookie.lower() and "samesite=lax" in cookie.lower()


def test_render_rejects_a_bundle_without_head():
    with pytest.raises(ValueError):
        workspace_ui.render_workspace_html("<html><body></body></html>", "")


def test_a_missing_bundle_is_an_honest_503(client, monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_ui, "SHELL_FILE", tmp_path / "absent.html")
    response = client.get("/workspace/")
    assert response.status_code == 503
    assert "npm run build" in response.text
    assert response.headers["cache-control"] == "no-store"


# ── errors keep their shapes ─────────────────────────────────────────────────────────

def test_the_workspace_handlers_are_registered_on_the_hub_app():
    assert web.app.exception_handlers[ws_errors.WorkspaceError] is ws_errors.workspace_error_handler
    assert web.app.exception_handlers[RequestValidationError] is ws_errors.validation_error_handler


def test_workspace_errors_are_workspace_json(client):
    unauthenticated = client.get("/api/workspace/me")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"] == "auth_required"
    assert unauthenticated.headers["cache-control"] == "no-store"
    conn = db()
    company = seed_company(conn)
    conn.close()
    login(client, company.member_a.email)
    malformed = client.get("/api/workspace/documents/not-a-number")
    assert malformed.status_code == 422
    assert malformed.json() == {"error": "invalid_request", "message": "invalid value for document_id",
                                "field": "document_id", "reason": "type"}
    huge = client.get(f"/api/workspace/documents/{10 ** 20}")
    assert (huge.status_code, huge.json()["reason"]) == (422, "too_large")


def test_hub_validation_errors_keep_fastapis_default_body(client):
    response = client.post("/chat", json={})
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail"} and isinstance(body["detail"], list)
    assert "error" not in body


def test_an_unhandled_workspace_exception_is_a_workspace_500(ws, monkeypatch):
    def broken(conn):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(ws_identity, "ensure_org", broken)
    client = TestClient(web.app, raise_server_exceptions=False)
    response = client.get("/api/workspace/session")
    assert response.status_code == 500
    assert response.json() == {"error": "internal_error", "message": "Internal server error"}
    assert response.headers["cache-control"] == "no-store"
    assert "database exploded" not in response.text


def _request(path: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
                    "root_path": "", "query_string": b"", "headers": [], "app": web.app,
                    "server": ("testserver", 80), "scheme": "http"})


def test_the_hub_500_keeps_its_own_shape_outside_the_workspace():
    hub = asyncio.run(web.generic_error_handler(_request("/status"), RuntimeError("x")))
    assert json.loads(hub.body)["code"] == "JARVIS-INTERNAL-001"
    ws_500 = asyncio.run(web.generic_error_handler(_request("/api/workspace/me"), RuntimeError("x")))
    assert json.loads(ws_500.body)["error"] == "internal_error"


# ── the hub limiter and the lifespan ─────────────────────────────────────────────────

@pytest.mark.parametrize("path,expected", [
    ("/api/workspace", True), ("/api/workspace/login", True), ("/workspace", True),
    ("/workspace/", True), ("/workspace/assets/a.js", True),
    ("/api/workspaces", False), ("/workspacex", False), ("/api/work", False), ("/v2", False),
])
def test_workspace_paths_are_recognised_exactly(path, expected):
    assert web._is_workspace_path(path) is expected


# ── CORS: JARVIS_CORS_ORIGINS never reaches the workspace (review fix OPS-04) ──────────

LISTED_ORIGIN = "https://intranet.acme.test"


def _hub_with_cors():
    """The hub app behind the CORS middleware web.py installs for JARVIS_CORS_ORIGINS."""
    from agents.core.workspace.http import WorkspaceExemptCORSMiddleware

    return WorkspaceExemptCORSMiddleware(web.app, allow_origins=[LISTED_ORIGIN],
                                         allow_credentials=True, allow_methods=["*"],
                                         allow_headers=["*"])


def _cors_headers(response) -> list[str]:
    return [name for name in response.headers if name.lower().startswith("access-control-")]


def test_a_listed_cors_origin_cannot_read_a_signed_in_users_workspace(ws):
    conn = db()
    company = seed_company(conn)
    client = TestClient(_hub_with_cors())
    login(client, company.member_a.email)
    session = client.get("/api/workspace/session", headers={"Origin": LISTED_ORIGIN})
    assert session.status_code == 200 and session.json()["authenticated"] is True
    assert _cors_headers(session) == [], "a credentialed CORS read would expose the csrf_token"
    preflight = client.options("/api/workspace/documents", headers={
        "Origin": LISTED_ORIGIN, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-csrf-token"})
    assert _cors_headers(preflight) == [] and preflight.status_code != 200
    assert _cors_headers(client.get("/workspace/", headers={"Origin": LISTED_ORIGIN})) == []
    hub = client.get("/healthz", headers={"Origin": LISTED_ORIGIN})
    assert hub.headers.get("access-control-allow-origin") == LISTED_ORIGIN, \
        "the hub's own CORS keeps working"


@pytest.mark.parametrize("scope,expected", [
    ({"path": "/api/workspace/session", "root_path": ""}, True),
    ({"path": "/nerva/api/workspace/session", "root_path": "/nerva"}, True),
    ({"path": "/nerva/workspace/", "root_path": "/nerva"}, True),
    ({"path": "/workspace", "root_path": ""}, True),
    ({"path": "/api/workspaces", "root_path": ""}, False),
    ({"path": "/nerva/healthz", "root_path": "/nerva"}, False),
])
def test_the_cors_exemption_matches_workspace_paths_root_path_aware(scope, expected):
    from agents.core.workspace.http import is_workspace_scope

    assert is_workspace_scope({"type": "http", **scope}) is expected


def test_the_hub_installs_only_the_workspace_exempt_cors_middleware():
    import ast

    tree = ast.parse((REPO / "agents" / "web.py").read_text(encoding="utf-8"))
    installed = [node.args[0].id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "add_middleware" and node.args
                 and isinstance(node.args[0], ast.Name) and "CORS" in node.args[0].id]
    assert installed == ["WorkspaceExemptCORSMiddleware"]


def test_the_hub_limiter_never_counts_workspace_traffic(client, monkeypatch):
    monkeypatch.setattr(web, "RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(web, "USER_TOKEN", "")
    monkeypatch.setattr(web, "_rate_hits", {})
    js = next(name for name in _bundle_assets() if name.endswith(".js"))
    for attempt in range(5):
        assert client.get("/api/workspace/session").status_code == 200
        assert client.get("/workspace/").status_code == 200
        assert client.get(f"/workspace/assets/{js}").status_code == 200
        # A different email each time stays clear of the workspace's own per-email throttle.
        assert client.post("/api/workspace/login", headers={"Origin": origin_of(client)},
                           json={"email": f"x{attempt}@acme.test", "password": "y"},
                           ).status_code != 429
    assert web._rate_hits == {}, "workspace requests must not fill the hub's buckets"
    # The limiter itself is live: a hub path from the same client is throttled.
    assert [client.get("/status").status_code == 429 for _ in range(3)] == [False, False, True]


def test_the_scheduler_starts_and_stops_with_the_hub(ws):
    assert scheduler._scheduler is None
    with TestClient(web.app, client=("127.0.0.1", 50000)) as client:
        running = scheduler._scheduler
        assert running is not None and running.running
        assert client.get("/workspace/").status_code == 200
    assert scheduler._scheduler is None and not running.running


def test_shutdown_stops_the_scheduler_before_the_orchestrator_closes():
    source = (REPO / "agents" / "web.py").read_text(encoding="utf-8")
    lifespan = source.split("async def lifespan(application: FastAPI):", 1)[1]
    startup, shutdown = lifespan.split("\n    yield\n", 1)
    assert "workspace_scheduler.start_background()" in startup
    assert shutdown.index("await workspace_scheduler.stop_background()") < shutdown.index(
        "await orch.aclose()")


def test_importing_the_hub_registers_every_approval_effect():
    assert {"document.company_publish", "report.delivery", "report.share_company",
            "email.send"} <= set(effects_api.kinds())


# ── the flag off ─────────────────────────────────────────────────────────────────────

def _workspace_routes() -> list[tuple[str, str]]:
    found = []
    for route in iter_effective_routes(web.app):
        path = getattr(route, "path", "")
        if not web._is_workspace_path(path) or not getattr(route, "methods", None):
            continue
        for method in sorted(set(route.methods) - {"HEAD", "OPTIONS"}):
            found.append((method, path))
    return found


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path.replace("{path:path}", "reports/1"))


def test_with_the_flag_off_every_workspace_path_is_a_404(ws, monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE", "0")
    client = TestClient(web.app)
    routes = _workspace_routes()
    assert len(routes) >= 60, routes
    headers = {"Origin": origin_of(client), "X-CSRF-Token": "x"}
    for method, path in routes:
        kwargs = {"json": {}} if method in {"POST", "PUT", "PATCH"} else {}
        response = client.request(method, _concrete(path), headers=headers, **kwargs)
        assert response.status_code == 404, (method, path, response.status_code)
        if path.startswith("/api/workspace"):
            assert response.json()["error"] == "workspace_disabled", (method, path)
        else:
            assert "Workspace" not in response.text, (method, path)
    redirect = client.get("/workspace", follow_redirects=False)
    assert redirect.status_code == 404
    for name in _bundle_assets():
        response = client.get(f"/workspace/assets/{name}")
        assert response.status_code == 404 and "Workspace" not in response.text
    assert not (ws.data_dir / "business" / "workspace.db").exists()


# ── one journey across the real app ──────────────────────────────────────────────────

POLICY = ("Politica de concediu: fiecare angajat are dreptul la 21 de zile lucrătoare de "
          "concediu de odihnă pe an. Cererea se depune cu cel puțin 10 zile înainte.")


def test_setup_upload_and_a_streamed_cited_answer_through_the_hub(client):
    session = client.get("/api/workspace/session").json()
    assert (session["enabled"], session["setup_required"], session["authenticated"]) == (
        True, True, False)
    setup = client.post("/api/workspace/setup", headers={"Origin": origin_of(client)}, json={
        "setup_code": SETUP_CODE, "org_name": "Acme SRL", "name": "Ana Admin",
        "email": "ana@acme.test", "password": DEFAULT_PASSWORD, "locale": "ro"})
    assert setup.status_code == 201, setup.text
    csrf = setup.json()["csrf_token"]
    department_id = setup.json()["user"]["department_ids"][0]

    upload = client.post(
        f"/api/workspace/documents?department_id={department_id}&filename=concediu.txt",
        content=POLICY.encode("utf-8"),
        headers={**authed(client, csrf), "Content-Type": "application/octet-stream"})
    assert upload.status_code == 201, upload.text
    assert upload.json()["status"] == "ready"

    conversation = client.post("/api/workspace/conversations", headers=authed(client, csrf),
                               json={"department_id": department_id})
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    with client.stream("POST", f"/api/workspace/conversations/{conversation_id}/messages",
                       json={"content": "Câte zile de concediu de odihnă am pe an?"},
                       headers={**authed(client, csrf), **SSE_ACCEPT}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-store"
        body = "".join(response.iter_text())
    events = [name for name, _ in parse_sse(body) if name != "ping"]
    assert events[0] == "start" and events[1] == "sources" and events[-1] == "done"
    assert "token" in events and "error" not in events
    done = dict(parse_sse(body))["done"]["assistant_message"]
    assert done["status"] == "complete"
    assert [c["title"] for c in done["citations"]] == ["concediu"]
    assert "[1]" in done["content"]

    audit = client.get("/api/workspace/admin/audit").json()["items"]
    actions = {item["action"] for item in audit}
    assert {"auth.setup", "document.uploaded", "chat.asked"} <= actions
    verified = client.get("/api/workspace/admin/audit/verify").json()
    assert verified["ok"] is True and verified["checked"] >= 3


LONG_REPLY = ("Conform politicii interne, concediul anual de odihnă este de 21 de zile "
              "lucrătoare, iar cererea se depune cu cel puțin zece zile înainte. ") * 4


async def test_a_client_that_goes_away_cancels_the_answer_under_the_hub_middleware(ws):
    """The disconnect path through the hub's own BaseHTTPMiddleware stack (the slice
    proves it on a bare app): uvicorn's ``http.disconnect`` after the first token must
    still reach the stream, cancel the model call and store the answer as cancelled."""
    engine = ws.use_engine(FakeEngine(reply=LONG_REPLY, token_delay=0.02))
    conn = db()
    company = seed_company(conn)
    client = TestClient(web.app)
    csrf = login(client, company.member_a.email)
    conversation_id = new_conversation(client, csrf, company.dept_a)
    path = f"/api/workspace/conversations/{conversation_id}/messages"
    body = json.dumps({"content": "Câte zile de concediu avem?"}).encode("utf-8")
    cookie = f"nerva_ws_session={client.cookies.get('nerva_ws_session')}"
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "root_path": "", "client": ("127.0.0.1", 50000),
             "server": ("testserver", 80),
             "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                         (b"content-length", str(len(body)).encode()),
                         (b"accept", b"text/event-stream"),
                         (b"origin", origin_of(client).encode()),
                         (b"x-csrf-token", csrf.encode()), (b"cookie", cookie.encode())]}
    first_token = asyncio.Event()
    request_sent = False
    sent: list[bytes] = []

    async def receive() -> dict:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await first_token.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.body":
            sent.append(message.get("body", b""))
            if b"event: token" in message.get("body", b""):
                first_token.set()

    try:
        await asyncio.wait_for(web.app(scope, receive, send), timeout=10)
        events = parse_sse(b"".join(sent).decode("utf-8"))
        assert events[0][0] == "start" and "done" not in [kind for kind, _ in events]
        answer_id = events[0][1]["assistant_message_id"]
        for _ in range(300):
            row = message_row(conn, answer_id)
            if row["status"] != "pending":
                break
            await asyncio.sleep(0.01)
        assert (row["status"], row["error_code"], row["content"]) == ("error", "cancelled", "")
        assert not live_answers()
        assert len(engine.calls) == 1
    finally:
        conn.close()


def test_a_member_session_opens_no_admin_route_and_no_hub_token_opens_the_workspace(client):
    conn = db()
    company = seed_company(conn)
    make_user(conn, role="member", department_ids=[company.dept_a], email="b@acme.test")
    conn.close()
    assert client.get("/api/workspace/admin/users",
                      headers={"X-Admin-Token": "anything"}).status_code == 401
    login(client, "b@acme.test")
    forbidden = client.get("/api/workspace/admin/users")
    assert (forbidden.status_code, forbidden.json()["error"]) == (403, "forbidden")
