"""Tests for scripts/gen_api_sweep.py — the generated API-surface chapter of the deep test manual.

`docs/test-manual/14-api-surface-sweep.md` enumerates every route with its auth tier so a manual
QA run can prove it covered the whole surface. It is generated from the route snapshots, so it goes
stale the moment a route PR lands — and a stale sweep is worse than none: it tells a tester the
surface is fully enumerated when it is not.

This gate keeps it honest. If it fails, the fix is one command:

    python scripts/gen_api_sweep.py

The script is loaded by path (scripts/ is not a package), mirroring tests/test_status_sync.py.
"""

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "gen_api_sweep", REPO / "scripts" / "gen_api_sweep.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load()


def test_generated_chapter_is_current():
    """The committed chapter matches what the generator produces from the snapshots."""
    assert gen.TARGET.exists(), f"{gen.TARGET} missing — run: python scripts/gen_api_sweep.py"
    assert gen.TARGET.read_text(encoding="utf-8") == gen.build(), (
        "docs/test-manual/14-api-surface-sweep.md is stale relative to the route snapshots. "
        "Run: python scripts/gen_api_sweep.py"
    )


def test_check_mode_agrees():
    """--check exits 0 when the file is current (the CI-style invocation)."""
    assert gen.main(["--check"]) == 0


def test_every_route_is_enumerated_exactly_once():
    """No route is dropped or double-listed by the grouping logic."""
    surface = set(json.loads((REPO / "tests/_snapshots/route_surface.json").read_text(encoding="utf-8")))
    auth = set(json.loads((REPO / "tests/_snapshots/route_auth.json").read_text(encoding="utf-8")))
    text = gen.TARGET.read_text(encoding="utf-8")
    for route in surface | auth:
        method, path = route.split(" ", 1)
        row = f"| `{method}` | `{path}` |"
        assert text.count(row) == 1, f"{route} appears {text.count(row)}x in the sweep (want 1)"


def test_every_enumerated_route_carries_a_tier():
    """Each row states a real guard tier — the sweep's whole security value."""
    text = gen.TARGET.read_text(encoding="utf-8")
    rows = [ln for ln in text.split("\n") if ln.startswith("| API-") and "`/" in ln]
    assert rows, "no route rows found in the sweep"
    for ln in rows:
        assert any(f"| `{t}` |" in ln for t in ("user", "admin", "open")), (
            f"row without a known tier: {ln[:120]}"
        )


def test_tier_counts_match_the_auth_snapshot():
    """The headline tier table is derived, not hand-typed."""
    auth = json.loads((REPO / "tests/_snapshots/route_auth.json").read_text(encoding="utf-8"))
    text = gen.TARGET.read_text(encoding="utf-8")
    for tier in ("user", "admin", "open"):
        n = sum(1 for v in auth.values() if v == tier)
        assert f"| `{tier}` | {n} |" in text, f"tier table wrong for {tier} (expected {n})"


def test_pass_c_does_not_claim_the_tasks_payload_leak_is_live():
    """DRA-55: Pass C used to tell the tester to 'confirm it still leaks' for
    `GET /tasks`. That leak is closed — `format_task` in
    agents/core/routers/dashboard.py pops `payload`/`result` on all three view
    paths, pinned by tests/test_dashboard.py::test_tasks_user_tier_never_ships_payload_or_result.
    A manual chapter that asserts a live leak sends the tester hunting for a
    bug that does not exist, and invites a 'not reproducible' write-off of the
    whole pass. The chapter must state the payload-free expectation instead.
    """
    text = gen.TARGET.read_text(encoding="utf-8")
    pass_c = text.split("**Pass C")[1].split("\n\n")[0]
    assert "confirm it still leaks" not in pass_c, (
        "Pass C still tells the tester that GET /tasks leaks payload/result at user tier; "
        "that regression was fixed (TASK-5) and is pinned by tests/test_dashboard.py"
    )
    assert "/tasks" in pass_c, "Pass C should still name GET /tasks as the worked example"
    assert "absent" in pass_c, (
        "Pass C should ask the tester to confirm payload/result are ABSENT at user tier"
    )
