"""A8-i — the production HTTP trigger for the governed acquisition loop.

`AcquisitionRuntime.synthesize_and_propose` had no caller under `agents/`
(BACKLOG GAP-1: "acquisition is caller-missing"), so owner gate A8's §N
walkthrough could only be scripted from a Python shell. `POST
/api/acquisition/{request_id}/drive` (admin) drives gap → reuse-check →
research → strict-local generate → sandbox verify → propose. These tests
exercise the ROUTE's contract; every composed stage keeps its own H32.x suite.
Handlers are driven directly (the guard is enforced by the route-auth matrix
snapshot), reusing the hermetic fixtures of `test_h32_synthesis_pipeline.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.routers import acquisition as acquisition_router
from agents.core.routers.acquisition import (
    AcquisitionCaseBody,
    AcquisitionDriveBody,
    acquisition_drive,
)
from tests.test_h32_synthesis_pipeline import (
    GOAL,
    _FakeResearch,
    _fresh_request,
    _generate_ok,
    _generate_placeholder,
    _runtime,
    _verified_sequence,
)


def _body():
    return AcquisitionDriveBody(
        entrypoint="run",
        cases=[AcquisitionCaseBody(input={"items": [{"id": 1}]}, expected=[1])],
    )


def _hermetic_seams(monkeypatch, generate=_generate_ok, research=None):
    monkeypatch.setattr(
        acquisition_router,
        "_drive_seams",
        lambda: (research or _FakeResearch(), generate, None),
    )
    monkeypatch.setattr(acquisition_router, "_sandbox_runner", _verified_sequence)


async def test_drive_happy_path_produces_a_pending_proposal(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: runtime)
    _hermetic_seams(monkeypatch)

    response = await acquisition_drive(request.request_id, _body())

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["status"] == "proposed" and payload["proposal_id"]
    assert payload["request_status"] == "approval_pending"
    assert runtime.request_store.get(request.request_id).status.value == "approval_pending"
    # The permanent owner-approval floor is untouched: proposal is pending, nothing installed.
    promotion = runtime.ensure_promotion()
    assert promotion.proposals.get(payload["proposal_id"]).status == "pending"


async def test_drive_unavailable_disabled_and_unknown_request(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: None)
    off = await acquisition_drive("a" * 32, _body())
    assert off.status_code == 409
    assert json.loads(off.body)["reason"] == "acquisition_unavailable"

    from agents.core.acquisition.runtime import AcquisitionRuntime

    disabled_root = tmp_path / "disabled"
    disabled = AcquisitionRuntime(enabled=lambda: False, root=disabled_root)
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: disabled)
    resp = await acquisition_drive("a" * 32, _body())
    body = json.loads(resp.body)
    assert resp.status_code == 409 and body["_degraded"]["reason"] == "acquisition_disabled"
    assert not disabled_root.exists()  # disabled stays lazy — nothing touched disk

    runtime = _runtime(tmp_path)
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: runtime)
    missing = await acquisition_drive("b" * 32, _body())
    assert missing.status_code == 404
    assert json.loads(missing.body)["reason"] == "capability_request_not_found"


async def test_drive_refuses_when_reuse_is_available(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: runtime)
    called = []
    _hermetic_seams(monkeypatch)

    async def _never(*a, **k):  # pragma: no cover - must not run
        called.append(True)

    monkeypatch.setattr(runtime, "synthesize_and_propose", _never)
    monkeypatch.setattr(
        runtime,
        "resolve_gap",
        lambda *_a, **_k: SimpleNamespace(outcome="reused", candidate_id="skill:existing"),
    )

    response = await acquisition_drive(request.request_id, _body())

    payload = json.loads(response.body)
    assert response.status_code == 409 and payload["reason"] == "reuse_available"
    assert payload["outcome"] == "reused" and payload["candidate"] == "skill:existing"
    assert called == []


async def test_drive_degrades_honestly_without_searxng_or_local_llm(tmp_path, monkeypatch):
    from agents.core.plugins.degradation import is_degraded

    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: runtime)

    # No local backend → local_llm_required (the seam probe raises RuntimeError).
    class _NoLocal:
        @property
        def local_backend(self):
            raise RuntimeError("No local LLM backend available (strict-local path).")

    monkeypatch.setattr(
        acquisition_router, "get_orch", lambda: SimpleNamespace(llm_router=_NoLocal())
    )
    resp = await acquisition_drive(request.request_id, _body())
    body = json.loads(resp.body)
    assert resp.status_code == 409 and is_degraded(body)
    assert body["_degraded"]["reason"] == "local_llm_required"

    # Local backend present but SEARXNG_URL unset → searxng_backend_required.
    monkeypatch.setattr(
        acquisition_router,
        "get_orch",
        lambda: SimpleNamespace(llm_router=SimpleNamespace(local_backend=object())),
    )
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    resp2 = await acquisition_drive(request.request_id, _body())
    body2 = json.loads(resp2.body)
    assert resp2.status_code == 409 and body2["_degraded"]["reason"] == "searxng_backend_required"
    assert body2["_degraded"]["needs"] == ["SEARXNG_URL"]
    # Neither degrade advanced the request — it is still drivable.
    assert runtime.request_store.get(request.request_id).status.value == "missing"


async def test_drive_synthesis_failure_reports_the_request_state(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: runtime)
    _hermetic_seams(monkeypatch, generate=_generate_placeholder)

    response = await acquisition_drive(request.request_id, _body())

    payload = json.loads(response.body)
    assert response.status_code == 409 and payload["reason"] == "synthesis_failed"
    assert payload["request_status"] == "blocked"  # placeholder body → GenerationError
    # blocked → researching is legal, so the same request can be re-driven after a fix.

    research_down = _FakeResearch(raises=True)
    retry_runtime = _runtime(tmp_path / "second")
    retry = _fresh_request(retry_runtime)
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: retry_runtime)
    _hermetic_seams(monkeypatch, research=research_down)
    second = await acquisition_drive(retry.request_id, _body())
    assert json.loads(second.body)["request_status"] == "blocked"


async def test_drive_goal_is_system_owned_not_caller_supplied(tmp_path, monkeypatch):
    """The contract's goal comes from the captured request — a caller cannot
    smuggle a different goal past the grounding gate via the drive body."""
    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)
    monkeypatch.setattr(acquisition_router, "_get_runtime", lambda: runtime)
    seen_contracts = []

    async def _spy(request_id, *, contract, research, generate, runner=None):
        seen_contracts.append(contract)
        return None

    monkeypatch.setattr(runtime, "synthesize_and_propose", _spy)
    _hermetic_seams(monkeypatch)

    await acquisition_drive(request.request_id, _body())

    assert len(seen_contracts) == 1 and seen_contracts[0].goal == GOAL
