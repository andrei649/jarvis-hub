"""G13 / H509 — the owner signs in to a networked Nerva from a browser.

Written from the owner's side (what the owner can do) and the attacker's (what a
guest, another site or a guesser cannot): sign-in with the owner secret, a wrong
secret, the lockout, the cookie's flags, CSRF on cookie writes, sign-out and sign-out
everywhere, the credential rotation that ends sessions, the loopback posture left
unchanged, and a guest token that cannot become the owner. The 2026-11-11 review round
adds: nobody can lock the owner out by failing on purpose (M1), the cookie is no
stronger than the admin header it was exchanged for (m1), cookie use needs positive
browser evidence (m2), plain-HTTP sign-in from the network is refused unless the owner
opts in (m3), malformed cookies never reach the store and lookups are cached (m4), and
the nits (0600 file, polling does not keep a session alive, no __Host- fallback).

The browser stand-in sends ``Sec-Fetch-Site: same-origin`` (what every current browser
sends on the HUD's own fetches) unless a test says otherwise.
"""
import os
import stat
import sys
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import web  # noqa: E402
from agents.core.routers import browser_auth  # noqa: E402
from agents.core.security import browser_session as bs  # noqa: E402
from agents.core.security import token_store as ts  # noqa: E402

OWNER = "owner-secret-" + "x" * 40
GUEST = "guest-token-" + "y" * 40
ORIGIN = "http://testserver"
NET = ("192.168.1.50", 50000)     # a LAN browser
LOOP = ("127.0.0.1", 50000)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Real guards, a private session store and token store, the owner secret set."""
    web.app.dependency_overrides.clear()
    store = ts.TokenStore(str(tmp_path / "tokens.db"))
    monkeypatch.setattr(ts, "_store", store)
    bs.reset_session_store(bs.BrowserSessionStore(str(tmp_path / "sessions.db")))
    monkeypatch.setattr(web, "ADMIN_TOKEN", OWNER)
    monkeypatch.setattr(web, "USER_TOKEN", "")
    monkeypatch.delenv("JARVIS_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("JARVIS_USER_TOKEN", raising=False)
    monkeypatch.delenv("JARVIS_TRUSTED_PROXIES", raising=False)
    monkeypatch.setattr(web, "RATE_LIMIT_PER_MIN", 0)
    # The suite runs over plain-HTTP TestClient origins: opt in to LAN sign-in here and
    # prove the refusal-by-default in its own tests.
    monkeypatch.setenv(bs.INSECURE_SIGNIN_ENV, "1")
    monkeypatch.setattr(bs, "GLOBAL_BACKOFF_SECONDS", 0.0)
    yield store
    bs.reset_session_store(None)
    store.close()


def _probe_app() -> FastAPI:
    """The sign-in router plus four probes behind the hub's real guards."""
    app = FastAPI()
    app.include_router(browser_auth.router)

    @app.get("/probe/user", dependencies=[Depends(web._user_guard)])
    async def user_read(request: Request):
        return {"admin": web._web_principal(request).admin}

    @app.post("/probe/user", dependencies=[Depends(web._user_guard)])
    async def user_write(request: Request):
        return {"admin": web._web_principal(request).admin}

    @app.get("/probe/admin", dependencies=[Depends(web._admin_guard)])
    async def admin_read():
        return {"ok": True}

    @app.post("/probe/admin", dependencies=[Depends(web._admin_guard)])
    async def admin_write():
        return {"ok": True}

    return app


BROWSER = {"Sec-Fetch-Site": "same-origin"}


def _client(app=None, client=NET, base=ORIGIN, headers=BROWSER) -> TestClient:
    return TestClient(app or _probe_app(), base_url=base, client=client, headers=headers)


def _login(c: TestClient, secret: str = OWNER, **headers):
    hdrs = {"Origin": ORIGIN, "Content-Type": "application/json", **headers}
    return c.post("/api/auth/login", json={"secret": secret}, headers=hdrs)


