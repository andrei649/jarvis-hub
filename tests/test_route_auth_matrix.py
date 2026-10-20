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
   PUBLIC_BY_DESIGN (no credential exists to check);
5. (H511 review) AST-scans agents/ for every in-body guard call or reference and
   every in-body credential decision (`_web_principal`, `_admin_credential_ok`,
   `_request_is_authed`, `_user_credential_required`, the MCP identity checks, ...),
   pins each site with the probe(s) that prove it, and flags calls that cannot take
   effect; and pins every mounted or host-dispatched sub-app (`Mount`/`Host`, at any
   depth) by its served path and type.

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
# Depends) — found by an AST scan, pinned here. Each site names the probe(s) that
# prove that very call behaviourally, as "tests/<file>.py::<test>[<param>]";
# tests/test_route_inhandler_guards.py::test_every_pinned_site_names_a_live_probe
# fails when a named probe does not exist. A new in-body guard call fails CI until
# it is pinned here with a probe.
_INH = "tests/test_route_inhandler_guards.py::"
IN_HANDLER_GUARD_SITES = {
    "agents/core/routers/kanban.py:events": (
        _INH + "test_websocket_in_handler_guard_refuses_unauthenticated[WS /api/kanban/events]",
        _INH + "test_websocket_closes_when_credential_is_revoked_mid_stream[WS /api/kanban/events]"),
    "agents/core/routers/hermes_runtime.py:websocket_rpc": (
        _INH + "test_websocket_in_handler_guard_refuses_unauthenticated[WS /api/hermes/ws]",
        _INH + "test_websocket_closes_when_credential_is_revoked_mid_stream[WS /api/hermes/ws]"),
    # The per-event re-check on the push path (not the receive loop's).
    "agents/core/routers/hermes_runtime.py:_send_events": (
        _INH + "test_hermes_event_push_stops_when_credential_is_revoked",),
    "agents/core/routers/composer_vision.py:_selected_owner_scope": tuple(
        _INH + f"test_step_up_refuses_a_user_tier_caller[{route}]" for route in sorted(IN_HANDLER_STEP_UP)),
}
_GUARD_CALLS = {"admin_guard", "user_guard", "_admin_guard", "_user_guard"}

# H511 review: the tier decision made in a body from the credential primitives —
# `_web_principal(...).admin`, `owner_web_principal`, `_admin_credential_ok`,
# `_user_credential_ok` (incl. a `getattr(web, "<name>")` lookup). The dependency
# graph sees only the route's dependency tier; these sites branch on admin vs user
# (or valid vs invalid) inside it. Each names the test that fails when its decision
# is forced (mutation-checked: replacing the call with an always-admin / always-valid
# value fails the named test).
_TIER_CALLS = {"_web_principal", "owner_web_principal", "_admin_credential_ok", "_user_credential_ok",
               # Round 3: the other credential decisions — "is this request authed",
               # "is a credential required at all", and the MCP identity re-checks.
               "_request_is_authed", "_user_credential_required",
               "_mcp_identity_check", "_mcp_agent_identity_check"}
