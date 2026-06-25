"""V3 — capability readiness matrix (fleet-coordination gate).

Generalizes the route-auth matrix from "every mutator is guarded" to "every capability
is honestly stated". Snapshots the deterministic capability set (the static plugin
manifests) into `_snapshots/capability_readiness.json` and fails CI on:

  * **drift** — a capability added / removed / silently state-changed (e.g. a plugin
    disabled WIRED→SEAM) vs the committed snapshot;
  * **fabricated VERIFIED** — a record at VERIFIED/GA without a harness_id (only the V1
    reality harness may promote — this guards the registry invariant);
  * **unclassified SEAM** — a capability left a stub that isn't in INTENTIONALLY_SEAM.

Honest escape sets (mirroring route_auth's INTENTIONALLY_OPEN / PENDING_GUARD, which
SEC-3 drove to empty): INTENTIONALLY_SEAM (by-design stubs) and PENDING_VERIFY (wired
but not yet reality-verified — the shrinking backlog). Both are kept honest by a test so
they can't go stale.

Scope: this slice covers the **plugin** capability set, which is enumerable statically
(no orchestrator boot). Components/skills (need a booted fixture) and cross-agent
interface-contract drift fold in as Track V tightens.

Re-seed on an intentional change, reviewed in the same PR:

    python tests/test_capability_readiness_matrix.py --update
"""

import json
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

SNAPSHOT = Path(__file__).resolve().parent / "_snapshots" / "capability_readiness.json"


@pytest.fixture(autouse=True)
def _isolate_registry_state():
    """The matrix asserts the static-derivable truth; transient in-process harness
    promotions / manual overrides (which another test may have left behind) must not
    leak in and cause spurious drift. Durable verification lives in this committed
    snapshot, not the in-memory store."""
    from agents.core.observability import capability_registry as cr
    cr.clear_verifications()
    cr._OVERRIDES.clear()
    yield
    cr.clear_verifications()
    cr._OVERRIDES.clear()

# By-design stubs that are allowed to stay SEAM (none today — all plugins are enabled).
INTENTIONALLY_SEAM: set[str] = set()
# WIRED capabilities not yet promoted by a reality harness — the shrinking backlog.
# (Today's hard gate only forbids SEAM; this set is forward-looking for when the gate
# tightens to "user-facing must be VERIFIED".) Kept honest by test below.
PENDING_VERIFY: set[str] = set()


def _records():
    """Deterministic capability records — plugins only (static manifest registry)."""
    from agents.core.observability import capability_registry as cr
    return cr.build_records(orch=None)


def _state_map() -> dict:
    return {r.id: r.state for r in _records()}


def test_readiness_matrix_no_drift():
    assert SNAPSHOT.exists(), (
        f"No readiness snapshot. Seed it once with: python {Path(__file__).name} --update"
    )
    expected = json.loads(SNAPSHOT.read_text())
    current = _state_map()
    added = sorted(set(current) - set(expected))
    removed = sorted(set(expected) - set(current))
    changed = sorted(k for k in set(current) & set(expected) if current[k] != expected[k])
    assert not (added or removed or changed), (
        "Capability readiness changed. If intentional, re-seed "
        f"{SNAPSHOT.name} in the same PR (and update INTENTIONALLY_SEAM / PENDING_VERIFY).\n"
        f"  ADDED:   {added}\n  REMOVED: {removed}\n"
        f"  CHANGED: {[(k, expected[k], current[k]) for k in changed]}"
    )


def test_no_fabricated_verified():
    from agents.core.observability import capability_registry as cr
    offenders = [r.id for r in _records() if r.state in (cr.VERIFIED, cr.GA) and not r.harness_id]
    assert not offenders, (
        "Capability(ies) claim VERIFIED/GA without a harness_id — only the V1 reality "
        f"harness may promote: {offenders}"
    )


def test_no_user_facing_capability_is_seam():
    from agents.core.observability import capability_registry as cr
    seam = [r.id for r in _records() if r.state == cr.SEAM]
    unclassified = sorted(c for c in seam if c not in INTENTIONALLY_SEAM)
    assert not unclassified, (
        "Capability(ies) are SEAM (stub/unwired) with no classification. Wire them, or "
        f"add to INTENTIONALLY_SEAM with a reason:\n{unclassified}"
    )


def test_escape_sets_are_honest():
    from agents.core.observability import capability_registry as cr
    recs = {r.id: r for r in _records()}
    # INTENTIONALLY_SEAM entries must actually exist and actually be SEAM.
    stale_seam = sorted(c for c in INTENTIONALLY_SEAM if recs.get(c) is None or recs[c].state != cr.SEAM)
    # PENDING_VERIFY entries must exist and not already be VERIFIED/GA (else remove them).
    stale_pending = sorted(
        c for c in PENDING_VERIFY if recs.get(c) is None or recs[c].state in (cr.VERIFIED, cr.GA)
    )
    assert not stale_seam, f"INTENTIONALLY_SEAM is stale (not seam / gone): {stale_seam}"
    assert not stale_pending, f"PENDING_VERIFY is stale (verified / gone): {stale_pending}"


if __name__ == "__main__":  # pragma: no cover
    if "--update" in sys.argv:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        data = dict(sorted(_state_map().items()))
        SNAPSHOT.write_text(json.dumps(data, indent=2) + "\n")
        print(f"Seeded {SNAPSHOT} with {len(data)} capabilities")
    else:
        print("pass --update to seed the snapshot")
