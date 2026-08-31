"""DRA-50 / docs/AUDIT.md A5+Q2 — the `require_component` guard sweep.

AUDIT A5 asked for one shared helper so the `getattr(orch, "X", None) → 503`
preamble stops being copy-pasted into every new router (§7 parked it as
"Deferred to post-manual-testing"; by the time it was picked up the boilerplate
had roughly tripled). This file is the contract for that sweep:

* the helper exists and resolves a component with **exactly** the semantics the
  hand-written preamble had (including the `if orch else None` short-circuit);
* no router re-inlines the preamble — with one explicit, named allowlist of
  sites deliberately left alone because their behaviour genuinely differs;
* the sweep is behaviour-exact: the same status, the same body, the same
  response class, and the same *ordering* relative to request-body validation.

That last point is why `require_component` is a request-time helper and not a
`Depends(...)`. FastAPI solves dependencies **before** it validates the request
body, so a `Depends`-based guard turns today's 422-on-a-malformed-body into a
503 whenever the component happens to be down. `test_body_validation_still_wins_over_the_guard`
pins that ordering so nobody "upgrades" the helper into a dependency and
silently changes 4xx behaviour across ~45 endpoints.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

ROUTERS = repo_root / "agents" / "core" / "routers"

# Component-guard sites deliberately NOT migrated, and why. Each one differs
# from the shared shape in a way the helper cannot reproduce, so normalising it
# would be a behaviour change dressed up as a refactor.
#
#   analytics.*  — the 503 goes out through `nocache_json` (Cache-Control /
#                  Pragma headers) AND each handler distinguishes "orch is not
#                  up yet" ({"error": "not initialized"}) from "the component is
#                  missing" ({"error": "tracer not available"}). One
#                  `require_component` call collapses both into the second body.
#   oauth.*      — guards on truthiness (`if not bridge`), not `is None`, and
#                  answers with a different body shape ({"ok": False, "error": …}).
DELIBERATELY_UNCONVERTED = {
    ("analytics.py", "metrics_north_star"),
    ("analytics.py", "get_trace"),
    ("analytics.py", "clear_traces"),
    ("oauth.py", "oracle_status"),
    ("oauth.py", "oracle_sync"),
    ("oauth.py", "oracle_conflicts"),
    ("oauth.py", "oracle_resolve_conflicts"),
}

# Sites where the guard itself stays hand-written (it tests two components, or
# it sits mid-handler rather than in the preamble) but the 503 *body* is minted
# by the shared factory, so the response shape is still defined in one place.
SHARED_FACTORY_ONLY = {
    ("security.py", "capabilities_check"),
    ("skills.py", "sandbox_execute"),
}


def _inline_component_guards() -> set[tuple[str, str]]:
    """Every handler that still hand-rolls `getattr(orch, …) is None → 503`."""
    found: set[tuple[str, str]] = set()
    for path in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            comps: set[str] = set()
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)):
                    continue
                value = node.value
                value = value.body if isinstance(value, ast.IfExp) else value
                if (isinstance(value, ast.Call)
                        and getattr(value.func, "id", "") == "getattr"
                        and len(value.args) == 3
                        and getattr(value.args[0], "id", "") == "orch"
                        and isinstance(value.args[1], ast.Constant)):
                    comps.add(node.targets[0].id)
            if not comps:
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.If):
                    continue
                names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
                if not (names & comps):
                    continue
                for stmt in node.body:
                    if not (isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call)):
                        continue
                    kw = {k.arg: k.value for k in stmt.value.keywords}
                    code = kw.get("status_code")
                    if isinstance(code, ast.Constant) and code.value == 503:
                        found.add((path.name, fn.name))
    return found


# ── 1. the helper's contract ──────────────────────────────────────────────────

def test_require_component_helper_exists():
    """RED before DRA-50: `agents.core.routers._component` does not exist."""
    from agents.core.routers._component import component_unavailable, require_component

    assert callable(require_component)
    assert callable(component_unavailable)


def test_component_unavailable_is_the_exact_503_the_routers_returned():
    from agents.core.routers._component import component_unavailable

    resp = component_unavailable("arena not available")
    assert resp.status_code == 503
    assert resp.body == b'{"error":"arena not available"}'
    # Plain JSONResponse: the migrated sites never sent cache headers on the 503.
    assert "cache-control" not in {k.lower() for k in resp.headers}


def test_require_component_resolves_and_refuses_like_the_old_preamble(monkeypatch):
    import agents.web as web
    from agents.core.routers._component import require_component

    # 1. no orchestrator at all → 503, no component.
    monkeypatch.setattr(web, "orch", None)
    orch, value, err = require_component("arena", "arena not available")
    assert (orch, value) == (None, None)
    assert err is not None and err.status_code == 503

    # 2. orchestrator up, component absent → 503, and `orch` still handed back
    #    (7 of the migrated handlers keep using it after the guard).
    stub = SimpleNamespace()
    monkeypatch.setattr(web, "orch", stub)
    orch, value, err = require_component("arena", "arena not available")
    assert orch is stub and value is None
    assert err is not None and err.status_code == 503
    assert err.body == b'{"error":"arena not available"}'

    # 3. component present → passthrough, no error.
    sentinel = object()
    monkeypatch.setattr(web, "orch", SimpleNamespace(arena=sentinel))
    orch, value, err = require_component("arena", "arena not available")
    assert value is sentinel and err is None


def test_require_component_keeps_the_falsy_orch_short_circuit(monkeypatch):
    """The old line was `getattr(orch, "x", None) if orch else None`.

    A falsy-but-present orchestrator therefore refused even when the attribute
    existed. `notes_rewrite` / `rooms_message` encoded that twice (`x is None or
    not orch`); the helper has to keep it, or those two change behaviour.
    """
    import agents.web as web
    from agents.core.routers._component import require_component

    class _Falsy:
        arena = object()

        def __bool__(self):
            return False

    monkeypatch.setattr(web, "orch", _Falsy())
    _, value, err = require_component("arena", "arena not available")
    assert value is None
    assert err is not None and err.status_code == 503


# ── 2. the sweep itself ───────────────────────────────────────────────────────

def test_no_router_reinlines_the_component_503_preamble():
    """RED before DRA-50: 40+ handlers hand-roll this guard."""
    leftover = _inline_component_guards() - DELIBERATELY_UNCONVERTED
    assert leftover == set(), (
        "these handlers still hand-roll the getattr(orch,…)→503 preamble; use "
        f"agents.core.routers._component.require_component instead: {sorted(leftover)}"
    )


def test_the_unconverted_allowlist_is_not_stale():
    """Every excused site must still exist, so the residual cannot rot silently."""
    still_there = _inline_component_guards()
    assert still_there >= DELIBERATELY_UNCONVERTED, (
        "allowlist names a site that no longer hand-rolls the guard: "
        f"{sorted(DELIBERATELY_UNCONVERTED - still_there)}"
    )


def test_shared_factory_sites_use_the_shared_factory():
    for filename, func in SHARED_FACTORY_ONLY:
        src = (ROUTERS / filename).read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func)
        calls = {getattr(n.func, "id", "") for n in ast.walk(fn) if isinstance(n, ast.Call)}
        assert "component_unavailable" in calls, f"{filename}:{func}"


def test_the_sweep_actually_reached_the_routers():
    """`require_component` is used broadly, not wired into one token call site."""
    users = {p.name for p in sorted(ROUTERS.glob("*.py"))
             if "require_component" in p.read_text(encoding="utf-8")}
    users.discard("_component.py")
    assert len(users) >= 10, sorted(users)


# ── 3. behaviour pins (green before AND after — this is the regression net) ───

@pytest.fixture()
def client(monkeypatch):
    import agents.web as web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "dra50-secret")
    with TestClient(web.app) as c:
        real_orch = web.orch
        try:
            yield c
        finally:
            # Restore before the lifespan shutdown runs: `monkeypatch` unwinds
            # after this fixture, and TestClient.__exit__ calls orch.stop_channels().
            web.orch = real_orch


ADMIN = {"X-Admin-Token": "dra50-secret"}

# One representative route per migrated router family: (method, path, body, headers, message).
CASES = [
    ("POST", "/api/actions/request", {}, ADMIN, "action approvals not available"),
    ("POST", "/api/arena/run", {}, ADMIN, "arena not available"),
    ("POST", "/api/memory/consolidate", {}, ADMIN, "consolidation not available"),
    ("POST", "/api/sync/push", {}, ADMIN, "e2e sync unavailable"),
    ("PUT", "/api/notes", {"content": "x"}, ADMIN, "notes not available"),
    ("GET", "/api/presence/owner", None, ADMIN, "presence not available"),
    ("POST", "/api/rooms", {"name": "r"}, ADMIN, "rooms not available"),
    ("GET", "/api/security/kill-switch", None, ADMIN, "kill-switch not available"),
]


@pytest.mark.parametrize("method,path,body,headers,message", CASES)
def test_missing_component_still_answers_503_with_the_same_body(
        client, monkeypatch, method, path, body, headers, message):
    import agents.web as web

    monkeypatch.setattr(web, "orch", SimpleNamespace())
    resp = client.request(method, path, json=body, headers=headers)
    assert resp.status_code == 503, (path, resp.status_code, resp.text)
    assert resp.json() == {"error": message}


def test_a_present_component_is_passed_through(client, monkeypatch):
    """The guard must not swallow the happy path."""
    import agents.web as web

    class _Presence:
        def snapshot(self):
            return SimpleNamespace(to_dict=lambda: {"state": "present"})

    monkeypatch.setattr(web, "orch", SimpleNamespace(owner_presence=_Presence()))
    resp = client.get("/api/presence/owner", headers=ADMIN)
    assert resp.status_code == 200
    assert resp.json()["state"] == "present"


def test_orch_is_still_available_after_the_guard(client, monkeypatch):
    """`notes_set` reads `orch.session_id` *after* the guard — the helper must
    hand the orchestrator back, not just the component."""
    import agents.web as web

    class _Notes:
        def set(self, sid, content):
            return {"chars": len(content)}

    monkeypatch.setattr(
        web, "orch", SimpleNamespace(notes=_Notes(), session_id="sess-dra50"))
    resp = client.put("/api/notes", json={"content": "hello"}, headers=ADMIN)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "session": "sess-dra50", "chars": 5}


def test_body_validation_still_wins_over_the_guard(client, monkeypatch):
    """A malformed body is a 422 even while the component is down.

    This is exactly what a `Depends(require_component(...))` would break:
    FastAPI resolves dependencies before `request_body_to_args`, so the guard
    would answer 503 and the client would never learn its payload was invalid.
    """
    import agents.web as web

    monkeypatch.setattr(web, "orch", SimpleNamespace())
    resp = client.post("/api/presence/owner", json={"state": ""}, headers=ADMIN)
    assert resp.status_code == 422, resp.text
