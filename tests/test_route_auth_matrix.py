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
}

# Open mutating routes still awaiting a guard — SEC-3 backlog. Listed explicitly
# so the debt is bounded and visible; this set shrinks (never grows) as SEC-3
# lands guards and the snapshot flips those routes to user/admin.
PENDING_GUARD = set()  # SEC-3 COMPLETE — every open mutator is now guarded or in INTENTIONALLY_OPEN.


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
