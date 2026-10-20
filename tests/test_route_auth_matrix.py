"""SEC-2 — route-auth matrix gate (F-03 from docs/SECURITY_ROUTE_AUDIT_2026-06-17.md).

A green test suite must not be able to hide a newly-unguarded state-changing
endpoint. This reads each route's *resolved dependency graph* from the live app
(ground truth, not AST) and:

1. pins every route's guard against tests/_snapshots/route_auth.json — any new,
   removed, or drifted guard fails CI until the snapshot is consciously updated;
2. fails if any OPEN *mutating* route isn't explicitly classified as either
   INTENTIONALLY_OPEN (self-authenticating / public by design) or PENDING_GUARD
   (SEC-3 backlog);
3. keeps PENDING_GUARD honest — it may only list routes that are still open;
4. (H511) enumerates every WebSocket upgrade route too and pins each one to a
   dependency guard or a WS_GUARDED_IN_HANDLER entry, and splits the open
   allowlists into IN_HANDLER_GUARDED (a credential checked in the handler body,
   proved route by route in tests/test_route_inhandler_guards.py) and
   PUBLIC_BY_DESIGN (no credential exists to check).

The autouse user-guard override in conftest is irrelevant here: dependency
overrides apply at request time and do not change route.dependant, which is what
we introspect.
"""
import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

SNAPSHOT = repo_root / "tests" / "_snapshots" / "route_auth.json"
MUTATING = {"POST", "PUT", "DELETE", "PATCH"}

# Mutating routes that are open *by design* — each authenticates itself or is a
# public ingress that mints nothing. Verified in the 2026-06-17 audit.
INTENTIONALLY_OPEN = {
    "POST /api/webhooks/{hook_id}",        # per-webhook token or HMAC over the body
    "POST /api/a2a/task",                   # peer HMAC signature; off unless a2a enabled
    "POST /api/mcp/server/rpc",             # disabled by default; optional OAuth bearer
    "POST /api/oauth/callback",             # provider redirect; verify_state() gates it
    "POST /api/widget/{token}/message",     # widget capability token in the path
    "POST /api/channels/pairing/request",   # inbound pairing; lands in approval, mints nothing
    "POST /api/analytics/event",            # H22 public privacy-first beacon; bounded INSERT, mints nothing
}

# Open mutating routes still awaiting a guard — SEC-3 backlog. Listed explicitly
# so the debt is bounded and visible; this set shrinks (never grows) as SEC-3
# lands guards and the snapshot flips those routes to user/admin.
PENDING_GUARD = set()  # SEC-3 COMPLETE — every open mutator is now guarded or in INTENTIONALLY_OPEN.