def _set_cookie(resp) -> str:
    return "; ".join(v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie")


# ── sign-in ──────────────────────────────────────────────────────────────────────────

def test_owner_signs_in_and_the_cookie_opens_owner_routes(monkeypatch):
    monkeypatch.setattr(web, "USER_TOKEN", GUEST)     # HF-1: user routes open to the network
    c = _client()
    assert c.get("/probe/admin").status_code == 401        # networked, no credential
    r = _login(c)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["signed_in"] is True and body["csrf"]
    assert c.get("/probe/admin").status_code == 200
    assert c.get("/probe/user").json() == {"admin": True}
    s = c.get("/api/auth/session").json()
    assert s["signed_in"] is True and s["csrf"] == body["csrf"] and s["sign_in_available"] is True


def test_sign_in_through_the_mounted_hub_router():
    """The real app serves the routes (host guard and middleware included)."""
    c = TestClient(web.app, base_url=ORIGIN, client=NET, headers=BROWSER)
    assert c.get("/api/auth/session").json()["signed_in"] is False
    assert _login(c).status_code == 200
    assert c.get("/api/auth/session").json()["signed_in"] is True


def test_wrong_secret_is_refused_and_opens_nothing():
    c = _client()
    r = _login(c, "not-the-secret")
    assert r.status_code == 401 and r.json()["error"] == "invalid_secret"
    assert "set-cookie" not in {k.lower() for k in r.headers}
    assert c.get("/probe/admin").status_code == 401


def test_login_requires_same_origin_and_json():
    c = _client()
    assert _login(c, Origin="https://evil.example").status_code == 403
    assert _login(c, **{"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert _login(c, **{"Sec-Fetch-Site": "same-site"}).status_code == 403
    r = c.post("/api/auth/login", content=f'{{"secret": "{OWNER}"}}',
               headers={"Origin": ORIGIN, "Content-Type": "text/plain"})
    assert r.status_code == 415                             # a cross-site form cannot send JSON
    assert c.get("/probe/admin").status_code == 401


def test_lockout_after_repeated_failures_even_for_the_right_secret():
    c = _client()
    for _ in range(bs.LOGIN_IP_LIMIT):
        assert _login(c, "wrong").status_code == 401
    locked = _login(c)
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    assert c.get("/probe/admin").status_code == 401
    # Another address is not locked by this one, and header tokens still work here.
    assert _login(_client(client=("192.168.1.51", 50000))).status_code == 200
    assert c.get("/probe/admin", headers={"X-Admin-Token": OWNER}).status_code == 200


def test_global_lockout_bounds_a_distributed_guesser(monkeypatch):
    """Past the hub-wide limit every further wrong guess, from any new address, is slowed
    (GLOBAL_BACKOFF_SECONDS) and refused with 429 — it never learns more than "no"."""
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(bs, "GLOBAL_BACKOFF_SECONDS", 2.0)
    monkeypatch.setattr(browser_auth.asyncio, "sleep", fake_sleep)
    for i in range(bs.LOGIN_GLOBAL_LIMIT):
        assert _login(_client(client=(f"10.0.{i // 200}.{i % 200 + 1}", 50000)), "wrong").status_code == 401
    assert slept == []
    late = _login(_client(client=("10.9.9.9", 50000)), "wrong")
    assert late.status_code == 429 and int(late.headers["Retry-After"]) > 0
    assert slept == [2.0]


def test_unauthenticated_peers_cannot_lock_the_owner_out():
    """M1: failures from other addresses never refuse the right secret — from the LAN or
    from the hub's own machine."""
    for i in range(bs.LOGIN_GLOBAL_LIMIT + 5):
        _login(_client(client=(f"10.0.{i // 200}.{i % 200 + 1}", 50000)), "wrong")
    assert _login(_client(client=("192.168.1.77", 50000))).status_code == 200
    assert _login(_client(client=LOOP, base="http://127.0.0.1"),
                  Origin="http://127.0.0.1").status_code == 200


def test_loopback_is_exempt_from_the_sign_in_throttle():
    c = _client(client=LOOP, base="http://127.0.0.1")
    for _ in range(bs.LOGIN_IP_LIMIT + 2):
        assert _login(c, "wrong", Origin="http://127.0.0.1").status_code == 401
    assert _login(c, Origin="http://127.0.0.1").status_code == 200


def test_cookie_flags_over_http():
    r = _login(_client())
    cookie = _set_cookie(r)
    assert cookie.startswith("nerva_session=")
    low = cookie.lower()
    assert "httponly" in low and "samesite=strict" in low and "max-age=" in low and "path=/" in low
    assert "secure" not in low


def test_cookie_flags_over_https_use_the_host_prefix():
    c = _client(base="https://testserver")
    r = c.post("/api/auth/login", json={"secret": OWNER},
               headers={"Origin": "https://testserver"})
    assert r.status_code == 200
    cookie = _set_cookie(r)
    assert cookie.startswith("__Host-nerva_session=")
    low = cookie.lower()
    assert "secure" in low and "httponly" in low and "samesite=strict" in low and "path=/" in low
    assert c.get("/probe/admin").status_code == 200


def test_https_reads_only_the_host_prefixed_cookie():
    """Nit: over HTTPS a plain nerva_session (plantable by a sibling host or an HTTP page)
    is never read."""
    c = _client(base="https://testserver")
    c.post("/api/auth/login", json={"secret": OWNER}, headers={"Origin": "https://testserver"})
    token = c.cookies.get("__Host-nerva_session")
    plain = _client(base="https://testserver")
    plain.cookies.set("nerva_session", token)
    assert plain.get("/probe/admin").status_code == 401


def test_plain_http_sign_in_from_the_network_is_refused_by_default(monkeypatch):
    """m3: over plain HTTP a browser sends the cookie to every port of the host."""
    monkeypatch.delenv(bs.INSECURE_SIGNIN_ENV, raising=False)
    c = _client()
    r = _login(c)
    assert r.status_code == 403 and r.json()["error"] == "https_required"
    s = c.get("/api/auth/session").json()
    assert s["sign_in_available"] is False and s["reason"] == "https_required"
    # Loopback and HTTPS are unaffected.
    assert _login(_client(client=LOOP, base="http://127.0.0.1"),
                  Origin="http://127.0.0.1").status_code == 200
    assert _client(base="https://testserver").post(
        "/api/auth/login", json={"secret": OWNER},
        headers={"Origin": "https://testserver"}).status_code == 200


def test_a_cookie_from_an_allowed_period_stops_counting_when_the_opt_in_is_removed(monkeypatch):
    c = _client()
    _login(c)
    assert c.get("/probe/admin").status_code == 200
    monkeypatch.delenv(bs.INSECURE_SIGNIN_ENV, raising=False)
    assert c.get("/probe/admin").status_code == 401


def test_only_the_hash_of_the_session_is_stored(tmp_path):
    c = _client()
    _login(c)
    token = c.cookies.get("nerva_session")
    raw = (tmp_path / "sessions.db").read_bytes()
    assert token and token.encode() not in raw
    assert bs.token_hash(token).encode() in raw
    if os.name == "posix":                          # nit: owner-only file
        assert stat.S_IMODE((tmp_path / "sessions.db").stat().st_mode) == 0o600


def test_malformed_cookies_never_reach_the_store(monkeypatch):
    """m4: junk cookie values are refused before any database work."""
    calls = []
    store = bs.get_session_store()
    real = store._conn

    class Spy:
        def execute(self, *a, **k):
            calls.append(a[0])
            return real.execute(*a, **k)

        def __getattr__(self, name):
            return getattr(real, name)

    monkeypatch.setattr(store, "_conn", Spy())
    c = _client()
    for junk in ("x", "a" * 300, "' OR 1=1 --", "A" * 42 + "!"):
        c.cookies.set("nerva_session", junk)
        assert c.get("/probe/admin").status_code == 401
    assert calls == []


def test_session_lookups_are_cached_and_sign_out_drops_the_cache(monkeypatch):
    """m4: repeated requests reuse a recent lookup; sign-out takes effect at once."""
    c = _client()
    csrf = _login(c).json()["csrf"]
    store = bs.get_session_store()
    selects = []
    real = store._conn

    class Spy:
        def execute(self, sql, *a, **k):
            if sql.startswith("SELECT * FROM sessions"):
                selects.append(sql)
            return real.execute(sql, *a, **k)

        def __getattr__(self, name):
            return getattr(real, name)

    monkeypatch.setattr(store, "_conn", Spy())
    for _ in range(5):
        assert c.get("/probe/admin").status_code == 200
    assert len(selects) <= 1
    other = _client(client=("192.168.1.90", 50000))
    other.cookies.set("nerva_session", c.cookies.get("nerva_session"))
    assert c.post("/api/auth/logout-all", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}).status_code == 200
    assert other.get("/probe/admin").status_code == 401


def test_polling_does_not_keep_a_session_alive():
    """Nit: only user-initiated requests (writes, the HUD's session read) touch the idle
    clock; a GET poll or a WebSocket loop does not."""
    store = bs.get_session_store()
    opened = store.create(cred_hash=bs.token_hash(OWNER), now=0.0)
    for hour in range(1, 30):
        store.resolve(opened["token"], now=hour * 3600.0)          # polling: touch=False
    assert store.resolve(opened["token"], now=bs.IDLE_SECONDS + 7200.0) is None
    touched = store.create(cred_hash=bs.token_hash(OWNER), now=0.0)
    for hour in range(1, 30):
        store.resolve(touched["token"], now=hour * 3600.0, touch=True)
    assert store.resolve(touched["token"], now=30 * 3600.0) is not None


# ── CSRF ─────────────────────────────────────────────────────────────────────────────

def test_cookie_write_without_csrf_is_refused():
    c = _client()
    csrf = _login(c).json()["csrf"]
    assert c.post("/probe/admin", headers={"Origin": ORIGIN}).status_code == 403
    assert c.post("/probe/admin", headers={"Origin": ORIGIN, "X-CSRF-Token": "forged"}).status_code == 403
    assert c.post("/probe/user", headers={"Origin": ORIGIN}).status_code == 403
    ok = c.post("/probe/admin", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
    assert ok.status_code == 200


def test_cross_origin_cookie_use_is_refused_even_with_the_csrf_token():
    c = _client()
    csrf = _login(c).json()["csrf"]
    assert c.post("/probe/admin", headers={"Origin": "https://evil.example",
                                           "X-CSRF-Token": csrf}).status_code == 401
    assert c.get("/probe/admin", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 401
    assert c.get("/probe/admin", headers={"Sec-Fetch-Site": "same-site"}).status_code == 401
    # The session probe does not hand the CSRF token to another origin.
    leak = c.get("/api/auth/session", headers={"Origin": "https://evil.example"}).json()
    assert leak["signed_in"] is False and "csrf" not in leak


def test_no_browser_evidence_is_not_cookie_authentication():
    """m2 (was FACT_no_browser_evidence_counts_as_same_origin_and_returns_csrf): a
    replayed cookie with neither Origin nor Sec-Fetch-Site opens nothing and gets no CSRF
    token; nor does a typed-URL navigation (Sec-Fetch-Site: none) to an API."""
    c = _client()
    csrf = _login(c).json()["csrf"]
    raw = _client(headers={})
    raw.cookies.set("nerva_session", c.cookies.get("nerva_session"))
    s = raw.get("/api/auth/session").json()
    assert s["signed_in"] is False and "csrf" not in s
    assert raw.get("/probe/admin").status_code == 401
    assert raw.post("/probe/admin", headers={"X-CSRF-Token": csrf}).status_code == 401
    typed = _client(headers={"Sec-Fetch-Site": "none"})
    typed.cookies.set("nerva_session", c.cookies.get("nerva_session"))
    assert typed.get("/probe/admin").status_code == 401
    # A browser without Sec-Fetch-Site that sends a matching Origin is evidence.
    old = _client(headers={"Origin": ORIGIN})
    old.cookies.set("nerva_session", c.cookies.get("nerva_session"))
    assert old.get("/probe/admin").status_code == 200


def test_header_token_routes_do_not_become_cookie_driven():
    """A request that presents a header credential is judged on it alone: a wrong
    header with a valid owner cookie is still refused (no CSRF-free cookie path), and
    a right header needs no CSRF token (browsers cannot forge a custom header)."""
    c = _client()
    _login(c)
    assert c.post("/probe/admin", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert c.post("/probe/admin", headers={"X-Admin-Token": OWNER}).status_code == 200


# ── revocation ───────────────────────────────────────────────────────────────────────

def test_sign_out_revokes_the_session_server_side():
    c = _client()
    _login(c)
    token = c.cookies.get("nerva_session")
    r = c.post("/api/auth/logout", headers={"Origin": ORIGIN})
    assert r.status_code == 200 and r.json()["revoked"] is True
    assert "nerva_session=" in _set_cookie(r) and "max-age=0" in _set_cookie(r).lower()
    # Replaying the old cookie after sign-out opens nothing.
    replay = _client()
    replay.cookies.set("nerva_session", token)
    assert replay.get("/probe/admin").status_code == 401


def test_sign_out_refuses_another_origin():
    c = _client()
    _login(c)
    assert c.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.get("/probe/admin").status_code == 200


def test_sign_out_everywhere_ends_every_session():
    a, b = _client(), _client(client=("192.168.1.60", 50000))
    csrf = _login(a).json()["csrf"]
    _login(b)
    assert a.post("/api/auth/logout-all", headers={"Origin": ORIGIN}).status_code == 403
    r = a.post("/api/auth/logout-all", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["revoked"] == 2
    assert a.get("/probe/admin").status_code == 401
    assert b.get("/probe/admin").status_code == 401


def test_sign_out_everywhere_needs_the_owner():
    c = _client()
    assert c.post("/api/auth/logout-all", headers={"Origin": ORIGIN}).status_code == 401


def test_rotating_the_admin_credential_ends_sessions_opened_with_it(_isolated):
    managed = _isolated.issue("admin")
    c = _client()
    assert _login(c, managed).status_code == 200
    assert c.get("/probe/admin").status_code == 200
    _isolated.rotate("admin")             # also supersedes the env bootstrap token
    assert c.get("/probe/admin").status_code == 401
    assert _login(_client(client=("192.168.1.70", 50000))).status_code == 401


def test_a_new_sign_in_rotates_the_session():
    c = _client()
    _login(c)
    first = c.cookies.get("nerva_session")
    _login(c)
    assert c.cookies.get("nerva_session") != first
    stale = _client()
    stale.cookies.set("nerva_session", first)
    assert stale.get("/probe/admin").status_code == 401


def test_idle_and_absolute_expiry():
    store = bs.get_session_store()
    opened = store.create(cred_hash=bs.token_hash(OWNER), now=1000.0)
    assert store.resolve(opened["token"], now=1000.0 + bs.IDLE_SECONDS - 1) is not None
    assert store.resolve(opened["token"], now=1000.0 + 2 * bs.IDLE_SECONDS) is None
    kept = store.create(cred_hash=bs.token_hash(OWNER), now=0.0)
    for step in range(1, 8):              # touched every day, still dies at 7 days
        store.resolve(kept["token"], now=step * 86400.0 - 10, touch=True)
    assert store.resolve(kept["token"], now=bs.ABSOLUTE_SECONDS + 1) is None


# ── loopback unchanged; guests cannot escalate ───────────────────────────────────────

def test_loopback_posture_is_unchanged(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    c = _client(client=LOOP, base="http://127.0.0.1")
    assert c.get("/probe/admin").status_code == 200        # fresh box: loopback is the owner
    assert c.post("/probe/user").json() == {"admin": True}  # no CSRF needed, as before
    r = c.post("/api/auth/login", json={"secret": "anything"},
               headers={"Origin": "http://127.0.0.1"})
    assert r.status_code == 409 and r.json()["error"] == "no_owner_credential"
    assert c.get("/api/auth/session").json() == {"signed_in": False, "sign_in_available": False}
    # A networked caller on the same box configuration is still refused.
    assert _client().get("/probe/admin").status_code == 403


def test_cookie_is_no_stronger_than_the_admin_header(monkeypatch):
    """m1 (was FACT_cookie_opens_network_user_routes_that_the_admin_header_cannot): with
    no user token configured, HF-1 keeps user routes network-disabled for the admin
    header — and for the cookie it was exchanged for. Admin routes open for both."""
    c = _client()
    assert c.get("/probe/user", headers={"X-Admin-Token": OWNER}).status_code == 403
    assert _login(c).status_code == 200
    assert c.get("/probe/user").status_code == 403
    assert c.get("/probe/admin").status_code == 200
    monkeypatch.setattr(web, "USER_TOKEN", GUEST)
    assert c.get("/probe/user", headers={"X-Admin-Token": OWNER}).status_code == 200
    assert c.get("/probe/user").status_code == 200


def test_guest_token_cannot_sign_in_or_escalate(monkeypatch):
    monkeypatch.setattr(web, "USER_TOKEN", GUEST)
    guest = _client(client=("192.168.1.80", 50000))
    assert guest.get("/probe/user", headers={"X-User-Token": GUEST}).json() == {"admin": False}
    r = _login(guest, GUEST)
    assert r.status_code == 401
    assert guest.get("/probe/admin", headers={"X-User-Token": GUEST}).status_code == 401
    # In the owner's browser, a guest header is judged alone — the owner cookie does
    # not lift it to owner.
    owner = _client()
    _login(owner)
    assert owner.get("/probe/user", headers={"X-User-Token": GUEST}).json() == {"admin": False}
    assert owner.get("/probe/user").json() == {"admin": True}


def test_session_exempts_the_owner_from_the_unauthenticated_rate_limit():
    c = _client()
    _login(c)
    # The rate limiter's predicate: a live owner session counts as authenticated.
    from starlette.requests import Request as StarletteRequest
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [
        (b"cookie", f"nerva_session={c.cookies.get('nerva_session')}".encode()),
        (b"sec-fetch-site", b"same-origin"),
        (b"host", b"testserver")], "client": NET, "server": ("testserver", 80),
        "scheme": "http", "query_string": b"", "root_path": ""}
    assert web._request_is_authed(StarletteRequest(scope)) is True
    scope["headers"] = [(b"host", b"testserver")]
    assert web._request_is_authed(StarletteRequest(scope)) is False
