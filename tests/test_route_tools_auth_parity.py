"""0.36 — unify the MCP route-tool allow-list with route_auth.json.

The agent-native route tools (`mcp/route_tools.py`) expose a small curated set of
HTTP routes to the model. That allow-list used to declare nothing about each
route's auth posture, so it could silently drift from the route's real guard —
or, worse, expose an over-privileged route (an admin-only or mutating route) as
an agent **read** tool. `tests/_snapshots/route_auth.json` (kept honest by the
SEC-2 route-auth matrix gate) is the single source of truth for every route's
guard; this pins each allow-list spec's declared `guard` to it.

Invariants enforced here:
  * every allow-listed path+method actually exists in route_auth.json;
  * each spec's *declared* guard equals the route's *real* guard (no drift);
  * a READ tool is never admin-guarded (no privilege leak to agents);
  * a MUTATING tool is never `open` (a write surface is always authenticated).
"""

import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.mcp.route_tools import (  # noqa: E402
    MUTATING_ROUTE_ALLOWLIST,
    ROUTE_TOOL_ALLOWLIST,
)

SNAPSHOT = repo_root / "tests" / "_snapshots" / "route_auth.json"
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _auth() -> dict:
    return json.loads(SNAPSHOT.read_text())


def test_read_tools_match_route_auth_and_are_not_admin():
    auth = _auth()
    for spec in ROUTE_TOOL_ALLOWLIST:
        assert spec.method == "GET", f"{spec.name}: read tools must be GET"
        key = f"{spec.method} {spec.path}"
        assert key in auth, f"{spec.name}: {key} missing from route_auth.json (drift)"
        assert spec.guard == auth[key], (
            f"{spec.name}: declared guard {spec.guard!r} != route_auth {auth[key]!r}"
        )
        assert spec.guard in {"open", "user"}, (
            f"{spec.name}: a READ tool must not expose an admin route ({spec.guard!r})"
        )


def test_mutating_tools_match_route_auth_and_are_authenticated():
    auth = _auth()
    for spec in MUTATING_ROUTE_ALLOWLIST:
        assert spec.method in MUTATING, f"{spec.name}: mutating tools must be a write verb"
        key = f"{spec.method} {spec.path}"
        assert key in auth, f"{spec.name}: {key} missing from route_auth.json (drift)"
        assert spec.guard == auth[key], (
            f"{spec.name}: declared guard {spec.guard!r} != route_auth {auth[key]!r}"
        )
        assert spec.guard in {"user", "admin"}, (
            f"{spec.name}: a WRITE tool must be authenticated, never open ({spec.guard!r})"
        )


def test_allowlists_do_not_overlap():
    # A path should not be exposed as both a read tool and a write tool.
    read_paths = {s.path for s in ROUTE_TOOL_ALLOWLIST}
    write_paths = {s.path for s in MUTATING_ROUTE_ALLOWLIST}
    assert read_paths.isdisjoint(write_paths)