# ── SEC-B6: the read half of the matrix ──────────────────────────────────────
# The 2026-07-25 audit's theme B: mutators had a forcing function (above) while
# reads had none, so a personal-content GET could ship open silently. From here
# on every OPEN GET must be classified by the *substance of its handler* (what
# the response body contains), never by its URL shape:
#   INTENTIONALLY_OPEN_READS — PUBLIC_READS (verified to expose no personal
#                              content) | the in-handler-credentialed GETs (H511);
#   PENDING_READ_GUARD       — touches personal data, guard still owed (debt,
#                              shrink-only, same contract as PENDING_GUARD).
PUBLIC_READS = {
    # App shell + static assets (serve markup/bytes, never user data).
    "GET /",
    "GET /v1",
    "GET /v2",
    "GET /v2/{path:path}",
    "GET /admin",            # page shell only; every admin API behind it is admin-guarded
    "GET /favicon.ico",
    "GET /sw.js",
    # FastAPI scaffolding (route schema, no stored data).
    "GET /docs",
    "GET /docs/oauth2-redirect",
    "GET /redoc",
    "GET /openapi.json",
    # Public protocol surfaces / self-authenticating token in the path.
    "GET /.well-known/agent-card",
    "GET /.well-known/oauth-protected-resource",
    "GET /api/mcp/server",               # status of a disabled-by-default surface
    # Liveness / ops meters (aggregate counters, degradation flags).
    "GET /healthz",
    "GET /readyz",
    "GET /metrics",
    "GET /api/resilience",
    "GET /api/health/components",
    "GET /api/status",
    "GET /status",
    "GET /api/local-docs",
    # Catalogs shipped in code (templates, specs, synthetic fixtures).
    "GET /api/agent-templates",
    "GET /api/design-manifest",          # HUD design tokens parsed from the shipped stylesheet
    # T-0.29 PWA: the browser fetches both WITHOUT app auth headers (an install
    # prompt and a service-worker registration are unauthenticated by spec), and
    # neither carries user data — the manifest is static branding, the worker is
    # static code that itself refuses to cache any /api/ response.
    "GET /manifest.webmanifest",
    "GET /v2/manifest.webmanifest",
    "GET /sw-v2.js",
    "GET /v2/sw-v2.js",

    "GET /api/memory/tool-spec",
    "GET /api/memory/eval/corpus",       # owned synthetic corpus, not user memory
    "GET /api/voice/capabilities",
    "GET /api/voice/wyoming",
    "GET /skills/imported",
    "GET /sandbox/status",
    "GET /plugins",                      # config presence booleans, never key values
    "GET /agents",                       # roster + aggregate stats + skill names
    # Aggregate observability (counts/rates/percentiles — no message content).
    "GET /api/analytics/cost",
    "GET /api/analytics/locality",
    "GET /api/analytics/model-tiers",
    "GET /api/metrics/capabilities",
    "GET /api/metrics/kernel",
    "GET /api/metrics/north-star",
    "GET /api/quality",                  # rolling average + alert flag; scores are guarded
    "GET /api/review/stats",
    "GET /learning/stats",
    "GET /bench",
    "GET /bench/stats",
    "GET /memory/stats",
    "GET /heartbeat/status",
    "GET /api/arena/leaderboard",        # scores only; match bodies are guarded
    "GET /api/eval/datasets",
    "GET /api/eval/datasets/{name}/runs",
    "GET /api/eval/datasets/{name}/compare",
    "GET /api/autonomy/escalation/targets",
    # Deliberate transparency: the trust surface is readable by design (H18.18
    # reads it from mobile without tokens; writes stay admin-guarded).
    "GET /api/security/capabilities/check",
    "GET /api/security/governance",
    "GET /api/security/kill-switch",
    "GET /api/security/loop-breaker",
    "GET /api/trust/status",
    "GET /security",
    "GET /security/status",
    # OAuth connect flow (pre-auth by nature: presence booleans + public URLs).
    "GET /api/oauth/status",
    "GET /api/oauth/auth-url",
    "GET /api/oauth/callback",   # provider redirect; verify_state() gates the exchange, page shows only the service name
    "GET /api/oracle/status",
    # WorldView liveness booleans; the overview (recon/alerts) is guarded.
    "GET /api/worldview/status",
}
# (The widget capability-token reads are open too, but their handler checks a
# credential, so they are listed in IN_HANDLER_GUARDED below and folded in there.)

# Personal-data reads still open — SEC-B6 debt. Shrink-only.
PENDING_READ_GUARD = set()  # SEC-B6 COMPLETE — every personal-content read now carries user_guard.


# ── H511: credentials checked in the handler body ────────────────────────────
# The dependant graph cannot see a check made inside a handler, so these routes
# classify as "open". Each entry names the credential the handler demands, and
# tests/test_route_inhandler_guards.py holds one probe per entry that calls the
# route without it (asserting the refusal) and with it (asserting the refusal
# came from that check) — a listed-but-unproved entry fails there.
IN_HANDLER_GUARDED = {
    "POST /api/webhooks/{hook_id}": "x-webhook-token, or HMAC x-signature-256 for a signed hook",
    "POST /api/a2a/task": "allowlisted peer's HMAC x-signature-256",
    "POST /api/mcp/server/rpc": "OAuth bearer, or the HF-1 user/admin token posture",
    "POST /api/oauth/callback": "a state minted by this hub (verify_state)",
    "POST /api/widget/{token}/message": "widget capability token in the path",
    "GET /api/widget/{token}": "widget capability token in the path",
    "GET /api/widget/{token}/config": "widget capability token in the path",
}

