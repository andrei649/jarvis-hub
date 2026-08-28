"""SEC-2 — route-auth matrix gate (F-03 from docs/SECURITY_ROUTE_AUDIT_2026-06-17.md).

A green test suite must not be able to hide a newly-unguarded state-changing
endpoint. This reads each route's *resolved dependency graph* from the live app
(ground truth, not AST) and:

1. pins every route's guard against tests/_snapshots/route_auth.json — any new,
   removed, or drifted guard fails CI until the snapshot is consciously updated;
2. fails if any OPEN *mutating* route isn't explicitly classified as either
   INTENTIONALLY_OPEN (self-authenticating / public by design) or PENDING_GUARD
   (SEC-3 backlog);
3. keeps PENDING_GUARD honest — it may only list routes that are still open.

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
#   INTENTIONALLY_OPEN_READS — verified to expose no personal content;
#   PENDING_READ_GUARD       — touches personal data, guard still owed (debt,
#                              shrink-only, same contract as PENDING_GUARD).
INTENTIONALLY_OPEN_READS = {
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
    "GET /api/widget/{token}",           # widget capability token authenticates
    "GET /api/widget/{token}/config",
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

    "GET /api/memory/tool-spec",
    "GET /api/memory/eval/corpus",       # owned synthetic corpus, not user memory
    "GET /api/voice/capabilities",
    "GET /api/voice/wyoming",
    "GET /skills",
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
    "GET /api/oracle/status",
    # WorldView liveness booleans; the overview (recon/alerts) is guarded.
    "GET /api/worldview/status",
}

# Personal-data reads still open — SEC-B6 debt. Shrink-only.
PENDING_READ_GUARD = set()  # SEC-B6 COMPLETE — every personal-content read now carries user_guard.


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
        names = set()
        dep = getattr(r, "dependant", None)
        if dep:
            stack = list(getattr(dep, "dependencies", []))
            while stack:
                d = stack.pop()
                call = getattr(d, "call", None)
                if call is not None:
                    names.add(getattr(call, "__name__", ""))
                stack.extend(getattr(d, "dependencies", []))
        if {"_admin_guard", "admin_guard"} & names:
            guard = "admin"
        elif {"_user_guard", "user_guard"} & names:
            guard = "user"
        else:
            guard = "open"
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
