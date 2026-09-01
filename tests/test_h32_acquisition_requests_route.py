"""DRA-38 — the admin read route that makes the HUD's drive control addressable.

`POST /api/acquisition/{request_id}/drive` existed with no way to learn a
request_id: the audit ledger only exposes `request_hash` and the status snapshot
only exposes per-state counts. `GET /api/acquisition/requests` lists the
drive-eligible gaps (MISSING + BLOCKED — exactly the two states
`_TRANSITIONS` lets `synthesize_and_propose` move to `researching` from) with
enough identity to pick a row, and deliberately WITHOUT the raw goal or the
fingerprint, which stay hashed by design.

Handlers are driven directly (the guard is enforced by the route-auth matrix
snapshot), reusing the hermetic fixtures of `test_h32_synthesis_pipeline.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.routers import acquisition as acquisition_router
from agents.core.routers.acquisition import acquisition_requests
from tests.test_h32_synthesis_pipeline import GOAL, _fresh_request, _runtime


async def test_requests_lists_the_captured_gap_without_leaking_the_goal(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: runtime)

    resp = await acquisition_requests()
    body = json.loads(resp.body)

    assert resp.status_code == 200
    assert body["enabled"] is True
    assert len(body["requests"]) == 1
    row = body["requests"][0]
    assert row["request_id"] == request.request_id
    assert row["status"] == "missing"
    assert row["agent_id"] == "jarvis"
    assert row["reason"] == "tool_not_allowed"
    assert row["occurrences"] == 1
    assert isinstance(row["updated_at"], float)
    # Privacy: the raw goal and the fingerprint never reach the HUD.
    serialized = json.dumps(body)
    assert GOAL not in serialized
    assert "fingerprint" not in serialized
    assert "goal" not in serialized


async def test_requests_only_lists_drive_eligible_states(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: runtime)

    # `researching` is not drive-eligible: `_TRANSITIONS` forbids re-entering it.
    runtime.request_store.transition(request.request_id, "researching", actor="test")
    assert json.loads((await acquisition_requests()).body)["requests"] == []

    # `blocked` is drive-eligible again (blocked → researching is allowed).
    runtime.request_store.transition(request.request_id, "blocked", actor="test")
    rows = json.loads((await acquisition_requests()).body)["requests"]
    assert [row["status"] for row in rows] == ["blocked"]


async def test_requests_reports_unavailable_without_a_runtime(monkeypatch):
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: None)
    resp = await acquisition_requests()
    assert resp.status_code == 409
    assert json.loads(resp.body)["reason"] == "acquisition_unavailable"


async def test_requests_disabled_stays_lazy(tmp_path, monkeypatch):
    from agents.core.acquisition.runtime import AcquisitionRuntime

    disabled_root = tmp_path / "disabled"
    disabled = AcquisitionRuntime(enabled=lambda: False, root=disabled_root)
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: disabled)

    resp = await acquisition_requests()
    body = json.loads(resp.body)

    assert resp.status_code == 200
    assert body == {"enabled": False, "status": "disabled", "requests": []}
    assert not disabled_root.exists()  # disabled stays lazy — nothing touched disk


async def test_requests_honours_its_limit(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    for index in range(3):
        runtime.capture_gap(
            {"goal": f"{GOAL} {index}", "agent_id": "jarvis", "reason": "tool_not_allowed"}
        )
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: runtime)

    assert len(json.loads((await acquisition_requests()).body)["requests"]) == 3
    assert len(json.loads((await acquisition_requests(limit=2)).body)["requests"]) == 2