# H511 review: the read half is partitioned exactly like the mutators — an open GET
# is either public by design (PUBLIC_READS) or credentialed in its handler (and then
# proved by a probe); there is no third, say-so-only bucket.
INTENTIONALLY_OPEN_READS = PUBLIC_READS | {k for k in IN_HANDLER_GUARDED if k.startswith("GET ")}

# Open mutators with no credential to check — public ingress by design.
PUBLIC_BY_DESIGN = {
    "POST /api/channels/pairing/request",   # lands in owner approval, mints nothing
    "POST /api/analytics/event",            # bounded anonymous beacon
}

# WebSocket upgrades whose guard runs in the handler body (an upgrade has no
# Request for a dependency to receive, so both build one and call admin_guard
# before accept()). Value = the tier the in-handler check enforces; each is
# connected to unauthenticated by tests/test_route_inhandler_guards.py.
WS_GUARDED_IN_HANDLER = {
    "WS /api/kanban/events": "admin",
    "WS /api/hermes/ws": "admin",
}

# H511 review: a step-up — a route the dependant graph classifies as "user" whose
# handler demands the admin credential for part of its input. The matrix records
# these as "user"; each is proved by a probe in test_route_inhandler_guards.py
# (user-tier caller refused, owner admitted).
IN_HANDLER_STEP_UP = {
    "POST /api/vlm/composer/prepare": "admin when selected_turn=true",
    "POST /api/vlm/composer/describe-prepared": "admin when selected_turn=true",
    "POST /api/vlm/composer/chat-prepared": "admin when selected_turn=true",
}

# H511 review: every function in agents/ that *calls* a guard in its body (not as a
# Depends) — found by an AST scan, pinned here, and mapped to the routes whose
# in-handler or step-up check it is. A new in-body guard call fails CI until it is
# mapped to an entry that has a probe.
IN_HANDLER_GUARD_SITES = {
    "agents/core/routers/kanban.py:events": ("WS /api/kanban/events",),
    "agents/core/routers/hermes_runtime.py:websocket_rpc": ("WS /api/hermes/ws",),
    "agents/core/routers/hermes_runtime.py:_send_events": ("WS /api/hermes/ws",),
    "agents/core/routers/composer_vision.py:_selected_owner_scope": tuple(sorted(IN_HANDLER_STEP_UP)),
}
_GUARD_CALLS = {"admin_guard", "user_guard", "_admin_guard", "_user_guard"}

# H511 review: mounted ASGI sub-apps. A mount with a route table is descended into
# by iter_websocket_routes; one without (StaticFiles, an opaque ASGI app) cannot be
# introspected, so it must be listed here by type. StaticFiles serves GET/HEAD
# bytes only and refuses WebSocket scopes.
ALLOWED_MOUNTS = {
    "/static": "StaticFiles",
    "/v2/assets": "StaticFiles",
}

WS_SNAPSHOT = repo_root / "tests" / "_snapshots" / "ws_route_auth.json"


def _guard_of(dep) -> str:
    """Classify a resolved dependant graph as "open|user|admin"."""
    names = set()
    if dep:
        stack = list(getattr(dep, "dependencies", []))
        while stack:
            d = stack.pop()
            call = getattr(d, "call", None)
            if call is not None:
                names.add(getattr(call, "__name__", ""))
            stack.extend(getattr(d, "dependencies", []))
    if {"_admin_guard", "admin_guard"} & names:
        return "admin"
    if {"_user_guard", "user_guard"} & names:
        return "user"
    return "open"