_DEPENDENCY_WRAPPERS = {"Depends", "Security"}
IN_HANDLER_TIER_SITES = {
    # The primitives themselves (agents/web.py).
    "agents/web.py:_admin_guard": ("tests/test_admin_guard_hf7.py::test_admin_guard_token_path_unaffected",),
    "agents/web.py:_user_credential_ok": ("tests/test_user_guard_hf1.py::test_user_guard_admin_token_is_superset",),
    "agents/web.py:_user_guard": ("tests/test_user_guard_hf1.py::test_user_guard_token",),
    "agents/web.py:_web_principal": (
        "tests/test_commands_catalog.py::test_bad_owner_token_and_query_flag_cannot_reveal_owner_commands",),
    "agents/web.py:_request_is_authed": ("tests/test_rate_limit_hf2.py::test_request_is_authed_requires_valid_token",),
    "agents/web.py:_mcp_identity_check": (
        "tests/test_h273e_provenance_review.py::"
        "test_the_mcp_identity_check_refuses_a_revoked_credential_as_the_guard_does",),
    # Step-ups inside user-tier routes.
    "agents/web.py:chat": (
        "tests/test_h011_preappend_commands.py::test_cli_web_owner_registry_contract_preserves_history_and_exit_status",),
    "agents/web.py:chat_stream": (_INH + "test_chat_stream_binds_the_credentialed_principal",),
    "agents/core/routers/canvas.py:canvas_post": (
        "tests/test_h309_pointer.py::test_a_tip_through_the_http_route_is_marked_unless_the_owner_sent_it",),
    "agents/core/routers/actions.py:actions_request": (
        "tests/test_h487_approval_groups.py::test_owner_http_producer_and_optional_projection_with_legacy_complete_actions",),
    "agents/core/routers/commands.py:command_catalog": (
        "tests/test_commands_catalog.py::test_user_catalog_contains_only_commands_visible_to_that_chat_principal",),
    "agents/core/routers/skills.py:_request_principal": (_INH + "test_sandbox_principal_follows_the_credential",),
    "agents/core/routers/chat_pending.py:http_actor": (
        "tests/test_pending_input_http_poll.py::test_revocation_retires_polled_or_unpolled_wait",
        _INH + "test_pending_input_actor_follows_the_credential"),
    "agents/core/routers/autonomy.py:_consent_admin_current": (_INH + "test_consent_recheck_follows_the_credential",),
    # Round 3: `_request_is_authed` / `_user_credential_required` / the MCP identity
    # checks are credential decisions too.
    "agents/web.py:_rate_limit": (
        "tests/test_rate_limit_hf2.py::test_middleware_returns_429_for_unauthed",
        "tests/test_rate_limit_hf2.py::test_valid_token_is_exempt_from_limit"),
    "agents/core/routers/mcp.py:mcp_server_rpc": (
        _INH + "test_in_handler_guard_refuses_without_credential[POST /api/mcp/server/rpc]",
        _INH + "test_in_handler_guard_refuses_without_credential[POST /api/mcp/server/rpc [oauth]]"),
    "agents/web.py:_mcp_agent_identity_check": (
        "tests/test_h10_5_mcp_server.py::test_production_agent_guard_requires_owner_identity_for_model_lifecycle",),
    "agents/web.py:_mcp_agent_request_guard": (
        "tests/test_h10_5_mcp_server.py::test_production_agent_guard_requires_owner_identity_for_model_lifecycle",),
    "agents/web.py:_build_mcp_mutating_route_tools": (
        _INH + "test_mcp_mutating_tools_are_bound_to_the_identity_check",),
}

