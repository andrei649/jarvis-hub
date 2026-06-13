"""CLN-2/CLN-3 OpenAPI-surface guard (complements the route-parity guard).

Freezes the public OpenAPI surface — every `METHOD /path` plus its FastAPI
`operationId`. The operationId is derived from the handler function name, so a
route that is extracted into a router but renamed in the process trips this even
when the path is unchanged.

LIMITS (by design): this is a *surface* check only. It does NOT verify status
codes, response bodies, auth/guard behavior, side effects, or request
validation — a handler can be moved with an identical signature and broken logic
and still pass here. Behavior is covered by characterization tests
(test_route_guard_contracts.py) and the per-domain suites.

Re-seed on an intentional change (review the diff in the same PR):

    python tests/test_openapi_parity_guard.py --update
"""

import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

SNAPSHOT = Path(__file__).resolve().parent / "_snapshots" / "openapi_surface.json"
_METHODS = ("get", "post", "put", "delete", "patch")


def _openapi_surface() -> dict[str, str]:
    from agents import web

    paths = web.app.openapi()["paths"]
    surface: dict[str, str] = {}
    for path, ops in paths.items():
        for method, spec in ops.items():
            if method in _METHODS:
                surface[f"{method.upper()} {path}"] = spec.get("operationId", "")
    return surface


def test_openapi_surface_unchanged():
    assert SNAPSHOT.exists(), (
        f"No OpenAPI snapshot. Seed it once with: python {Path(__file__).name} --update"
    )
    expected = json.loads(SNAPSHOT.read_text())
    current = _openapi_surface()
    added = sorted(set(current) - set(expected))
    removed = sorted(set(expected) - set(current))
    drift = {
        k: (expected.get(k), current.get(k))
        for k in current
        if k in expected and expected[k] != current[k]
    }
    assert not added and not removed and not drift, (
        "OpenAPI surface changed (refactors must be behavior-preserving). Re-seed "
        "in the same PR if intentional.\n"
        f"  added:   {added}\n"
        f"  removed: {removed}\n"
        f"  operationId drift (path same, handler renamed): {drift}"
    )


if __name__ == "__main__":  # pragma: no cover
    if "--update" in sys.argv:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        surface = _openapi_surface()
        SNAPSHOT.write_text(json.dumps(surface, indent=2, sort_keys=True) + "\n")
        print(f"Seeded {SNAPSHOT} with {len(surface)} operations")
    else:
        print("pass --update to seed the snapshot")