def _ws_guards(app=None):
    """Map "WS /path" -> "open|user|admin" for every WebSocket route (H511)."""
    from tests._route_introspect import iter_websocket_routes

    if app is None:
        from agents.web import app
    return {f"WS {r.path}": _guard_of(getattr(r, "dependant", None)) for r in iter_websocket_routes(app)}


def _runtime_guards():
    """Map "METHOD /path" -> "open|user|admin" from the live app's dependant graph."""
    from agents.web import app
    from tests._route_introspect import iter_effective_routes

    out = {}
    # iter_effective_routes flattens fastapi 0.137 _IncludedRouter wrappers and
    # exposes each route's *merged* dependant (include-time guards folded in), so
    # routers mounted with `dependencies=[Depends(_user_guard)]` classify correctly.
    for r in iter_effective_routes(app):
        if not getattr(r, "methods", None):
            continue
        guard = _guard_of(getattr(r, "dependant", None))
        for meth in sorted((r.methods or set()) - {"HEAD", "OPTIONS"}):
            out[f"{meth} {r.path}"] = guard
    return out


def test_route_guards_match_snapshot():
    runtime = _runtime_guards()
    snap = json.loads(SNAPSHOT.read_text())
    new = sorted(set(runtime) - set(snap))
    gone = sorted(set(snap) - set(runtime))
    drift = sorted(k for k in runtime if k in snap and runtime[k] != snap[k])
    problems = []
    if new:
        problems.append(f"NEW routes (classify + add to snapshot): {new}")
    if gone:
        problems.append(f"REMOVED routes (drop from snapshot): {gone}")
    if drift:
        problems.append("GUARD DRIFT: " + ", ".join(f"{k}: {snap[k]}->{runtime[k]}" for k in drift))
    assert not problems, (
        "Route auth changed. If intended, regenerate tests/_snapshots/route_auth.json and "
        "update INTENTIONALLY_OPEN / PENDING_GUARD.\n" + "\n".join(problems)
    )


def test_no_unclassified_open_mutator():
    runtime = _runtime_guards()
    open_mut = {k for k, g in runtime.items() if g == "open" and k.split()[0] in MUTATING}
    unclassified = sorted(open_mut - INTENTIONALLY_OPEN - PENDING_GUARD)
    assert not unclassified, (
        "OPEN mutating route(s) with no classification. Add a guard, or list under "
        "INTENTIONALLY_OPEN (with a reason) / PENDING_GUARD:\n" + "\n".join(unclassified)
    )


def test_pending_guard_is_honest():
    runtime = _runtime_guards()
    stale = sorted(k for k in PENDING_GUARD if runtime.get(k) != "open")
    assert not stale, (
        "PENDING_GUARD lists routes that are no longer open (guarded or removed) — "
        "remove them from the set:\n" + "\n".join(stale)
    )


def test_no_unclassified_open_read():
    """SEC-B6: an open GET is a decision, not a default — classify it or guard it."""
    runtime = _runtime_guards()
    open_reads = {k for k, g in runtime.items() if g == "open" and k.startswith("GET ")}
    unclassified = sorted(open_reads - INTENTIONALLY_OPEN_READS - PENDING_READ_GUARD)
    assert not unclassified, (
        "OPEN read route(s) with no classification. Add user_guard, or list under "
        "INTENTIONALLY_OPEN_READS (with the substance-of-handler reason) / "
        "PENDING_READ_GUARD:\n" + "\n".join(unclassified)
    )


def test_read_classifications_are_honest():
    """SEC-B6: both read sets may only name routes that are actually open GETs —
    a guarded or removed entry is stale and must be dropped, so the debt list
    can only shrink and the allowlist can't mask a later guard."""
    runtime = _runtime_guards()
    stale_pending = sorted(k for k in PENDING_READ_GUARD if runtime.get(k) != "open")
    stale_allow = sorted(k for k in INTENTIONALLY_OPEN_READS if runtime.get(k) != "open")
    problems = []
    if stale_pending:
        problems.append("PENDING_READ_GUARD lists non-open routes: " + ", ".join(stale_pending))
    if stale_allow:
        problems.append("INTENTIONALLY_OPEN_READS lists non-open routes: " + ", ".join(stale_allow))
    assert not problems, "\n".join(problems)