# H511 review: mounted ASGI sub-apps, keyed by the path each is *served* under
# (iter_mounts walks included routers and nested mounts). The route matrices cannot
# see inside a mount, so every mount must be listed here with the class its app must
# be an instance of. StaticFiles serves GET/HEAD bytes only and refuses WebSocket
# scopes.
ALLOWED_MOUNTS = {
    "/static": "starlette.staticfiles.StaticFiles",
    "/v2/assets": "starlette.staticfiles.StaticFiles",
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


def _mount_violations(app) -> dict:
    """Every mount (at any depth, by served path) that is not an allowlisted instance."""
    import importlib

    from tests._route_introspect import iter_mounts

    def allowed(path, mounted):
        dotted = ALLOWED_MOUNTS.get(path)
        if not dotted:
            return False
        module, _, cls = dotted.rpartition(".")
        return isinstance(mounted, getattr(importlib.import_module(module), cls))

    return {m.path: type(m.app).__name__ for m in iter_mounts(app) if not allowed(m.path, m.app)}


def test_every_mount_is_pinned():
    """H511 review: a mounted ASGI app is invisible to the HTTP route matrix, so every
    mount — top-level, inside an included router, or nested in a sub-app — must be an
    allowlisted instance at the path it is served under."""
    from agents.web import app
    from tests._route_introspect import iter_mounts

    assert {m.path for m in iter_mounts(app)} >= set(ALLOWED_MOUNTS), "a pinned mount is gone — drop it"
    unexpected = _mount_violations(app)
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
    assert _mount_violations(app) == {"/sub": "FastAPI"}


def test_mount_check_sees_a_mount_inside_an_included_router():
    """H511 review (round 2): `router.mount()` on an included APIRouter is served, with
    no guard, but sits behind fastapi's opaque `_IncludedRouter` — a top-level-only
    scan missed it. It is reported under the path that actually answers, and a
    StaticFiles-named impostor class at an allowlisted path is still refused."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    async def raw(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"unguarded"})

    router = APIRouter(prefix="/api")
    router.mount("/inner", raw)
    outer = APIRouter(prefix="/outer")
    outer.include_router(router)
    app = FastAPI()
    app.include_router(router)
    app.include_router(outer)

    from tests._route_introspect import iter_mounts
    served = {m.path for m in iter_mounts(app)}
    client = TestClient(app)
    for path in served:   # each reported path is the one that serves the mounted app
        assert client.get(path + "/x").text == "unguarded", path
    assert len(served) == 2 and "/inner" in served
    assert set(_mount_violations(app)) == served

    class StaticFiles:   # same class name as the allowlisted type, not the type
        async def __call__(self, scope, receive, send):
            await raw(scope, receive, send)

    impostor = FastAPI()
    impostor.mount("/static", StaticFiles())
    assert _mount_violations(impostor) == {"/static": "StaticFiles"}


def test_host_sub_apps_are_walked_like_mounts():
    """H511 review (round 3): starlette's `Host` route is a sibling of `Mount`, not a
    subclass — a host-dispatched sub-app was invisible to both walks. Its upgrade routes
    are enumerated under `//<host><path>` and the Host itself is a pinned mount, whether
    its app has a route table or is an opaque ASGI callable."""
    from fastapi import APIRouter, FastAPI, WebSocket
    from starlette.routing import Host, Mount

    sub = FastAPI()

    @sub.websocket("/s")
    async def _s(ws: WebSocket):
        await ws.close()

    async def raw(scope, receive, send):
        return None

    app = FastAPI()
    app.router.routes.append(Host("evil.example", app=sub))
    assert _ws_guards(app) == {"WS //evil.example/s": "open"}
    assert _mount_violations(app) == {"//evil.example": "FastAPI"}

    # A Host behind a Mount and inside an included router, and an opaque Host app.
    deep = FastAPI()
    deep.router.routes.append(Host("in.example", app=sub))
    router = APIRouter()
    router.routes.append(Host("raw.example", app=raw))
    app2 = FastAPI()
    app2.router.routes.append(Mount("/m", app=deep))
    app2.include_router(router)
    assert _ws_guards(app2) == {"WS /m//in.example/s": "open"}
    assert _mount_violations(app2) == {"/m": "FastAPI", "/m//in.example": "FastAPI",
                                       "//raw.example": "function"}


def _scan_in_body_guard_calls(root=None, rel_to=None):
    """AST-scan agents/ for every function whose body calls a guard or a tier primitive.

    Returns (guard_sites, tier_sites, suspicious). A site is "file:function". Calls are
    matched by name, by an import alias of a name (`from ._deps import admin_guard as
    ag`), and by a string lookup (`getattr(web, "_web_principal")`); a bare reference
    (`g = web._admin_guard`, a guard handed over as a callback) is a site too. A
    reference inside `Depends(...)`/`Security(...)` is a declared dependency, not an
    in-body call, and is skipped. `suspicious` lists calls that cannot be doing their
    job: an async guard that is not awaited, a call under a constant-false
    `if`/`while`, or one inside a `try` with a broad handler (bare / `Exception` /
    `BaseException` / `HTTPException`) that does nothing (`pass` / `...` / `continue`)
    or that neither raises nor returns while code still follows the try in its
    function (e.g. `except Exception as e: logger.warning(e)`)."""
    import ast

    root = root or repo_root / "agents"
    rel_to = rel_to or repo_root
    watched = _GUARD_CALLS | _TIER_CALLS
    awaited_only = _GUARD_CALLS | {"owner_web_principal"}
    guard_sites, tier_sites, suspicious = set(), set(), []
    callee_funcs = set()   # ids of Call.func nodes, so a call is not also counted as a reference

    def ref_name(node):
        return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""

    refusals = {"Exception", "BaseException", "HTTPException"}   # what a guard raises

    def catches_refusal(handler):
        if handler.type is None:
            return True
        kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        return any((k.id if isinstance(k, ast.Name) else getattr(k, "attr", "")) in refusals for k in kinds)

    def leaves(handler):
        """The handler stops the guarded flow: it raises or returns (a refusal response,
        or after closing the socket). Nested defs do not count."""
        stack = list(handler.body)
        while stack:
            s = stack.pop()
            if isinstance(s, (ast.Raise, ast.Return)):
                return True
            if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                stack.extend(ast.iter_child_nodes(s))
        return False

    terminal = set()   # ids of Try nodes that end their function (falling off = return)

    def mark_terminal(tree):
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                last = fn.body[-1]
                while isinstance(last, (ast.With, ast.AsyncWith)):
                    last = last.body[-1]
                if isinstance(last, ast.Try):
                    terminal.add(id(last))

    def inert(handler):
        return all(isinstance(s, (ast.Pass, ast.Continue))
                   or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)) for s in handler.body)

    def swallowing(try_node):
        # A broad handler that does nothing is always flagged. Round 3: so is any broad
        # handler that neither raises nor returns — logging the refusal does not stop
        # execution carrying on past it — unless nothing follows the try in its function.
        return any(catches_refusal(h) and (inert(h) or (id(try_node) not in terminal and not leaves(h)))
                   for h in try_node.handlers)

    def visit(node, owner, rel, aliases, dead, awaited):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                name = owner if isinstance(child, ast.Lambda) else child.name
                visit(child, name, rel, aliases, False, False)
                continue
            child_dead = dead
            if isinstance(child, (ast.If, ast.While)) and isinstance(child.test, ast.Constant) \
                    and not child.test.value:
                # Only the body is dead; the else branch (orelse) runs.
                for stmt in child.body:
                    visit_stmt(stmt, owner, rel, aliases, True)
                for stmt in child.orelse:
                    visit_stmt(stmt, owner, rel, aliases, dead)
                continue
            if isinstance(child, ast.Try) and swallowing(child):
                for stmt in child.body:
                    visit_stmt(stmt, owner, rel, aliases, True)
                for part in (*child.handlers, *child.orelse, *child.finalbody):
                    visit_stmt(part, owner, rel, aliases, dead)
                continue
            name = ""
            if isinstance(child, ast.Call):
                fn = child.func
                raw = ref_name(fn)
                name = aliases.get(raw, raw) if owner is not None else ""
                callee_funcs.add(id(fn))
                if raw in _DEPENDENCY_WRAPPERS:
                    continue   # Depends(admin_guard): a declared dependency, not an in-body call
            elif owner is not None and isinstance(child, ast.Constant) and child.value in watched:
                name = child.value   # getattr(module, "<name>") lookup
            elif owner is not None and isinstance(child, (ast.Name, ast.Attribute)) \
                    and isinstance(child.ctx, ast.Load) and id(child) not in callee_funcs:
                # Round 3: a bare reference (`g = web._admin_guard`, a guard passed as a
                # callback) is a site too — the call through the local name is not.
                raw = ref_name(child)
                name = aliases.get(raw, raw)
            if name in watched:
                site = f"{rel}:{owner}"
                (guard_sites if name in _GUARD_CALLS else tier_sites).add(site)
                line = f"{rel}:{child.lineno} {name}"
                if child_dead:
                    suspicious.append(line + " (dead or swallowed)")
                elif isinstance(child, ast.Call) and name in awaited_only and not awaited:
                    suspicious.append(line + " (not awaited)")
            visit(child, owner, rel, aliases, child_dead, isinstance(child, ast.Await))

    def visit_stmt(stmt, owner, rel, aliases, dead):
        wrapper = ast.Module(body=[stmt], type_ignores=[])
        visit(wrapper, owner, rel, aliases, dead, False)

    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(rel_to).as_posix()
        if rel == "agents/core/routers/_deps.py":   # the lazy wrappers themselves
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        aliases = {a.asname: a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                   for a in n.names if a.asname and a.name in watched}
        terminal.clear()        # node ids are only meaningful while this tree is alive
        callee_funcs.clear()
        mark_terminal(tree)
        visit(tree, None, rel, aliases, False, False)
    return guard_sites, tier_sites, suspicious


def test_every_in_body_guard_call_is_pinned():
    """H511 review: a credential check inside a handler (or a helper it calls) is
    found by the AST scan, so it cannot hide behind a "user"/"open" classification:
    each site is pinned in IN_HANDLER_GUARD_SITES / IN_HANDLER_TIER_SITES with the
    probes that prove it, and no scanned call may be dead, swallowed or un-awaited."""
    guard_sites, tier_sites, suspicious = _scan_in_body_guard_calls()
    problems = []
    if guard_sites != set(IN_HANDLER_GUARD_SITES):
        problems.append(f"in-body guard call sites changed: new={sorted(guard_sites - set(IN_HANDLER_GUARD_SITES))} "
                        f"gone={sorted(set(IN_HANDLER_GUARD_SITES) - guard_sites)}")
    tier_only = tier_sites - guard_sites
    if tier_only != set(IN_HANDLER_TIER_SITES):
        problems.append(f"in-body tier decision sites changed: new={sorted(tier_only - set(IN_HANDLER_TIER_SITES))} "
                        f"gone={sorted(set(IN_HANDLER_TIER_SITES) - tier_only)}")
    if suspicious:
        problems.append(f"guard calls that cannot take effect: {suspicious}")
    empty = sorted(k for k, v in {**IN_HANDLER_GUARD_SITES, **IN_HANDLER_TIER_SITES}.items() if not v)
    if empty:
        problems.append(f"pinned sites with no probe: {empty}")
    assert not problems, "\n".join(problems)


def test_guard_scan_flags_aliases_lookups_and_inert_calls(tmp_path):
    """The scan itself: an aliased import and a getattr lookup are sites; a call under
    `if False:`, inside a swallowing try, or never awaited is flagged as inert."""
    pkg = tmp_path / "agents"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        "from agents.core.routers._deps import admin_guard as ag\n"
        "async def aliased(r):\n    await ag(r)\n"
        "def looked_up(web, r):\n    return getattr(web, '_web_principal')(r).admin\n"
        "async def dead(r):\n    if False:\n        await ag(r)\n"
        "async def swallowed(r):\n    try:\n        await ag(r)\n    except Exception:\n        pass\n"
        "async def discarded(r):\n    ag(r)\n"
        "async def live_else(r):\n    if 0:\n        pass\n    else:\n        await ag(r)\n"
        "async def narrow(r):\n    try:\n        await ag(r)\n    except WebSocketDisconnect:\n        pass\n"
        # Round 3: a broad handler that only logs swallows the refusal (the work after
        # the try still runs); one that re-raises, returns (after closing), or ends the
        # function (the try is its last statement) does not.
        "async def logged(r):\n    try:\n        await ag(r)\n    except Exception as e:\n"
        "        logger.warning(e)\n    return await act(r)\n"
        "async def terminal(ws):\n    try:\n        await ag(ws)\n        await ws.send_text('x')\n"
        "    except HTTPException:\n        await ws.close(code=1008)\n"
        "async def reraised(r):\n    try:\n        await ag(r)\n    except Exception as e:\n"
        "        logger.warning(e)\n        raise\n"
        "async def refused(ws):\n    try:\n        await ag(ws)\n    except HTTPException:\n"
        "        await ws.close(code=1008)\n        return\n"
        # A local rebinding of a guard, and the credential-decision primitives.
        "async def rebound(web, r):\n    g = web._admin_guard\n    await g(r)\n"
        "def authed(web, r):\n    if not web._request_is_authed(r):\n        return 401\n"
        "def required(web):\n    return web._user_credential_required()\n"
        "def mcp_check(web, t):\n    return web._mcp_agent_identity_check(t)\n"
        # A dependency declaration is not an in-body call.
        "def wired(router, x):\n    router.include_router(x, dependencies=[Depends(ag)])\n")
    guard, tier, suspicious = _scan_in_body_guard_calls(pkg, tmp_path)
    assert guard == {f"agents/mod.py:{f}"
                     for f in ("aliased", "dead", "swallowed", "discarded", "live_else", "narrow",
                               "logged", "terminal", "reraised", "refused", "rebound")}
    assert tier == {f"agents/mod.py:{f}" for f in ("looked_up", "authed", "required", "mcp_check")}
    assert {s.split()[0] for s in suspicious} == {
        "agents/mod.py:8", "agents/mod.py:11", "agents/mod.py:15", "agents/mod.py:28"}


def test_step_up_routes_are_user_tier():
    """A step-up entry must name a live route whose dependency tier is "user" — the
    in-handler admin check is what the probe proves on top of it."""
    runtime = _runtime_guards()
    wrong = {k: runtime.get(k) for k in IN_HANDLER_STEP_UP if runtime.get(k) != "user"}
    assert not wrong, f"IN_HANDLER_STEP_UP entries not user-tier routes: {wrong}"
