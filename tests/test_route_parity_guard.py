"""CLN-2/CLN-3 route-parity guard.

Behavior-preserving refactors (splitting web.py into per-domain routers,
decomposing the orchestrator) must not add, drop, rename, or re-mount a single
HTTP route. This enumerates the LIVE FastAPI app (so it sees `include_router`
mounts too, unlike a text grep of `web.py`) and asserts the method+path surface
is byte-identical to a frozen snapshot.

Update the snapshot ONLY on an intentional route change, and review the diff in
the same PR:

    python tests/test_route_parity_guard.py --update
"""

import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

SNAPSHOT = Path(__file__).resolve().parent / "_snapshots" / "route_surface.json"


def _route_surface() -> list[str]:
    # Import inside the function so collection never depends on app import order.
    from agents import web
    from tests._route_introspect import iter_effective_routes

    sig = set()
    # iter_effective_routes flattens fastapi 0.137 _IncludedRouter wrappers. An
    # APIRoute (top-level) and an _EffectiveRouteContext (included) both expose
    # .methods + .dependant; plain Starlette routes (/docs, /openapi.json) and
    # mounts lack .dependant and are excluded — exactly the old isinstance(APIRoute).
    for r in iter_effective_routes(web.app):
        if getattr(r, "methods", None) and hasattr(r, "dependant"):
            for m in (set(r.methods) - {"HEAD", "OPTIONS"}):
                sig.add(f"{m} {r.path}")
    return sorted(sig)


def test_route_surface_unchanged():
    assert SNAPSHOT.exists(), (
        f"No route snapshot. Seed it once with: python {Path(__file__).name} --update"
    )
    expected = set(json.loads(SNAPSHOT.read_text()))
    current = set(_route_surface())
    added = sorted(current - expected)
    removed = sorted(expected - current)
    assert not added and not removed, (
        "Route surface changed (refactors must be behavior-preserving). If this is "
        "intentional, re-seed the snapshot in the same PR.\n"
        f"  ADDED (unexpected new/renamed mount): {added}\n"
        f"  REMOVED (dropped/renamed/mis-mounted): {removed}"
    )


def test_route_surface_size_sanity():
    # Coarse backstop so a wholesale mount failure can't silently shrink the API
    # even if the snapshot were stale.
    assert len(_route_surface()) >= 290


if __name__ == "__main__":  # pragma: no cover
    if "--update" in sys.argv:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        surface = _route_surface()
        SNAPSHOT.write_text(json.dumps(surface, indent=2) + "\n")
        print(f"Seeded {SNAPSHOT} with {len(surface)} routes")
    else:
        print("pass --update to seed the snapshot")