def test_every_websocket_route_is_pinned():
    """H511: an upgrade route is a route — a new one, guarded or not, fails until classified."""
    ws = _ws_guards()
    assert ws, "no WebSocket routes enumerated — the introspection lost them"
    unclassified = sorted(k for k, g in ws.items() if g == "open" and k not in WS_GUARDED_IN_HANDLER)
    stale = sorted(k for k in WS_GUARDED_IN_HANDLER if ws.get(k) != "open")
    problems = []
    if unclassified:
        problems.append("OPEN WebSocket route(s) with no classification — add a guard, or list under "
                        "WS_GUARDED_IN_HANDLER and prove it in test_route_inhandler_guards.py: "
                        + ", ".join(unclassified))
    if stale:
        problems.append("WS_GUARDED_IN_HANDLER lists routes that are gone or now dependency-guarded: "
                        + ", ".join(stale))
    assert not problems, "\n".join(problems)


def test_websocket_classifier_sees_included_and_guarded_upgrades():
    """The enumeration itself: an included router's upgrade route is found under its
    real prefix, a dependency guard is read, and an unguarded one reads "open"."""
    from fastapi import APIRouter, Depends, FastAPI, WebSocket

    async def admin_guard():
        return None

    router = APIRouter(prefix="/x")

    @router.websocket("/open")
    async def _open(ws: WebSocket):
        await ws.close()

    @router.websocket("/guarded", dependencies=[Depends(admin_guard)])
    async def _guarded(ws: WebSocket):
        await ws.close()

    app = FastAPI()
    app.include_router(router)

    @app.websocket("/top")
    async def _top(ws: WebSocket):
        await ws.close()

    assert _ws_guards(app) == {"WS /x/open": "open", "WS /x/guarded": "admin", "WS /top": "open"}


def test_open_allowlists_split_into_in_handler_and_public():
    """H511: every open mutator is either credentialed in its handler (and proved) or
    public by design; nothing sits in INTENTIONALLY_OPEN on say-so alone."""
    runtime = _runtime_guards()
    mutators = {k for k in IN_HANDLER_GUARDED if k.split()[0] in MUTATING}
    problems = []
    if mutators | PUBLIC_BY_DESIGN != INTENTIONALLY_OPEN:
        problems.append("INTENTIONALLY_OPEN must equal IN_HANDLER_GUARDED mutators | PUBLIC_BY_DESIGN; "
                        f"diff: {sorted(INTENTIONALLY_OPEN ^ (mutators | PUBLIC_BY_DESIGN))}")
    if mutators & PUBLIC_BY_DESIGN:
        problems.append(f"both in-handler and public: {sorted(mutators & PUBLIC_BY_DESIGN)}")
    reads = {k for k in IN_HANDLER_GUARDED if k.startswith("GET ")}
    if reads & PUBLIC_READS:
        problems.append(f"both in-handler and public: {sorted(reads & PUBLIC_READS)}")
    if PUBLIC_READS | reads != INTENTIONALLY_OPEN_READS:
        problems.append("INTENTIONALLY_OPEN_READS must equal IN_HANDLER_GUARDED reads | PUBLIC_READS")
    not_open = sorted(k for k in IN_HANDLER_GUARDED if runtime.get(k) != "open")
    if not_open:
        problems.append(f"IN_HANDLER_GUARDED lists routes that are gone or dependency-guarded: {not_open}")
    assert not problems, "\n".join(problems)


