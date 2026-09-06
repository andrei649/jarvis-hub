"""E5.0 — the company-mode routes.

Three user-guarded routes and, deliberately, no fourth. The most important test
in this file is the one asserting what is *absent*: there is no route that starts
a work run, because starting one requires an owner-approved goal decided in the
inbox, and a "start" button here would be a second, weaker approval path for the
most powerful thing in the product.

The rest pin the honest-reporting properties: the flag state travels with the
read (so an empty list can say *why* it is empty), a stop is narrowing-only and
needs no approval, and no task payload ever reaches the wire.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "agents"))

from agents.core.autonomy.work_runs import WorkRunLedger  # noqa: E402
from agents.core.routers import company as company_routes  # noqa: E402
from agents.core.routers._deps import user_guard  # noqa: E402


def _goal(goal_id: str = "g-1", title: str = "Prepare the quarterly brief"):
    return types.SimpleNamespace(
        goal_id=goal_id, title=title,
        approved_by="receipt:owner-accepted-1", deadline_at=100_000.0,
    )


@pytest.fixture
def ledger():
    led = WorkRunLedger(":memory:", clock=lambda: 1_000.0)
    yield led
    led.close()


def _app():
    app = FastAPI()
    app.include_router(company_routes.router)
    return app


@pytest.fixture
def client(ledger, monkeypatch):
    async def _get():
        return ledger

    monkeypatch.setattr(company_routes, "_get_ledger", _get)
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    app = _app()
    app.dependency_overrides[user_guard] = lambda: None
    return TestClient(app)


# ── the surface, and what it deliberately omits ──────────────────────────────

def test_there_is_no_route_that_starts_a_run():
    """Opening a run needs an owner-approved goal, decided in the inbox. A start
    button here would be a second, weaker approval path for the most powerful
    thing in the product."""
    from tests._route_introspect import iter_effective_routes

    paths = {
        (m, r.path)
        for r in iter_effective_routes(_app())
        for m in sorted(getattr(r, "methods", ()) or ())
        # FastAPI's own docs/openapi routes come with the bare app, not the router
        if m not in {"HEAD", "OPTIONS"} and r.path.startswith("/api/")
    }
    assert paths == {
        ("GET", "/api/company/runs"),
        ("GET", "/api/company/runs/{run_id}"),
        ("POST", "/api/company/runs/{run_id}/stop"),
    }


def test_every_route_is_user_guarded():
    """Mirror tests/test_route_auth_matrix._runtime_guards: walk the dependant graph."""
    from tests._route_introspect import iter_effective_routes

    guarded = {}
    for route in iter_effective_routes(_app()):
        dep = getattr(route, "dependant", None)
        if not getattr(route, "methods", None) or dep is None:
            continue
        names = set()
        stack = list(getattr(dep, "dependencies", []))
        while stack:
            d = stack.pop()
            call = getattr(d, "call", None)
            if call is not None:
                names.add(getattr(call, "__name__", ""))
            stack.extend(getattr(d, "dependencies", []))
        guarded[route.path] = names
    assert guarded == {
        "/api/company/runs": {"user_guard"},
        "/api/company/runs/{run_id}": {"user_guard"},
        "/api/company/runs/{run_id}/stop": {"user_guard"},
    }


def test_routes_refuse_without_a_user_token(ledger, monkeypatch):
    async def _get():
        return ledger

    monkeypatch.setattr(company_routes, "_get_ledger", _get)
    app = _app()

    async def _deny(request: Request):
        raise HTTPException(status_code=401, detail="user token required")

    app.dependency_overrides[user_guard] = _deny
    c = TestClient(app)
    assert c.get("/api/company/runs").status_code == 401
    assert c.get("/api/company/runs/x").status_code == 401
    assert c.post("/api/company/runs/x/stop").status_code == 401


# ── the brief ────────────────────────────────────────────────────────────────

def test_the_brief_lists_runs_with_their_honest_headline(client, ledger):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="read the numbers",
                       outcome="ok", task_id=11)
    body = client.get("/api/company/runs").json()
    assert body["enabled"] is True
    assert body["empty"] is False
    assert body["counts"]["runs"] == 1
    assert body["runs"][0]["headline"] == "in progress"
    assert body["runs"][0]["verdict_lines"] == ["· nobody has graded it yet"]


def test_an_empty_brief_says_why_it_is_empty(client):
    body = client.get("/api/company/runs").json()
    assert body["empty"] is True
    assert body["reason"] == "no work runs have been opened"


def test_with_the_flag_off_the_read_still_answers_and_says_so(ledger, monkeypatch):
    """The HUD needs to distinguish "off" from "a quiet night", so the read works
    either way and reports the flag rather than 404-ing."""
    async def _get():
        return ledger

    monkeypatch.setattr(company_routes, "_get_ledger", _get)
    monkeypatch.delenv("JARVIS_COMPANY_MODE", raising=False)
    app = _app()
    app.dependency_overrides[user_guard] = lambda: None
    body = TestClient(app).get("/api/company/runs").json()
    assert body["enabled"] is False
    assert body["reason"] == "company mode is off, so no run was opened"


def test_active_only_hides_finished_runs(client, ledger):
    live = ledger.open_run(_goal(goal_id="live"))
    done = ledger.open_run(_goal(goal_id="done", title="Old work"))
    ledger.request_stop(done.id)
    ledger.settle_stop(done.id)
    body = client.get("/api/company/runs?active_only=true").json()
    assert [r["run_id"] for r in body["runs"]] == [live.id]
    assert len(client.get("/api/company/runs").json()["runs"]) == 2


def test_no_task_payload_reaches_the_wire(client, ledger):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="edit", summary="wrote the file", outcome="ok",
                       task_id=9, detail={"content": "SECRET-CONTENTS"})
    assert "SECRET" not in client.get("/api/company/runs").text


def test_the_brief_is_not_cached(client, ledger):
    ledger.open_run(_goal())
    assert client.get("/api/company/runs").headers["cache-control"].startswith("no-cache")


# ── one run ──────────────────────────────────────────────────────────────────

def test_one_run_returns_its_steps_budget_and_verdicts(client, ledger):
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="read it", outcome="ok", task_id=1)
    ledger.record_verdict(run.id, role="verifier", passed=True, reason="holds")
    body = client.get(f"/api/company/runs/{run.id}").json()
    assert body["ok"] is True
    assert body["run"]["id"] == run.id
    assert [s["summary"] for s in body["steps"]] == ["read it"]
    assert body["budget"]["steps_used"] == 1
    assert body["verdicts"][0]["role"] == "verifier"
    assert body["unauthorised_steps"] == []


def test_an_unknown_run_is_a_404_not_an_empty_success(client):
    r = client.get("/api/company/runs/nope")
    assert r.status_code == 404
    assert r.json()["reason"] == "unknown_run"


def test_an_oversized_run_id_is_refused_before_the_ledger(client):
    r = client.get("/api/company/runs/" + "x" * 100)
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_run_id"


# ── stopping ─────────────────────────────────────────────────────────────────

def test_stop_needs_no_approval_because_it_only_narrows(client, ledger):
    """Same shape as revoking a permission: narrowing is always allowed."""
    run = ledger.open_run(_goal())
    ledger.record_step(run.id, kind="research", summary="working", outcome="ok", task_id=1)
    r = client.post(f"/api/company/runs/{run.id}/stop")
    assert r.status_code == 200
    assert r.json()["run"]["status"] == "stopping"
    assert ledger.get(run.id).stop_reason == "owner"


def test_stopping_twice_settles_the_run(client, ledger):
    run = ledger.open_run(_goal())
    client.post(f"/api/company/runs/{run.id}/stop")
    second = client.post(f"/api/company/runs/{run.id}/stop")
    assert second.json()["run"]["status"] == "stopped"


def test_stopping_a_finished_run_is_a_409_with_the_ledger_s_reason(client, ledger):
    run = ledger.open_run(_goal())
    ledger.request_stop(run.id)
    ledger.settle_stop(run.id)
    r = client.post(f"/api/company/runs/{run.id}/stop")
    assert r.status_code == 409
    assert r.json()["reason"] == "run_stopped"


def test_stopping_an_unknown_run_is_a_404(client):
    r = client.post("/api/company/runs/nope/stop")
    assert r.status_code == 404
    assert r.json()["reason"] == "unknown_run"