def test_websocket_guards_match_snapshot():
    """H511 review: WebSocket tiers are pinned exactly like HTTP guards — a new
    upgrade route, a removed one, or a tier change (admin -> user, a dependency
    guard dropped) fails until tests/_snapshots/ws_route_auth.json is updated."""
    runtime = _ws_guards()
    snap = json.loads(WS_SNAPSHOT.read_text())
    assert runtime == snap, (
        "WebSocket route auth changed. If intended, update tests/_snapshots/ws_route_auth.json.\n"
        f"runtime={runtime}\nsnapshot={snap}")


def test_every_mount_is_pinned():
    """H511 review: a mounted ASGI app is invisible to the route matrices unless it
    has a route table, so every mount must be an allowlisted StaticFiles."""
    from agents.web import app
    from tests._route_introspect import iter_mounts

    seen = {m.path: type(m.app).__name__ for m in iter_mounts(app)}
    unexpected = {p: t for p, t in seen.items() if ALLOWED_MOUNTS.get(p) != t}
    assert not unexpected, (
        "Unclassified mounted sub-app(s) — guard it, or list it in ALLOWED_MOUNTS with "
        f"the reason it serves nothing credentialed: {unexpected}")


def test_mount_check_and_ws_walk_see_mounted_sub_apps():
    """The synthetic case: a WebSocket route on a mounted sub-app is enumerated under
    its mount prefix (so the WS pin catches it), and the mount itself is flagged."""
    from fastapi import FastAPI, WebSocket

    sub = FastAPI()

    @sub.websocket("/sock")
    async def _sock(ws: WebSocket):
        await ws.close()

    app = FastAPI()
    app.mount("/sub", sub)
    assert _ws_guards(app) == {"WS /sub/sock": "open"}

    from tests._route_introspect import iter_mounts
    assert [(m.path, type(m.app).__name__) for m in iter_mounts(app)] == [("/sub", "FastAPI")]
    assert ALLOWED_MOUNTS.get("/sub") != "FastAPI"


def _scan_in_body_guard_calls() -> set:
    """AST-scan agents/ for every function whose body calls a guard directly."""
    import ast

    sites = set()

    def visit(node, owner, rel):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name, rel)
                continue
            if isinstance(child, ast.Call) and owner is not None:
                fn = child.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                if name in _GUARD_CALLS:
                    sites.add(f"{rel}:{owner}")
            visit(child, owner, rel)

    for path in sorted((repo_root / "agents").rglob("*.py")):
        rel = path.relative_to(repo_root).as_posix()
        if rel == "agents/core/routers/_deps.py":   # the lazy wrappers themselves
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        visit(tree, None, rel)
    return sites


def test_every_in_body_guard_call_is_pinned():
    """H511 review: a credential check inside a handler (or a helper it calls) is
    found by the AST scan, so it cannot hide behind a "user"/"open" classification:
    each site must map to WS_GUARDED_IN_HANDLER / IN_HANDLER_STEP_UP entries, each of
    which has a probe in test_route_inhandler_guards.py."""
    found = _scan_in_body_guard_calls()
    problems = []
    if found != set(IN_HANDLER_GUARD_SITES):
        problems.append(f"in-body guard call sites changed: new={sorted(found - set(IN_HANDLER_GUARD_SITES))} "
                        f"gone={sorted(set(IN_HANDLER_GUARD_SITES) - found)}")
    proved = set(WS_GUARDED_IN_HANDLER) | set(IN_HANDLER_STEP_UP)
    unmapped = sorted(r for routes in IN_HANDLER_GUARD_SITES.values() for r in routes if r not in proved)
    if unmapped:
        problems.append(f"sites mapped to routes with no probe entry: {unmapped}")
    assert not problems, "\n".join(problems)


def test_step_up_routes_are_user_tier():
    """A step-up entry must name a live route whose dependency tier is "user" — the
    in-handler admin check is what the probe proves on top of it."""
    runtime = _runtime_guards()
    wrong = {k: runtime.get(k) for k in IN_HANDLER_STEP_UP if runtime.get(k) != "user"}
    assert not wrong, f"IN_HANDLER_STEP_UP entries not user-tier routes: {wrong}"
